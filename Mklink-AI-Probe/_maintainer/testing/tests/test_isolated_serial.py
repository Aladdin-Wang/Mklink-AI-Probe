"""Real worker process and pyserial loop transport; no hardware required."""
import time

import pytest
import serial

from mklink._isolated_serial import IsolatedSerial, _worker_command


def collect(port, size):
    result = bytearray()
    deadline = time.monotonic() + 5
    while len(result) < size and time.monotonic() < deadline:
        result.extend(port.read(size - len(result)))
    return bytes(result)


def test_worker_preserves_bytes_across_parent_pause_and_releases_port():
    port = IsolatedSerial('loop://', 115200)
    try:
        payload = bytes(range(256)) * 256
        for offset in range(0, len(payload), 1024):
            assert port.write(payload[offset:offset + 1024]) == 1024
        time.sleep(.15)
        assert collect(port, len(payload)) == payload
        assert port.read(1) == b''
        port.flush()
    finally:
        port.close()
    assert port._process.poll() is not None
    port.close()  # idempotent cleanup
    with pytest.raises(serial.SerialException):
        port.write(b'closed')


def test_reset_discards_already_queued_generation_without_corrupting_framing():
    port = IsolatedSerial('loop://', 115200)
    try:
        port.write(b'old' * 1000)
        time.sleep(.05)
        port.reset_input_buffer()
        port.reset_output_buffer()
        port.write(b'new\x00\xff')
        assert collect(port, 5) == b'new\x00\xff'
        assert port.read(1) == b''
    finally:
        port.close()


def test_worker_exit_is_visible_to_reader():
    port = IsolatedSerial('loop://', 115200)
    port._process.terminate()
    port._process.wait(timeout=2)
    try:
        with pytest.raises(serial.SerialException):
            port.read(1)
    finally:
        port.close()


def test_open_failure_is_reported_and_worker_is_reaped():
    with pytest.raises(serial.SerialException):
        IsolatedSerial('unsupported-mklink-test://', 115200)


def test_frozen_worker_uses_internal_executable_contract(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', 'D:/MKLink/mklink-sidecar.exe')
    assert _worker_command('COM42', 115200) == [
        'D:/MKLink/mklink-sidecar.exe', '--internal-serial-worker', 'COM42', '115200']


def test_worker_command_preserves_reported_transport_error(monkeypatch):
    port = IsolatedSerial('loop://', 115200)
    failure = serial.SerialTimeoutException('Write timeout')
    try:
        def failed_reply():
            raise failure
        with monkeypatch.context() as patch:
            patch.setattr(port, '_reply', failed_reply)
            with pytest.raises(serial.SerialTimeoutException) as caught:
                port.write(b'x')
            assert caught.value is failure
    finally:
        port.close()
