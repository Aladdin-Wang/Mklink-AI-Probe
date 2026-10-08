"""Bounded serial byte batching independent of the WebSocket event loop."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from collections.abc import Callable

SERIAL_BATCH_BYTES = 4096
SERIAL_BATCH_INTERVAL = 0.02


class SerialByteBatcher:
    """Preserve byte/direction order while avoiding one WS frame per USB read."""

    def __init__(self, publish: Callable[[bytes, str, str, float, float], None]):
        self._publish = publish
        self._lock = threading.Lock()
        self._pending = bytearray()
        self._direction = "RX"
        self._port = ""
        self._first_time = self._last_time = 0.0
        self._stop = threading.Event()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run, name="serial-byte-batches", daemon=True,
        )

    @property
    def worker_alive(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._thread.start()

    def feed(self, data: bytes, direction: str, port: str, *, monotonic_time: float | None = None) -> None:
        now = time.monotonic() if monotonic_time is None else monotonic_time
        with self._lock:
            if self._closed:
                return
            if direction != self._direction or port != self._port or (
                self._pending and now - self._last_time >= SERIAL_BATCH_INTERVAL
            ):
                self._flush_locked()
                self._direction, self._port = direction, port
            offset = 0
            while offset < len(data):
                if not self._pending:
                    self._first_time = now
                self._last_time = now
                count = min(SERIAL_BATCH_BYTES - len(self._pending), len(data) - offset)
                self._pending.extend(data[offset:offset + count])
                offset += count
                if len(self._pending) == SERIAL_BATCH_BYTES:
                    self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        if self._pending:
            payload = bytes(self._pending)
            self._pending.clear()
            self._publish(payload, self._direction, self._port, self._first_time, self._last_time)

    def _run(self) -> None:
        while not self._stop.wait(SERIAL_BATCH_INTERVAL):
            self.flush()

    def close(self) -> None:
        # Call after the serial reader stops so its last chunk is included.
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise TimeoutError("serial byte batch worker did not stop")
        with self._lock:
            self._closed = True
            self._flush_locked()


class SerialHistory:
    """One bounded raw-batch history; readers own cursors, never consume entries.

    The existing batcher bounds each payload to 4096 bytes, so 512 retained
    batches use at most 2 MiB of raw data. Protocol-transfer bytes stay separate.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._entries = deque(maxlen=512)
        self._session = uuid.uuid4().hex
        self._sequence = 0

    def reset(self, session: str) -> None:
        with self._lock:
            self._session = session
            self._sequence = 0
            self._entries.clear()

    def append(self, data: bytes, direction: str, port: str, *,
               first_time: float | None = None, last_time: float | None = None) -> None:
        if not 1 <= len(data) <= SERIAL_BATCH_BYTES:
            raise ValueError('Serial history requires 1..4096 bytes per batch')
        with self._lock:
            first_time = time.monotonic() if first_time is None else first_time
            last_time = first_time if last_time is None else last_time
            self._sequence += 1
            self._entries.append((self._sequence, time.time_ns(), port, direction, bytes(data), first_time, last_time))

    def read(self, session: str | None = None, after: int | None = None,
             limit: int = 256) -> dict:
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError('History limit must be an integer in 1..256')
        if (after is None) != (session is None):
            raise ValueError('History continuation requires both session and after')
        if after is not None and (type(after) is not int or after < 0):
            raise ValueError('History after must be a nonnegative integer')
        with self._lock:
            if session is not None and session != self._session:
                raise RuntimeError('Serial history session changed; reopen explicitly')
            if after is not None and after > self._sequence:
                raise ValueError('History cursor is ahead of this session')
            cursor = self._sequence if after is None else after
            oldest = self._entries[0][0] if self._entries else self._sequence + 1
            entries = [entry for entry in self._entries if entry[0] > cursor][:limit]
            return {'session': self._session, 'latest_seq': self._sequence,
                    'next_seq': entries[-1][0] if entries else cursor,
                    'dropped_batches': max(0, oldest - cursor - 1),
                    'entries': [{'seq': seq, 'timestamp_ns': timestamp, 'port': port,
                                 'direction': direction, 'size': len(data), 'hex': data.hex(),
                                 'first_monotonic': first, 'last_monotonic': last}
                                for seq, timestamp, port, direction, data, first, last in entries]}
