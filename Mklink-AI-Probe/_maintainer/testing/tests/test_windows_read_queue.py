"""Native read ownership: no buffer reuse before completion/cancellation."""
import ctypes
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows CDC API')


@pytest.fixture
def native_reads(monkeypatch):
    from serial import win32
    state = SimpleNamespace(pending={}, events=set(), next_event=1, error=0,
                            posts=0, resets=0, fail_at=None, read_error=None)

    def create(*args):
        event = state.next_event
        state.next_event += 1
        state.events.add(event)
        return event

    def post(handle, buffer, size, count, ptr):
        if state.posts == state.fail_at:
            state.error = 5
            return False
        event = ptr._obj.hEvent
        assert event not in state.pending, 'reuse before completion'
        state.pending[event] = [buffer, bytes([state.posts % 256]) * 7, False]
        state.posts += 1
        state.error = win32.ERROR_IO_PENDING
        return False

    def result(handle, ptr, count, wait):
        buffer, data, cancelled = state.pending.pop(ptr._obj.hEvent)
        if state.read_error:
            state.error = state.read_error
            return False
        if cancelled:
            count._obj.value = 0
            state.error = win32.ERROR_OPERATION_ABORTED
            return False
        ctypes.memmove(buffer, data, len(data))
        count._obj.value = len(data)
        return True

    def cancel(handle, ptr):
        if ptr._obj.hEvent in state.pending:
            state.pending[ptr._obj.hEvent][2] = True
        return True

    def close(event):
        assert event not in state.pending, 'released live DMA buffer/event'
        state.events.remove(event)
        return True

    for name, fn in {'GetCommTimeouts': lambda *a: True,
                     'SetCommTimeouts': lambda *a: True,
                     'CreateEvent': create, 'ResetEvent': lambda *a: True,
                     'ReadFile': post, 'GetOverlappedResult': result,
                     'CancelIoEx': cancel, 'CloseHandle': close,
                     'WaitForSingleObject': lambda *a: 258,
                     'GetLastError': lambda: state.error}.items():
        monkeypatch.setattr(win32, name, fn)
    def purge():
        assert not state.pending
        state.resets += 1
    state.port = SimpleNamespace(_port_handle=123, reset_input_buffer=purge)
    return state


def test_ordered_completion_reposts_and_cancel_reaps_before_free(native_reads):
    from mklink._serial_worker import _WindowsReadQueue
    state = native_reads
    reader = _WindowsReadQueue(state.port)
    assert len(state.pending) == 8
    for i in range(24):
        assert reader.read() == bytes([i]) * 7
        assert len(state.pending) == 8
    reader.cancel()
    assert reader.read() == b''
    reader.close()
    reader.close()
    assert not state.pending and not state.events


def test_reset_drains_old_requests_before_purge_and_new_generation(native_reads):
    from mklink._serial_worker import _WindowsReadQueue
    state = native_reads
    reader = _WindowsReadQueue(state.port)
    reader.reset()
    assert state.resets == 1 and reader.read() == b'\x08' * 7
    reader.close()
    assert not state.pending and not state.events


def test_partial_initialization_failure_cancels_all_submitted_requests(native_reads):
    import serial
    from mklink._serial_worker import _WindowsReadQueue
    state = native_reads
    state.fail_at = 3
    with pytest.raises(serial.SerialException, match='queue CDC read'):
        _WindowsReadQueue(state.port)
    assert not state.pending and not state.events


@pytest.mark.parametrize('code', [31, 121, 995, 1167])
def test_read_failure_preserves_native_code_without_reposting(native_reads, code):
    import serial
    from mklink._serial_worker import _WindowsReadQueue
    reader = _WindowsReadQueue(native_reads.port)
    native_reads.read_error = code
    with pytest.raises(serial.SerialException, match=f'WinError {code}'):
        reader.read()
    assert native_reads.posts == 8 and len(native_reads.pending) == 7
    reader.close()
    assert not native_reads.pending and not native_reads.events


def test_expected_cancel_during_completion_does_not_report_failure(native_reads, monkeypatch):
    from serial import win32
    from mklink._serial_worker import _WindowsReadQueue
    reader = _WindowsReadQueue(native_reads.port)
    complete = win32.GetOverlappedResult
    def cancel_then_complete(*args):
        reader.cancel()
        return complete(*args)
    monkeypatch.setattr(win32, 'GetOverlappedResult', cancel_then_complete)
    assert reader.read() == b''
    reader.close()
    assert not native_reads.pending and not native_reads.events


def test_incomplete_read_is_bounded_and_keeps_request_storage(native_reads, monkeypatch):
    from serial import win32
    from mklink._serial_worker import _WindowsReadQueue
    reader = _WindowsReadQueue(native_reads.port)
    complete = win32.GetOverlappedResult
    def incomplete(handle, ov, count, wait):
        assert not wait, 'control must not wait behind blocking native IO'
        native_reads.error = 996
        return False
    monkeypatch.setattr(win32, 'GetOverlappedResult', incomplete)
    assert reader.read() == b''
    assert len(native_reads.pending) == 8 and native_reads.posts == 8
    monkeypatch.setattr(win32, 'GetOverlappedResult', complete)
    reader.close()
    assert not native_reads.pending and not native_reads.events


def test_failed_cancellation_never_purges_reposts_or_frees_live_requests(native_reads, monkeypatch):
    from serial import win32
    from mklink import _serial_worker as worker
    reader = worker._WindowsReadQueue(native_reads.port)
    complete = win32.GetOverlappedResult
    clock = iter([0, 2])
    monkeypatch.setattr(worker.time, 'monotonic', lambda: next(clock))
    def incomplete(*args):
        assert args[-1] is False
        native_reads.error = 996
        return False
    monkeypatch.setattr(win32, 'GetOverlappedResult', incomplete)
    with pytest.raises(worker._PendingReadTimeout, match='cancellation'):
        reader.reset()
    assert native_reads.resets == 0 and native_reads.posts == 8
    assert len(native_reads.pending) == len(native_reads.events) == 8
    assert reader in worker._unreaped_readers
    monkeypatch.setattr(win32, 'GetOverlappedResult', complete)
    monkeypatch.setattr(worker.time, 'monotonic', lambda: 0)
    reader.close()
    worker._unreaped_readers.remove(reader)
