"""Shared terminal input polled by SerialCapture; owns no worker or UART."""
import codecs
import os
import sys
from pathlib import Path


class SerialTerminal:
    def __init__(self, send, console, stdin=None):
        self.send, self.console = send, console
        self.stdin = sys.stdin if stdin is None else stdin
        self.fd = self.stdin.fileno()
        self.tty = self.stdin.isatty()
        self.buffer = ''
        self._decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self._saved = None
        self._skip_lf = False
        self._extended_key = False
        self._filter_input = False
        self._ready = ''

    def __enter__(self):
        if self.tty and os.name != 'nt':
            import termios
            import tty
            self._saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        return self

    def __exit__(self, *_):
        if self._saved is not None:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)

    def _read(self):
        """Return ready text, or None at EOF. Never block on an open pipe."""
        if os.name == 'nt' and self.tty:
            import msvcrt
            chars = []
            while len(chars) < 256 and msvcrt.kbhit():
                ch = msvcrt.getwch()
                if self._extended_key:
                    self._extended_key = False
                elif ch in ('\x00', '\xe0'):
                    self._extended_key = True
                else:
                    chars.append(ch)
            return ''.join(chars)
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            import msvcrt
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            handle = wintypes.HANDLE(msvcrt.get_osfhandle(self.fd))
            kernel.GetFileType.argtypes = [wintypes.HANDLE]
            if kernel.GetFileType(handle) == 3:  # FILE_TYPE_PIPE
                available = wintypes.DWORD()
                kernel.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                    wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
                if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                    error = ctypes.get_last_error()
                    if error in (109, 232):  # broken/closing pipe = EOF
                        return self._decoder.decode(b'', final=True) or None
                    raise OSError(error, 'Cannot inspect terminal input pipe')
                if not available.value:
                    return ''
                count = min(4096, available.value)
            else:
                count = 4096  # regular file or NUL
        else:
            import select
            if not select.select([self.fd], [], [], 0)[0]:
                return ''
            count = 4096
        data = os.read(self.fd, count)
        return self._decoder.decode(data, final=not data) if data else self._decoder.decode(b'', final=True) or None

    def command(self, line):
        if self._filter_input:
            self._filter_input = False
            self.console.set_filter(line)
            return True
        if line == '>quit':
            return False
        if line.startswith('>mode '):
            self.console.set_mode(line[6:])
            return True
        if line == '>filter' or line.startswith('>filter '):
            self.console.set_filter(line[8:] if len(line) > 7 else '')
            return True
        if line.startswith('>hex '):
            data = bytes.fromhex(line[5:])
        elif line.startswith('>file '):
            with Path(line[6:]).expanduser().open('rb') as file:
                data = file.read(4097)
        else:
            data = (line + '\r\n').encode('utf-8')
        if not 1 <= len(data) <= 4096:
            raise ValueError('Terminal sends require 1..4096 bytes; file data is not split or retried')
        self.send(data)
        return True

    def poll(self):
        self.console.tick()
        text = self._ready or self._read()
        self._ready = ''
        if text is None:
            if self.buffer:
                self.command(self.buffer)
                self.buffer = ''
            return False
        for index, ch in enumerate(text):
            if ch == '\n' and self._skip_lf:
                self._skip_lf = False
                continue
            self._skip_lf = ch == '\r'
            if ch in ('\x03', '\x11'):
                return False
            if ch in ('\r', '\n'):
                line, self.buffer = self.buffer, ''
                if self.tty:
                    print(flush=True)
                if not self.command(line):
                    return False
                # Let capture inspect reader errors, duration and RX between
                # commands even when a pipe supplies thousands of short lines.
                self._ready = text[index + 1:]
                return True
            elif self.tty and ch in ('\x08', '\x7f'):
                self.buffer = self.buffer[:-1]
                print('\b \b', end='', flush=True)
            elif self.tty and ch == '\x06':
                self.buffer, self._filter_input = '', True
                print('\nFilter regex: ', end='', flush=True)
            elif self.tty and ch == '\x0c':
                print('\033[2J\033[H', end='', flush=True)
            else:
                self.buffer += ch
                if len(self.buffer) > 8192:
                    raise ValueError('Terminal input line exceeds 8192 characters')
                if self.tty and ch.isprintable():
                    print(ch, end='', flush=True)
        return True
