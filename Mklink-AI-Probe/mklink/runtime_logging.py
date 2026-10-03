"""Bounded Python diagnostics for the sole owner of one shared runtime."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import traceback

MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3
CHUNK_CHARS = 1024


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

    Python print/logging/tracebacks share the standard rotating file handler.
    Native writes to inherited OS handles remain in the launcher's startup log.
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
        with redirect_stdout(stream), redirect_stderr(stream):
            try:
                yield
            except BaseException:
                traceback.print_exc()
                raise
    finally:
        logging.raiseExceptions = previous_errors
        handler.close()
