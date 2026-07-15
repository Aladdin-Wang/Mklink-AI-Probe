from pathlib import Path

import pytest
from intelhex import IntelHex

from mklink.device import Device, DeviceError


class _FlashStub:
    def set_swd_clock(self, _clock: int) -> None:
        pass

    def burn_hex(self, _firmware: str, progress_callback=None) -> dict:
        return {"success": True}

    def burn_bin(self, _firmware: str, _address: str, progress_callback=None) -> dict:
        return {"success": True}


class _BridgeStub:
    def __init__(self):
        self.calls = []

    def send_command(self, command: str, timeout: float):
        self.calls.append((command, timeout))
        return "0"


def _device(read_memory):
    device = Device(mcu="custom", project_root="")
    device._connected = True
    device._bridge = object()
    device._flash = _FlashStub()
    device._get_mcu_profile = lambda: None
    device.read_memory = read_memory
    device.reset = lambda: None
    return device


def _write_hex(path: Path, data: bytes, address: int = 0x08000000) -> None:
    image = IntelHex()
    image.puts(address, data)
    image.write_hex_file(str(path))


def test_device_flash_verify_reads_back_hex_before_reset(tmp_path: Path):
    firmware = tmp_path / "firmware.hex"
    expected = bytes(range(32))
    _write_hex(firmware, expected)
    calls = []

    def read_memory(address: int, size: int) -> bytes:
        calls.append(("read", address, size))
        return expected[address - 0x08000000:address - 0x08000000 + size]

    device = _device(read_memory)
    device.reset = lambda: calls.append(("reset",))

    result = device.flash(str(firmware), verify=True, reset_after=True)

    assert result["verified"] is True
    assert calls[0][0] == "read"
    assert calls[-1] == ("reset",)


def test_device_flash_verify_rejects_mismatched_hex(tmp_path: Path):
    firmware = tmp_path / "firmware.hex"
    _write_hex(firmware, b"expected")
    device = _device(lambda _address, size: b"X" * size)

    with pytest.raises(DeviceError, match="Flash verify failed"):
        device.flash(str(firmware), verify=True, reset_after=False)


def test_device_flash_can_skip_readback_when_verify_is_false(tmp_path: Path):
    firmware = tmp_path / "firmware.hex"
    _write_hex(firmware, b"expected")
    device = _device(
        lambda _address, _size: (_ for _ in ()).throw(
            AssertionError("readback must be skipped")
        )
    )

    result = device.flash(str(firmware), verify=False, reset_after=False)

    assert result["verified"] is False


def test_device_flash_verify_reads_multiple_hex_segments_and_chunk_tail(
    tmp_path: Path,
):
    firmware = tmp_path / "firmware.hex"
    first = bytes(index % 251 for index in range(1025))
    second = b"tail"
    image = IntelHex()
    image.puts(0x08000000, first)
    image.puts(0x08002000, second)
    image.write_hex_file(str(firmware))
    regions = {0x08000000: first, 0x08002000: second}
    calls = []

    def read_memory(address: int, size: int) -> bytes:
        calls.append((address, size))
        for start, data in regions.items():
            if start <= address < start + len(data):
                offset = address - start
                return data[offset:offset + size]
        raise AssertionError(f"unexpected address: {address:#x}")

    result = _device(read_memory).flash(
        str(firmware), verify=True, reset_after=False
    )

    assert result["verified"] is True
    assert calls == [
        (0x08000000, 1024),
        (0x08000400, 1),
        (0x08002000, 4),
    ]


def test_device_flash_verify_reads_bin_from_flash_base(tmp_path: Path):
    firmware = tmp_path / "firmware.bin"
    expected = bytes(index % 251 for index in range(1100))
    firmware.write_bytes(expected)
    calls = []

    def read_memory(address: int, size: int) -> bytes:
        calls.append((address, size))
        offset = address - 0x08000000
        return expected[offset:offset + size]

    result = _device(read_memory).flash(
        str(firmware), verify=True, reset_after=False
    )

    assert result["verified"] is True
    assert calls == [(0x08000000, 1024), (0x08000400, 76)]


def test_device_reset_sends_target_reset_command_only():
    device = Device()
    bridge = _BridgeStub()
    device._connected = True
    device._bridge = bridge

    device.reset()

    assert bridge.calls == [("cmd.reset_chip()", 10.0)]
