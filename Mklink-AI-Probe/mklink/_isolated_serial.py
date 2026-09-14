"""Keep Windows USB CDC reception independent of application Python pauses.

The worker drains USB while the application collects garbage or parses ELF.
Transport buffers are finite; this is pause tolerance, not unlimited recording.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import threading
import time

import serial


def _available(pipe) -> int:
    if os.name == 'nt':
        import ctypes
        import msvcrt
        available = ctypes.c_ulong()
        peek = ctypes.windll.kernel32.PeekNamedPipe
        if not peek(ctypes.c_void_p(msvcrt.get_osfhandle(pipe.fileno())), None, 0,
                    None, ctypes.byref(available), None):
            raise serial.SerialException('Serial worker pipe closed')
        return available.value
    return 65536 if select.select([pipe], [], [], 0)[0] else 0


class IsolatedSerial:
    def __init__(self, port: str, baudrate: int, timeout: float = .01):
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self.is_open = False
        self._wire = bytearray()
        self._rx = bytearray()
        self._control = bytearray()
        self._epoch = 0
        self._rx_lock = threading.Lock()
        self._command_lock = threading.Lock()
        try:
            self._process = subprocess.Popen(
                [sys.executable, str(Path(__file__).with_name('_serial_worker.py')), port, str(baudrate)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except OSError as exc:
            raise serial.SerialException('Cannot start serial receive worker') from exc
        try:
            if not self._reply().get('ready'):
                raise serial.SerialException('Serial worker did not open the port')
            self.is_open = True
        except BaseException:
            self._dispose()
            raise

    def _reply(self):
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            if b'\n' in self._control:
                line, _, rest = self._control.partition(b'\n')
                self._control = bytearray(rest)
                try:
                    response = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    raise serial.SerialException('Invalid serial worker response') from exc
                if 'error' in response:
                    raise serial.SerialException(response['error'])
                return response
            n = _available(self._process.stderr)
            if n:
                data = self._process.stderr.read(min(n,65536))
                if not data: break
                self._control.extend(data)
            elif self._process.poll() is not None:
                break
            else:
                time.sleep(.001)
        raise serial.SerialException('Serial worker control connection failed')

    def _command(self, op, **kwargs):
        with self._command_lock:
            if not self.is_open:
                raise serial.SerialException('Serial port is closed')
            try:
                data = memoryview((json.dumps({'op': op, **kwargs})+'\n').encode())
                while data:
                    count = self._process.stdin.write(data)
                    if not count:
                        raise serial.SerialException('Serial worker input closed')
                    data = data[count:]
                return self._reply()
            except (OSError, ValueError) as exc:
                raise serial.SerialException('Serial worker write failed') from exc

    def _drain(self):
        if not self.is_open:
            raise serial.SerialException('Serial port is closed')
        # Leave excess bytes in the bounded worker/pipe instead of growing
        # memory when a caller repeatedly checks in_waiting without reading.
        n = _available(self._process.stdout) if len(self._rx) < 1048576 else 0
        if n:
            data = self._process.stdout.read(min(n,65536))
            if not data:
                raise serial.SerialException('Serial worker disconnected')
            self._wire.extend(data)
        elif self._process.poll() is not None:
            raise serial.SerialException('Serial worker exited')
        offset = 0
        while len(self._wire)-offset >= 9:
            kind, epoch, size = struct.unpack_from('<cII', self._wire, offset)
            if size > 65536 or kind not in (b'D', b'E'):
                raise serial.SerialException('Invalid serial worker packet')
            if len(self._wire)-offset < size+9: break
            data = self._wire[offset+9:offset+9+size]
            offset += size+9
            if kind == b'E':
                raise serial.SerialException(data.decode('utf-8', errors='replace'))
            if epoch >= self._epoch:
                self._rx.extend(data)
        if offset: del self._wire[:offset]

    @property
    def in_waiting(self):
        with self._rx_lock:
            self._drain()
            return len(self._rx)

    def read(self, size=1):
        if size <= 0: return b''
        deadline = time.monotonic()+self.timeout
        while True:
            with self._rx_lock:
                self._drain()
                if self._rx:
                    data = bytes(self._rx[:size])
                    del self._rx[:size]
                    return data
            if time.monotonic() >= deadline: return b''
            time.sleep(.0005)

    def write(self, data):
        return self._command('write', data=base64.b64encode(data).decode('ascii'))['result']

    def flush(self):
        self._command('flush')

    def reset_input_buffer(self):
        with self._rx_lock:
            self._epoch = self._command('reset_input_buffer')['epoch']
            self._rx.clear()
            # Retain partial framing; old generations are discarded by _drain.

    def reset_output_buffer(self):
        self._command('reset_output_buffer')

    def _dispose(self):
        if self._process.poll() is None:
            self._process.terminate()
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2)
        for pipe in (self._process.stdin, self._process.stdout, self._process.stderr):
            pipe.close()

    def close(self):
        try:
            if self.is_open and self._process.poll() is None:
                self._command('close')
        except serial.SerialException:
            # The read/write that discovered the failure reports it. Cleanup
            # must still release the port lock and reap an already-dead worker.
            pass
        finally:
            self.is_open = False
            self._dispose()
