"""Startup performance, accurate rejection and transport ownership regressions."""
import struct
import threading
import time
from types import SimpleNamespace

import pytest

from mklink.device import Device, DeviceError
from mklink.bridge import MKLinkSerialBridge
from mklink.mux import MuxTransport, MuxError, packet
from mklink.remote.dashboards import RttStreamManager


def target(device, ram_limit=0x20001000):
    base = 0x20000000
    memory = bytearray(4096)
    memory[:24] = b'SEGGER RTT' + bytes(6) + struct.pack('<II', 1, 1)
    memory[24:48] = struct.pack('<6I', 0, base+128, 256, 100, 128, 0)
    memory[48:72] = struct.pack('<6I', 0, base+512, 256, 0, 0, 0)
    device.read_memory = lambda address, size: bytes(memory[address-base:address-base+size])
    device._get_mcu_profile = lambda: {'regions': [{'name': 'ram', 'start': hex(base), 'size': hex(ram_limit-base)}]}
    return memory


def test_ram_snapshot_parses_elf_once_and_is_not_reused_after_start(tmp_path, monkeypatch):
    from mklink import elf_backend
    device = Device(project_root=str(tmp_path))
    target(device)
    source = tmp_path/'target.elf'
    source.write_bytes(b'fixture')
    device._axf = str(source)
    device._get_mcu_profile = lambda: None
    calls = []
    ranges = [(0x20000000, 0x20001000)]
    def parse(*a, **k):
        calls.append(source.read_bytes())
        return tuple(ranges)
    monkeypatch.setattr(elf_backend, 'writable_memory_ranges', parse)
    assert device._find_rtt_control_block(0x20000000, 256) == 0x20000000
    assert len(calls) == 1
    source.write_bytes(b'changed')
    ranges[:] = [(0x20000000, 0x20000060)]
    with pytest.raises(DeviceError, match='outside known target writable RAM'):
        device._find_rtt_control_block(0x20000000, 4)
    assert calls == [b'fixture', b'changed']


def test_readable_signature_reports_descriptor_failure(tmp_path):
    device = Device(project_root=str(tmp_path))
    target(device, 0x20000060)
    with pytest.raises(DeviceError, match='signature found.*UpBuffer 0.*outside known target writable RAM'):
        device._find_rtt_control_block(0x20000000, 4)


@pytest.mark.parametrize('signature', [False, True])
def test_scan_near_ram_end_only_reports_signatures_actually_seen(tmp_path, signature):
    device = Device(project_root=str(tmp_path))
    memory = target(device)
    if signature:
        memory[-16:-6] = b'SEGGER RTT'
        with pytest.raises(DeviceError, match='signature found.*header is outside'):
            device._find_rtt_control_block(0x20000FF0, 4)
    else:
        assert device._find_rtt_control_block(0x20000FF0, 4) is None


def test_ram_snapshot_does_not_leak_between_threads(tmp_path):
    device = Device(project_root=str(tmp_path))
    target(device)
    original = device.read_memory
    entered, release = threading.Event(), threading.Event()
    first_thread = None
    def read(addr, size):
        if threading.current_thread() is first_thread:
            entered.set()
            assert release.wait(2)
        return original(addr, size)
    device.read_memory = read
    outcomes = []
    first_thread = threading.Thread(target=lambda: outcomes.append(device._find_rtt_control_block(0x20000000, 4)))
    first_thread.start()
    assert entered.wait(2)
    device._get_mcu_profile = lambda: {'regions': [{'name': 'ram', 'start': '0x20000000', 'size': '0x60'}]}
    try:
        with pytest.raises(DeviceError, match='validation failed'):
            device._find_rtt_control_block(0x20000000, 4)
    finally:
        release.set(); first_thread.join(2)
    assert outcomes == [0x20000000]


def test_rtt_failure_is_queryable_while_cleanup_keeps_worker_owned():
    entered, release = threading.Event(), threading.Event()
    class FailedDevice:
        def rtt_start(self, *a, **k): raise DeviceError('original target failure')
        def rtt_stop(self):
            entered.set()
            assert release.wait(3)
    manager = RttStreamManager()
    manager.start(FailedDevice())
    assert entered.wait(2)
    statuses = []
    query = threading.Thread(target=lambda: statuses.append(manager.get_status()))
    query.start(); query.join(.5)
    try:
        assert not query.is_alive(), 'Status must not block behind target cleanup'
        assert statuses[0]['error'] == 'original target failure'
        assert statuses[0]['progress_state'] == 'error'
        assert manager._thread.is_alive() and manager.running
    finally:
        release.set(); manager._thread.join(2); query.join(2)


def test_mux_reader_drains_queued_heartbeat_before_timeout():
    transport = MuxTransport(lambda data: len(data))
    transport.epoch = 17
    transport.ready = True
    transport._send(2, b'', heartbeat=True)
    op, request, _, heartbeat = transport._pending
    transport._pending = (op, request, time.monotonic()-.1, heartbeat)
    reply = packet(0x82, 17, request, b'\0')
    bridge = MKLinkSerialBridge.__new__(MKLinkSerialBridge)
    bridge._mux, bridge._running = transport, True
    def read(size):
        bridge._running = False
        return reply
    bridge._serial = SimpleNamespace(in_waiting=len(reply), read=read)
    bridge._reader_loop()
    assert transport._error is None and transport._pending is None


def test_mux_real_missing_reply_preserves_identity_and_forbids_replay():
    sent = []
    transport = MuxTransport(sent.append)
    transport.epoch = 17
    transport._send(0x12, b'data')
    op, request, _, heartbeat = transport._pending
    transport._pending = (op, request, time.monotonic()-.1, heartbeat)
    transport.tick()
    with pytest.raises(MuxError, match=r'opcode=0x12.*request=1.*heartbeat=False'):
        transport.request(0x12, b'data')
    assert len(sent) == 1
    assert transport.stats()['last_timeout']['opcode'] == '0x12'


def test_mux_heartbeat_write_disconnect_uses_bridge_failure_boundary():
    from mklink._types import DeviceState
    def write(data): raise ConnectionError('probe disconnected during heartbeat')
    transport = MuxTransport(write)
    transport.ready = True
    transport._last_command = time.monotonic()-2
    bridge = MKLinkSerialBridge.__new__(MKLinkSerialBridge)
    bridge._mux, bridge._running = transport, True
    bridge._ctx = SimpleNamespace(state=DeviceState.READY)
    bridge._prompt_event = threading.Event()
    bridge._serial = SimpleNamespace(in_waiting=0, read=lambda size:b'')
    bridge._reader_loop()
    assert bridge._ctx.state == DeviceState.ERROR
    assert bridge._prompt_event.is_set()
    assert str(transport._error) == 'probe disconnected during heartbeat'
    assert isinstance(bridge._transport_error, ConnectionError)
