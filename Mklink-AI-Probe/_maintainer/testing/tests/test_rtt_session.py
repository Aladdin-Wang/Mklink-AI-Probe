import threading

import pytest

from mklink._types import DeviceState
from mklink.bridge import MKLinkSerialBridge
from mklink.device import Device, DeviceError
from mklink.rtt import RTTSession


class StopSensitiveBridge:
    def __init__(self):
        self.state = DeviceState.RTT_STREAM
        self.raw_writes = []
        self.commands = []

    def _exit_stream(self):
        self.state = DeviceState.READY
        return "tail"

    def _write_raw(self, data):
        self.raw_writes.append(data)

    def send_command(self, command, timeout=5.0):
        self.commands.append(command)
        if command == "RTTView.stop()":
            self.state = DeviceState.ERROR
            raise TimeoutError("prompt is unavailable while stopping RTT")
        if self.state is not DeviceState.READY:
            raise ConnectionError("bridge is not immediately reusable")
        return (
            "Find SEGGER RTT addr 0x20000000\n"
            "UpBuffer Channel 0 Size: 1024 Mode: 0\n>>>"
        )

    def _enter_stream(self, state):
        self.state = state


def test_bridge_rtt_byte_reader_preserves_non_utf8_payload():
    bridge = object.__new__(MKLinkSerialBridge)
    bridge._running = True
    bridge._buffer_lock = threading.Lock()
    payload = "中文".encode("gbk")
    bridge._response_buffer = [payload[:1], payload[1:]]

    assert bridge.read_stream_bytes(duration=0.001) == payload


def test_rtt_stop_uses_raw_stop_and_allows_immediate_restart():
    bridge = StopSensitiveBridge()
    session = RTTSession(bridge)
    session._running = True

    assert session.stop() == "tail"
    assert bridge.state is DeviceState.READY
    assert bridge.raw_writes == [b"RTTView.stop()\n"]
    assert "RTTView.stop()" not in bridge.commands

    result = session.start("0x20000000", search_size=1024)
    assert result["control_block_addr"] == "0x20000000"
    assert bridge.state is DeviceState.RTT_STREAM


def _rtt_control_block_memory():
    header = (
        b"SEGGER RTT" + b"\x00" * 6
        + (3).to_bytes(4, "little")
        + (3).to_bytes(4, "little")
    )

    def descriptor(buffer_address, size, write_offset=0, read_offset=0, flags=0):
        return (
            (0).to_bytes(4, "little")
            + buffer_address.to_bytes(4, "little")
            + size.to_bytes(4, "little")
            + write_offset.to_bytes(4, "little")
            + read_offset.to_bytes(4, "little")
            + flags.to_bytes(4, "little")
        )

    down = (
        descriptor(0x20001000, 16)
        + descriptor(0x20002000, 8, flags=1)
        + descriptor(0, 0)
    )
    return header, down


def test_device_reads_down_buffers_from_standard_rtt_control_block():
    header, down = _rtt_control_block_memory()
    device = Device()
    reads = []

    def read_memory(address, size):
        reads.append((address, size))
        return header if len(reads) == 1 else down

    device.read_memory = read_memory

    assert device._read_rtt_down_buffers(0x20000000) == [
        {"channel": 0, "size": 16, "mode": 0, "active": True, "name": ""},
        {"channel": 1, "size": 8, "mode": 1, "active": True, "name": ""},
        {"channel": 2, "size": 0, "mode": 0, "active": False, "name": ""},
    ]
    assert reads == [
        (0x20000000, 24),
        (0x20000000 + 24 + 3 * 24, 3 * 24),
    ]


def test_device_exact_rtt_start_uses_control_block_down_buffer_fallback():
    header, down = _rtt_control_block_memory()
    bridge = StopSensitiveBridge()
    bridge.state = DeviceState.READY
    device = Device()
    device._connected = True
    device._bridge = bridge
    device.read_memory = lambda _address, size: header if size == 24 else down

    result = device.rtt_start("0x20000000", mode=1, search_size=0)

    assert result["down_buffer_source"] == "target-control-block"
    assert [item["size"] for item in result["down_buffers"]] == [16, 8, 0]
    assert bridge.state is DeviceState.RTT_STREAM


