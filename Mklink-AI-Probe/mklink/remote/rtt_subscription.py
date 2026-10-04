"""Bounded consumer of the existing local RTT terminal binary WebSocket."""
from collections import deque
import json
import socket
import threading
import time

from mklink.remote.protocol import AgentOperationError
from mklink.remote.stream_protocol import decode_frame, StreamType, RTT_TERMINAL_UTF8, MAX_PAYLOAD_SIZE, HEADER_SIZE

BUFFER_BYTES = 64 * 1024
BUFFER_BATCHES = 128


def _status(payload):
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError('Invalid stream status')
    result = {key: value.get(key, 0) for key in (
        'dropped_batches', 'dropped_items', 'dropped_bytes', 'active_clients', 'last_sequence')}
    if any(type(count) is not int or not 0 <= count <= 0xffffffffffffffff for count in result.values()):
        raise ValueError('Invalid stream counters')
    return result


class RttSubscription:
    def __init__(self, info):
        from websockets.sync.client import connect
        self._condition = threading.Condition()
        self._chunks = deque()
        self._bytes = self.dropped_bytes = self.missing_batches = 0
        self.error = None
        self._stopping = False
        self._upstream = {}
        # Explicit loopback socket bypasses environment HTTP proxy settings,
        # including on the supported websockets 11 API.
        raw = None
        try:
            raw = socket.create_connection(('127.0.0.1', info['port']), timeout=3)
            self._socket = connect(f"ws://127.0.0.1:{info['port']}/ws/streams/rtt-terminal",
                sock=raw, additional_headers={'Authorization': 'Bearer '+info['token']},
                compression=None, open_timeout=3, close_timeout=1,
                max_size=MAX_PAYLOAD_SIZE+HEADER_SIZE)
            ready = decode_frame(self._socket.recv(timeout=3))
            if ready.stream_type != StreamType.CONTROL or ready.stream_id != int(StreamType.RTT_RAW):
                raise ValueError('Missing RTT subscription-ready frame')
            self._sequence = ready.sequence
            self._upstream = _status(ready.payload)
        except Exception:
            if hasattr(self, '_socket'):
                self._socket.close()
            if raw is not None:
                raw.close()
            raise AgentOperationError('Cannot subscribe to shared RTT; no direct fallback') from None
        self._thread = threading.Thread(target=self._receive, daemon=True, name='remote-rtt-subscriber')
        self._thread.start()

    def _receive(self):
        try:
            while not self._stopping:
                try:
                    frame = decode_frame(self._socket.recv(timeout=.25))
                except TimeoutError:
                    continue
                if frame.stream_id != int(StreamType.RTT_RAW):
                    raise ValueError('Wrong stream identity')
                with self._condition:
                    if frame.stream_type == StreamType.CONTROL:
                        self._upstream = _status(frame.payload)
                        continue
                    if frame.stream_type != StreamType.RTT_RAW or frame.flags != RTT_TERMINAL_UTF8:
                        raise ValueError('Wrong RTT terminal encoding')
                    frame.payload.decode('utf-8')  # Terminal batches contain complete UTF-8 text.
                    if frame.sequence <= self._sequence:
                        raise ValueError('RTT sequence moved backwards')
                    self.missing_batches += frame.sequence-self._sequence-1
                    self._sequence = frame.sequence
                    if len(frame.payload) > BUFFER_BYTES:
                        self.dropped_bytes += len(frame.payload)
                    elif frame.payload:
                        while self._chunks and (self._bytes+len(frame.payload) > BUFFER_BYTES or len(self._chunks) >= BUFFER_BATCHES):
                            dropped = self._chunks.popleft()
                            self._bytes -= len(dropped)
                            self.dropped_bytes += len(dropped)
                        self._chunks.append(frame.payload)
                        self._bytes += len(frame.payload)
                    self._condition.notify_all()
        except Exception:
            with self._condition:
                if not self._stopping:
                    self.error = 'Shared RTT subscription disconnected or received an invalid frame; restart explicitly'
                self._condition.notify_all()
        finally:
            self._socket.close()

    def read(self, timeout):
        deadline = time.monotonic()+timeout
        with self._condition:
            while not self._chunks and not self.error and not self._stopping:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            text = b''.join(self._chunks).decode('utf-8')
            self._chunks.clear()
            self._bytes = 0
            return {'text': text, 'dropped_bytes': self.dropped_bytes,
                    'missing_batches': self.missing_batches, 'sequence': self._sequence,
                    'error': self.error, 'upstream': dict(self._upstream)}

    def close(self):
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        self._socket.close()
        self._thread.join(timeout=2)
        if self._thread.is_alive():
            raise AgentOperationError('RTT subscriber did not exit after its socket closed')
