"""Bounded diagnostics for the sole owner of one shared runtime."""
import codecs
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os
import threading
import time
import traceback

MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3
CHUNK_CHARS = 1024


@contextmanager
def _native_diagnostics(stream):
    """Drain process stdout/stderr into the same sink; no disk spool or queue.

    Windows has both CRT descriptors and Win32 standard handles. Redirect both,
    including the handles inherited by children, and restore them on exit.
    """
    saved = {}
    inheritable = {}
    read_fd = write_fd = None
    reader = None
    stop = threading.Event()
    native = None
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel.GetStdHandle.restype = wintypes.HANDLE
        kernel.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
        kernel.SetStdHandle.restype = wintypes.BOOL
        kernel.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                        wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        kernel.PeekNamedPipe.restype = wintypes.BOOL
        native = {}
        for fd in (1, 2):
            handle = kernel.GetStdHandle(-10 - fd)
            try:
                follows_fd = handle == msvcrt.get_osfhandle(fd)
            except OSError:
                follows_fd = False
            native[fd] = (handle, follows_fd)

    def available():
        if native is not None:
            count = wintypes.DWORD()
            if not kernel.PeekNamedPipe(msvcrt.get_osfhandle(read_fd), None, 0, None,
                                        ctypes.byref(count), None):
                if ctypes.get_last_error() == 109:  # ERROR_BROKEN_PIPE
                    return -1
                raise ctypes.WinError(ctypes.get_last_error())
            return min(count.value, 8192)
        import select
        return 8192 if select.select([read_fd], [], [], .025)[0] else 0

    def drain():
        decoder = io.IncrementalNewlineDecoder(
            codecs.getincrementaldecoder('utf-8')(errors='replace'), translate=True)
        deadline = None
        try:
            while True:
                if stop.is_set():
                    deadline = deadline or time.monotonic() + 1
                    if time.monotonic() >= deadline:
                        break
                count = available()
                if count < 0 or (not count and stop.is_set()):
                    break
                if not count:
                    stop.wait(.025)
                    continue
                data = os.read(read_fd, count)
                if not data:
                    break
                stream.write(decoder.decode(data))
            stream.write(decoder.decode(b'', final=True))
        finally:
            os.close(read_fd)

    try:
        # Reserve missing CRT slots first (windowless/frozen entry points), so
        # os.pipe cannot allocate a read end that dup2 would then overwrite.
        missing = set()
        for fd in (1, 2):
            try:
                os.fstat(fd)
            except OSError:
                missing.add(fd)
        for fd in sorted(missing):
            temporary = os.open(os.devnull, os.O_WRONLY)
            if temporary != fd:
                os.dup2(temporary, fd)
                os.close(temporary)
        for fd in (1, 2):
            inheritable[fd] = os.get_inheritable(fd)
            saved[fd] = None if fd in missing else os.dup(fd)
        read_fd, write_fd = os.pipe()
        reader = threading.Thread(target=drain, name='runtime-diagnostics', daemon=True)
        reader.start()
        for fd in (1, 2):
            os.dup2(write_fd, fd)
            if native is not None and not kernel.SetStdHandle(-10 - fd, msvcrt.get_osfhandle(fd)):
                raise ctypes.WinError(ctypes.get_last_error())
        os.close(write_fd)
        write_fd = None
        yield
    finally:
        for fd, previous in saved.items():
            if previous is None:
                os.close(fd)
            else:
                os.dup2(previous, fd, inheritable=inheritable[fd])
                os.close(previous)
            if native is not None:
                handle, follows_fd = native[fd]
                restored = msvcrt.get_osfhandle(fd) if follows_fd else handle
                kernel.SetStdHandle(-10 - fd, restored)
        if write_fd is not None:
            os.close(write_fd)
        stop.set()
        if reader is not None and reader.ident is not None:
            reader.join()
        elif read_fd is not None:
            os.close(read_fd)


class _DiagnosticStream(io.TextIOBase):
    encoding = 'utf-8'

    def __init__(self, handler):
        self.handler = handler

    def writable(self):
        return True

    def write(self, text):
        if not isinstance(text, str):
            raise TypeError('diagnostic output must be text')
        # Bound a single record too; a large print must not defeat rotation.
        for offset in range(0, len(text), CHUNK_CHARS):
            record = logging.LogRecord('mklink.runtime', logging.INFO, '', 0,
                                       text[offset:offset + CHUNK_CHARS], (), None)
            self.handler.handle(record)
        return len(text)

    def flush(self):
        self.handler.flush()


@contextmanager
def runtime_diagnostics(directory, *, max_bytes=MAX_BYTES, backup_count=BACKUP_COUNT):
    """Call only while holding this runtime's owner lock, before server imports.

    Python and native output share the standard rotating file handler. The
    launcher's startup log only covers diagnostics before this context opens.
    """
    path = Path(directory) / 'runtime.log'
    # Existing pre-rotation logs may be huge. Preserve their tail without ever
    # reading the whole file or keeping an unbounded legacy backup.
    for candidate in [path, *(path.with_name(f'{path.name}.{n}') for n in range(1, backup_count + 1))]:
        if candidate.exists() and candidate.stat().st_size > max_bytes:
            with candidate.open('r+b') as output:
                output.seek(-max_bytes, 2)
                tail = output.read(max_bytes).decode('utf-8', 'ignore').encode('utf-8')
                output.seek(0)
                output.write(tail)
                output.truncate()
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count,
                                  encoding='utf-8', errors='backslashreplace')
    handler.terminator = ''
    stream = _DiagnosticStream(handler)
    previous_errors = logging.raiseExceptions
    # Disk/rotation failure must not recurse through stderr or break hardware I/O.
    logging.raiseExceptions = False
    try:
        with redirect_stdout(stream), redirect_stderr(stream), _native_diagnostics(stream):
            try:
                yield
            except BaseException:
                traceback.print_exc()
                raise
    finally:
        logging.raiseExceptions = previous_errors
        handler.close()
