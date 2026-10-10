"""Private serial I/O worker. stdout is binary RX; stderr is JSON control.

Run as a script in the bundled Python runtime, independently of the UI/GIL.
Only this process opens the port. The caller retains the application port lock.
"""
import base64
import json
import os
import queue
import struct
import sys
import threading
import time

# Executed by filename: do not shadow pyserial with mklink/serial/.
if __package__ in (None, ''):
    sys.path.pop(0)
import serial

# Retain ctypes storage even while a constructor unwinds on failed cancellation.
# The worker exits immediately after reporting that failure.
_unreaped_readers = []


class _PendingReadTimeout(serial.SerialException):
    """Only process termination may release storage still owned by the driver."""


class _WindowsReadQueue:
    """Keep CDC reads posted while Python is descheduled (128 KiB bounded).

    Consume in submission order. Each request owns its buffer and event until
    completion, including cancellation; USB never writes into recycled memory.
    Only the receive thread reads. Control pauses it before reset/close.
    """

    def __init__(self, port):
        import ctypes
        from collections import deque
        from serial import win32

        self._ctypes, self._api, self._port = ctypes, win32, port
        self._slots = deque()
        self._closed = False
        self._lock = threading.Lock()
        timeout = win32.COMMTIMEOUTS()
        if not win32.GetCommTimeouts(port._port_handle, ctypes.byref(timeout)):
            raise serial.SerialException('Cannot read CDC timeouts')
        # A quiet command reply completes promptly; continuous acquisition fills
        # requests without depending on a new user-space ReadFile every 4 KiB.
        timeout.ReadIntervalTimeout = 2
        timeout.ReadTotalTimeoutMultiplier = 0
        timeout.ReadTotalTimeoutConstant = 100
        if not win32.SetCommTimeouts(port._port_handle, ctypes.byref(timeout)):
            raise serial.SerialException('Cannot set CDC receive timeouts')
        try:
            for _ in range(8):
                ov = win32.OVERLAPPED()
                ov.hEvent = win32.CreateEvent(None, 1, 0, None)
                if not ov.hEvent:
                    raise serial.SerialException('Cannot create CDC receive event')
                slot = [ov, ctypes.create_string_buffer(16384), False]
                self._slots.append(slot)
                self._post(slot)
        except BaseException:
            self.close()
            raise

    def _post(self, slot):
        ov, buffer, _ = slot
        api, ctypes = self._api, self._ctypes
        api.ResetEvent(ov.hEvent)
        count = api.DWORD()
        ok = api.ReadFile(self._port._port_handle, buffer, len(buffer),
                          ctypes.byref(count), ctypes.byref(ov))
        if not ok:
            error = api.GetLastError()
            if error != api.ERROR_IO_PENDING:
                raise serial.SerialException(f'Cannot queue CDC read (WinError {error}: {ctypes.FormatError(error).strip()})')
        slot[2] = True

    def read(self):
        if self._closed:
            return b''
        slot = self._slots[0]
        ov, buffer, _ = slot
        api, ctypes = self._api, self._ctypes
        count = api.DWORD()
        ok = api.GetOverlappedResult(self._port._port_handle, ctypes.byref(ov),
                                     ctypes.byref(count), False)
        error = api.GetLastError() if not ok else 0
        if not ok and error == 996:  # ERROR_IO_INCOMPLETE; buffer is still live
            # Wait for completion without imposing a polling delay on arriving
            # data. The short bound also lets reset/close take the read lock.
            if api.WaitForSingleObject(ov.hEvent, 5) == 0xFFFFFFFF:
                error = api.GetLastError()
                raise serial.SerialException(f'CDC receive event failed (WinError {error})')
            return b''
        slot[2] = False
        if not ok:
            if self._closed and error == api.ERROR_OPERATION_ABORTED:
                return b''
            raise serial.SerialException(f'CDC queued read failed (WinError {error}: {ctypes.FormatError(error).strip()})')
        data = buffer.raw[:count.value]
        with self._lock:
            if not self._closed:
                self._post(slot)
                self._slots.rotate(-1)
        return data

    def cancel(self):
        with self._lock:
            self._closed = True
            for ov, _, submitted in self._slots:
                if submitted:
                    self._api.CancelIoEx(self._port._port_handle, self._ctypes.byref(ov))

    def _reap(self):
        deadline = time.monotonic() + 1
        for slot in self._slots:
            while slot[2]:
                count = self._api.DWORD()
                ok = self._api.GetOverlappedResult(self._port._port_handle,
                    self._ctypes.byref(slot[0]), self._ctypes.byref(count), False)
                if not ok and self._api.GetLastError() == 996:
                    if time.monotonic() >= deadline:
                        _unreaped_readers.append(self)
                        raise _PendingReadTimeout('CDC cancellation did not complete within 1s; worker must exit')
                    time.sleep(.002)
                    continue
                slot[2] = False

    def reset(self):
        self.cancel()
        self._reap()
        self._port.reset_input_buffer()
        self._closed = False
        for slot in self._slots:
            self._post(slot)

    def close(self):
        self.cancel()
        self._reap()
        with self._lock:
            for ov, _, _ in self._slots:
                self._api.CloseHandle(ov.hEvent)
            self._slots.clear()


