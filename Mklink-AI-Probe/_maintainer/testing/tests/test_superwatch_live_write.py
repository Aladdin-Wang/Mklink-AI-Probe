"""Live-control framing and real worker lifecycle, with a simulated wire peer."""
import binascii
from concurrent.futures import Future
import struct
import time
from types import SimpleNamespace

import pytest

from mklink.dump_memory import DumpMemoryParser, DumpMemoryStreamSession, MAGIC
from mklink.remote.dashboards import SuperWatchStreamManager
from mklink.superwatch import SuperWatchRuntime, WatchItem
from test_rtt_superwatch_streaming import _symbol_write_device, _dump_frame


def ack(request_id=1, address=0x20000020, value=1.5, status=0):
    body = MAGIC + struct.pack('<QHBBIIBB8s', 12000, 42, 0, 0x57,
                              request_id, address, 4, status, struct.pack('<f', value))
    return body + struct.pack('<I', binascii.crc32(body))


@pytest.mark.parametrize('split', range(1, 42))
def test_ack_fragmented_among_samples(split):
    parser = DumpMemoryParser([4])
    wire = ack()
    frames = parser.feed(_dump_frame(1000, b'abcd') + wire[:split])
    frames += parser.feed(wire[split:] + _dump_frame(13000, b'efgh'))
    assert [x['format'] for x in frames] == ['OLD', 'WRITE_ACK', 'OLD']
    assert frames[1]['request_id'] == 1
    assert frames[1]['data'] == struct.pack('<f', 1.5)
    assert parser.crc_errors == 0


def test_corrupt_ack_is_not_success():
    wire = bytearray(ack()); wire[30] ^= 1
    parser = DumpMemoryParser([4])
    assert parser.feed(wire) == []
    assert parser.crc_errors == 1


class Peer:
    def __init__(self, live=True):
        self.live = live
        self.writes = []
        self.chunks = []
        self.timestamp = 1000
        self.value = 0.0
        self.ack_status = 0
        self.suppress_ack = False

    def supports_dump_write(self): return self.live
    def _enter_stream(self, state): self.state = state
    def _exit_stream(self): pass
    def _stop_stream_and_sync(self, data):
        self.writes.append(data)
        return True

    def _write_raw(self, data):
        self.writes.append(data)
        if data.startswith(b'\x1e'):
            packet = bytes.fromhex(data[1:].decode().strip())
            assert binascii.crc32(packet[:24]) == struct.unpack_from('<I', packet, 24)[0]
            _, req, address, size, payload = struct.unpack('<4sIIB3x8s', packet[:24])
            self.value = struct.unpack('<f', payload[:size])[0]
            if not self.suppress_ack:
                self.chunks.append(ack(req, address, self.value, self.ack_status))

    def drain_stream_bytes(self, max_bytes=None):
        self.timestamp += 1000
        return (self.chunks.pop(0) if self.chunks else b'') + _dump_frame(self.timestamp, struct.pack('<f', self.value))


def manager_peer(tmp_path, live=True, write_error=None):
    device, operations = _symbol_write_device(tmp_path, write_error=write_error)
    peer = Peer(live)
    device._bridge = peer
    device.read_memory = lambda address, size: struct.pack('<f', peer.value)
    original_write = device.write_memory
    def write(address, data):
        original_write(address, data)
        peer.value = struct.unpack('<f', data)[0]
    device.write_memory = write
    manager = SuperWatchStreamManager()
    manager._runtime = SuperWatchRuntime(items=[WatchItem('gain', 0x20000020, 'float', 4)])
    manager.start(device)
    end = time.monotonic() + 1
    while manager._origin_us is None and time.monotonic() < end: time.sleep(.001)
    assert manager._origin_us is not None
    return manager, peer, operations


@pytest.mark.parametrize('live', [True, False])
@pytest.mark.parametrize('paused', [True, False])
def test_write_preserves_worker_epoch_origin_and_paused_state(tmp_path, live, paused):
    manager, peer, operations = manager_peer(tmp_path, live)
    try:
        if paused: manager.pause()
        before = (manager._thread, manager._origin_us, manager._metadata_version)
        result = manager.write_symbol('gain', generation=1, value=1.5)
        assert result['verified'] and result['value'] == 1.5
        assert result['mode'] == ('live' if live else 'legacy-gap')
        assert (manager._thread, manager._origin_us, manager._metadata_version) == before
        assert manager.get_status()['state'] == ('paused' if paused else 'running')
        assert len(manager.get_status()['write_events']) == 1
        if live:
            assert not operations
            assert not any(b'-1.0' in b for b in peer.writes)
        else:
            assert len(operations) == 1
            assert any(b'-1.0' in b for b in peer.writes)
    finally:
        manager.stop()


@pytest.mark.parametrize('live', [True, False])
def test_rejected_write_does_not_reset_or_stop_capture(tmp_path, live):
    manager, peer, _ = manager_peer(tmp_path, live, RuntimeError('flush failed') if not live else None)
    peer.ack_status = 3
    try:
        before = manager._metadata_version
        manager.pause()
        with pytest.raises(RuntimeError, match='failed'):
            manager.write_symbol('gain', generation=1, value=2.0)
        assert manager.get_status()['state'] == 'paused'
        assert manager._metadata_version == before
        assert manager.get_status()['write_events'] == []
    finally: manager.stop()


def test_session_stop_fails_pending_write_without_retry():
    peer = Peer(); peer.suppress_ack = True
    session = DumpMemoryStreamSession(peer, [(0x20000020, 4)], .001)
    session.start()
    future = Future()
    session.request_write(0x20000020, struct.pack('<f', 2), future)
    session.read_frames()
    assert not future.done()
    session.stop()
    with pytest.raises(RuntimeError, match='result unknown'): future.result()
    assert sum(x.startswith(b'\x1e') for x in peer.writes) == 1


def test_wrong_request_ack_ignored_and_not_counted_as_sample():
    peer = Peer(); peer.suppress_ack = True
    session = DumpMemoryStreamSession(peer, [(0x20000020, 4)], .001)
    session.start(); future = Future()
    session.request_write(0x20000020, struct.pack('<f', 2), future)
    peer.chunks.append(ack(request_id=0))
    samples = session.read_frames()
    assert len(samples) == 1 and not future.done()
    assert session.stats['complete_samples'] == 1
    session.stop()


def test_stopping_worker_rejects_idle_write(tmp_path):
    from unittest.mock import Mock
    device, operations = _symbol_write_device(tmp_path)
    manager = SuperWatchStreamManager()
    manager._device = device
    manager._thread = Mock()
    manager._thread.is_alive.return_value = True
    manager._stop_event.set()
    with pytest.raises(RuntimeError, match='stopping'):
        manager.write_symbol('gain', generation=1, value=2.0)
    assert operations == []