class CorruptDescriptorBridge(StopSensitiveBridge):
    def send_command(self, command, timeout=5.0):
        self.commands.append(command)
        return (
            "Find SEGGER RTT addr 0x20000000\n"
            "UpBuffer Channel 0 Size: 16384 Mode: 0\n"
            "DownBuffer Channel 0 Size: 0 Mode: 536873680\n"
            "DownBuffer Channel 2 Size: 640616 Mode: 536873680\n>>>"
        )


@pytest.mark.parametrize(("mode", "search_size"), [(0, 1024), (1, 0)])
def test_device_rtt_start_prefers_target_down_buffers_over_corrupt_probe_output(
    mode, search_size,
):
    header, down = _rtt_control_block_memory()
    bridge = CorruptDescriptorBridge()
    bridge.state = DeviceState.READY
    device = Device()
    device._connected = True
    device._bridge = bridge
    device.read_memory = lambda _address, size: header if size == 24 else down

    result = device.rtt_start(
        "0x20000000", mode=mode, search_size=search_size,
    )

    assert result["down_buffer_source"] == "target-control-block"
    assert [item["size"] for item in result["down_buffers"]] == [16, 8, 0]


class ExactModeUnsupportedBridge(StopSensitiveBridge):
    def __init__(self):
        super().__init__()
        self.exact_start_pending = False

    def send_command(self, command, timeout=5.0):
        self.commands.append(command)
        if ",0,0)" in command:
            self.exact_start_pending = True
            return ">>>"
        if command == "RTTView.stop()":
            self.exact_start_pending = False
            return ">>>"
        if ",4,0)" in command:
            if self.exact_start_pending:
                return ">>>"
            return (
                "Find SEGGER RTT addr 0x20000000\n"
                "UpBuffer Channel 0 Size: 1024 Mode: 0\n"
                "DownBuffer Channel 0 Size: 0 Mode: 536873680\n"
                "DownBuffer Channel 2 Size: 640616 Mode: 536873680\n>>>"
            )
        raise AssertionError(command)


def test_device_exact_rtt_start_resets_probe_before_bounded_scan_fallback():
    header, down = _rtt_control_block_memory()
    bridge = ExactModeUnsupportedBridge()
    bridge.state = DeviceState.READY
    device = Device()
    device._connected = True
    device._bridge = bridge
    device.read_memory = lambda _address, size: header if size == 24 else down

    result = device.rtt_start("0x20000000", mode=1, search_size=0)

    assert bridge.commands[:3] == [
        "RTTView.start(0x20000000,0,0)",
        "RTTView.stop()",
        "RTTView.start(0x20000000,4,0)",
    ]
    assert result["probe_compatibility_mode"] == "bounded-scan"
    assert result["storage_mode"] == 1
    assert result["down_buffer_source"] == "target-control-block"
    assert [item["size"] for item in result["down_buffers"]] == [16, 8, 0]


def test_device_exact_rtt_start_resolves_configured_address_before_fallback(tmp_path):
    from mklink.project_config import save_rtt_config

    save_rtt_config(str(tmp_path), {
        "rtt_addr": "0x20000000",
        "rtt_storage_mode": 1,
    })
    header, down = _rtt_control_block_memory()
    bridge = ExactModeUnsupportedBridge()
    bridge.state = DeviceState.READY
    device = Device(project_root=str(tmp_path))
    device._connected = True
    device._bridge = bridge
    device.read_memory = lambda _address, size: header if size == 24 else down

    result = device.rtt_start(mode=1, search_size=0)

    assert bridge.commands[:3] == [
        "RTTView.start(0x20000000,0,0)",
        "RTTView.stop()",
        "RTTView.start(0x20000000,4,0)",
    ]
    assert result["control_block_addr"] == "0x20000000"
    assert result["down_buffer_source"] == "target-control-block"


def test_device_rtt_start_rejects_missing_control_block():
    bridge = ExactModeUnsupportedBridge()
    bridge.state = DeviceState.READY
    bridge.send_command = lambda _command, timeout=5.0: ">>>"
    device = Device()
    device._connected = True
    device._bridge = bridge
    device.read_memory = lambda _address, _size: b"\x00" * 24

    with pytest.raises(DeviceError, match="control block"):
        device.rtt_start("0x20000000", mode=1, search_size=0)