def main(arguments=None):
    def reply(value):
        sys.stderr.write(json.dumps(value) + '\n')
        sys.stderr.flush()

    try:
        arguments = sys.argv[1:] if arguments is None else arguments
        if len(arguments) != 2:
            raise ValueError('Serial worker requires port and baudrate')
        port = serial.serial_for_url(arguments[0], int(arguments[1]), timeout=.01, write_timeout=5)
    except Exception as exc:
        reply({'error': str(exc)})
        return 1
    stopped = threading.Event()
    read_enabled = threading.Event()
    read_enabled.set()
    read_lock = threading.Lock()
    pending = queue.Queue(maxsize=1024)  # at most 16 MiB, then explicit backpressure
    epoch = 0
    receive_error = []
    reader = None
    try:
        if sys.platform == 'win32' and hasattr(port, '_port_handle'):
            reader = _WindowsReadQueue(port)
    except _PendingReadTimeout as exc:
        reply({'error': str(exc)})
        os._exit(1)  # Never free buffers while the kernel can still write them.
    except Exception as exc:
        port.close()
        reply({'error': str(exc)})
        return 1

    def receive():
        try:
            while not stopped.is_set():
                if not read_enabled.wait(.05):
                    continue
                with read_lock:
                    if stopped.is_set() or not read_enabled.is_set():
                        continue
                    generation = epoch
                    try:
                        data = reader.read() if reader else port.read(min(4096, port.in_waiting) or 1)
                    except Exception as exc:
                        # The control thread must never reset or write to a port
                        # whose sole receiver has already failed.
                        receive_error.append(str(exc))
                        raise
                if data:
                    while not stopped.is_set():
                        try:
                            pending.put((b'D', generation, data), timeout=.05)
                            break
                        except queue.Full:
                            pass
        except Exception as exc:
            while not stopped.is_set():
                try:
                    pending.put((b'E', epoch, str(exc).encode('utf-8')), timeout=.05)
                    break
                except queue.Full:
                    # Keep the error ordered after queued data, but let close
                    # interrupt backpressure. Never silently drop the E frame.
                    pass

    def transmit():
        try:
            while not stopped.is_set():
                try:
                    kind, generation, data = pending.get(timeout=.05)
                except queue.Empty:
                    continue
                packet = struct.pack('<cII', kind, generation, len(data)) + data
                sys.stdout.buffer.write(packet)
                sys.stdout.buffer.flush()
        except (BrokenPipeError, OSError):
            stopped.set()

    rx = threading.Thread(target=receive, daemon=True)
    tx = threading.Thread(target=transmit, daemon=True)
    rx.start()
    tx.start()
    closed = False

    def close_port():
        nonlocal closed
        if closed:
            return
        stopped.set()
        read_enabled.set()
        reader.cancel() if reader else port.cancel_read()
        rx.join(timeout=1)
        if rx.is_alive():
            raise _PendingReadTimeout('Serial receiver did not stop within 1s; worker must exit')
        if reader:
            reader.close()
        port.close()
        closed = True

    reply({'ready': True})
    try:
        for line in sys.stdin:
            try:
                command = json.loads(line)
                op = command['op']
                if receive_error and op != 'close':
                    raise serial.SerialException(receive_error[0])
                if op == 'write':
                    reply({'result': port.write(base64.b64decode(command['data']))})
                elif op == 'flush':
                    port.flush()
                    reply({'result': None})
                elif op == 'reset_input_buffer':
                    # Stop new reads BEFORE competing for the lock. Otherwise
                    # a busy receiver can reacquire it indefinitely.
                    read_enabled.clear()
                    if reader:
                        reader.cancel()
                    if not read_lock.acquire(timeout=1):
                        raise _PendingReadTimeout('Serial receiver did not pause within 1s; worker must exit')
                    try:
                        if receive_error:
                            raise serial.SerialException(receive_error[0])
                        epoch += 1
                        if reader:
                            reader.reset()
                        else:
                            port.reset_input_buffer()
                    except Exception as exc:
                        receive_error.append(str(exc))
                        raise
                    finally:
                        read_lock.release()
                    read_enabled.set()
                    reply({'epoch': epoch})
                elif op == 'reset_output_buffer':
                    port.reset_output_buffer()
                    reply({'result': None})
                elif op == 'close':
                    close_port()
                    reply({'result': None})
                    break
                else:
                    raise ValueError('Unknown serial worker operation')
            except _PendingReadTimeout as exc:
                reply({'error': str(exc)})
                os._exit(1)
            except Exception as exc:
                reply({'error': str(exc)})
    finally:
        try:
            close_port()
        except _PendingReadTimeout:
            os._exit(1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
