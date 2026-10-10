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


def test_dead_receiver_rejects_writes_and_resets_but_allows_clean_close(monkeypatch):
    import sys
    from mklink import _isolated_serial
    script = '''
from mklink import _serial_worker as worker
import serial
class Port:
    in_waiting = 0
    def read(self, size): raise serial.SerialException('injected CDC failure (WinError 31)')
    def write(self, data): raise AssertionError('write reached dead receiver')
    def reset_input_buffer(self): raise AssertionError('reset resurrected dead receiver')
    def cancel_read(self): pass
    def close(self): pass
worker.serial.serial_for_url = lambda *a, **kw: Port()
worker.main(['test', '115200'])
'''
    monkeypatch.setattr(_isolated_serial, '_worker_command', lambda *args: [sys.executable, '-c', script])
    port = IsolatedSerial('test', 115200)
    try:
        with pytest.raises(serial.SerialException, match='WinError 31'):
            collect(port, 1)
        with pytest.raises(serial.SerialException, match='WinError 31'):
            port.write(b'never replay')
        with pytest.raises(serial.SerialException, match='WinError 31'):
            port.reset_input_buffer()
    finally:
        port.close()
    assert port._process.poll() is not None


def test_busy_receiver_cannot_starve_reset_and_close(monkeypatch):
    import sys
    from mklink import _isolated_serial
    script = '''
from mklink import _serial_worker as worker
import time
class Port:
    in_waiting = 0
    def read(self, size):
        time.sleep(.02)
        return b''
    def reset_input_buffer(self): pass
    def cancel_read(self): pass
    def close(self): pass
worker.serial.serial_for_url = lambda *a, **kw: Port()
worker.main(['test', '115200'])
'''
    monkeypatch.setattr(_isolated_serial, '_worker_command', lambda *a: [sys.executable, '-c', script])
    port = IsolatedSerial('test', 115200)
    started = time.monotonic()
    try:
        for _ in range(20):
            port.reset_input_buffer()
        assert port._epoch == 20
    finally:
        port.close()
    assert time.monotonic() - started < 3


def test_unresponsive_receiver_exits_after_bounded_reset(monkeypatch):
    import sys
    from mklink import _isolated_serial
    script = '''
from mklink import _serial_worker as worker
import threading
class Port:
    in_waiting = 0
    def read(self, size): threading.Event().wait()
    def cancel_read(self): pass
    def close(self): pass
worker.serial.serial_for_url = lambda *a, **kw: Port()
worker.main(['test', '115200'])
'''
    monkeypatch.setattr(_isolated_serial, '_worker_command', lambda *a: [sys.executable, '-c', script])
    port = IsolatedSerial('test', 115200)
    started = time.monotonic()
    try:
        with pytest.raises(serial.SerialException, match='did not pause'):
            port.reset_input_buffer()
    finally:
        port.close()
    assert time.monotonic() - started < 3
    assert port._process.poll() is not None


def test_missing_control_reply_disposes_worker_without_replay(monkeypatch):
    from mklink._isolated_serial import _ControlFailure
    port = IsolatedSerial('loop://', 115200)
    def missing():
        raise _ControlFailure('reply deadline')
    monkeypatch.setattr(port, '_reply', missing)
    with pytest.raises(_ControlFailure):
        port.write(b'once')
    assert not port.is_open and port._process.poll() is not None
    with pytest.raises(serial.SerialException, match='closed'):
        port.write(b'never replay')
    port.close()


@pytest.mark.parametrize('drain', [False, True])
def test_receive_failure_under_backpressure_remains_visible_and_close_is_bounded(monkeypatch, drain):
    import sys
    from mklink import _isolated_serial
    script = '''
from mklink import _serial_worker as worker
import queue, serial
Queue = queue.Queue
worker.queue.Queue = lambda **kw: Queue(maxsize=2)
class Port:
    in_waiting = 4096
    reads = 0
    def read(self, size):
        self.reads += 1
        if self.reads > 4: raise serial.SerialException('backpressure RX failure')
        return b'x' * 4096
    def cancel_read(self): pass
    def close(self): pass
worker.serial.serial_for_url = lambda *a, **kw: Port()
worker.main(['test', '115200'])
'''
    monkeypatch.setattr(_isolated_serial, '_worker_command', lambda *a: [sys.executable, '-c', script])
    port = IsolatedSerial('test', 115200)
    time.sleep(.1)  # Let the unread data pipe apply backpressure.
    try:
        if drain:
            with pytest.raises(serial.SerialException, match='backpressure RX failure'):
                collect(port, 65536)
    finally:
        started = time.monotonic()
        port.close()
    assert time.monotonic() - started < 3


def test_closed_state_is_not_published_until_worker_reap_finishes(monkeypatch):
    import threading
    from mklink._isolated_serial import _ControlFailure
    port = IsolatedSerial('loop://', 115200)
    waiting, release = threading.Event(), threading.Event()
    original_wait = port._process.wait
    failures = []
    def delayed_wait(*args, **kwargs):
        waiting.set()
        assert release.wait(3)
        return original_wait(*args, **kwargs)
    def missing():
        raise _ControlFailure('reply deadline')
    monkeypatch.setattr(port._process, 'wait', delayed_wait)
    monkeypatch.setattr(port, '_reply', missing)
    def send():
        try:
            port.write(b'once')
        except _ControlFailure as exc:
            failures.append(exc)
    thread = threading.Thread(target=send)
    thread.start()
    try:
        assert waiting.wait(3)
        assert port.is_open, 'Bridge must not skip cleanup and release its port lock yet'
    finally:
        release.set()
        thread.join(3)
        port.close()
    assert not thread.is_alive() and len(failures) == 1
    assert not port.is_open and port._process.poll() is not None
