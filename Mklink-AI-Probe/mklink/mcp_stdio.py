"""Keep MCP JSON-RPC separate from diagnostic prints, without device imports."""
from contextlib import contextmanager
import sys


class _ProtocolStdout:
    def __init__(self, protocol_stream, diagnostic_stream):
        self._protocol_stream = protocol_stream
        self._diagnostic_stream = diagnostic_stream

    @property
    def buffer(self):
        return self._protocol_stream.buffer

    def write(self, text):
        return self._diagnostic_stream.write(text)

    def flush(self):
        self._diagnostic_stream.flush()

    def __getattr__(self, name):
        return getattr(self._diagnostic_stream, name)


@contextmanager
def isolate_stdio_protocol():
    protocol_stdout = sys.stdout
    sys.stdout = _ProtocolStdout(protocol_stdout, sys.stderr)
    try:
        yield
    finally:
        sys.stdout = protocol_stdout
