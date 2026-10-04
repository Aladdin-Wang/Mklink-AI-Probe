"""Bound producer ingress before waking the owning asyncio loop."""
from collections import deque
import asyncio
import threading


class LoopDelivery:
    """Coalesce wakeups while retaining at most capacity pending records.

    Delivery runs on the owner loop; discard runs on the submitting thread.
    The caller serializes submissions when their ordering is significant.
    A draining batch and the next pending batch can coexist, each bounded by
    capacity. The owner may flush pending records before an initial snapshot.
    """

    def __init__(self, loop, capacity, deliver, discard):
        if type(capacity) is not int or capacity <= 0:
            raise ValueError('Delivery capacity must be a positive integer')
        self.loop = loop
        self._capacity = capacity
        self._deliver, self._discard = deliver, discard
        self._pending = deque()
        self._scheduled = False
        self._lock = threading.Lock()

    def submit(self, item):
        discarded = []
        error = None
        with self._lock:
            if self.loop.is_closed():
                discarded = [*self._pending, item]
                self._pending.clear()
                self._scheduled = False
                error = RuntimeError('owner event loop is closed')
            else:
                if len(self._pending) == self._capacity:
                    discarded.append(self._pending.popleft())
                self._pending.append(item)
                if not self._scheduled:
                    self._scheduled = True
                    try:
                        self.loop.call_soon_threadsafe(self._drain)
                    except RuntimeError as exc:
                        discarded.extend(self._pending)
                        self._pending.clear()
                        self._scheduled = False
                        error = exc
        for dropped in discarded:
            self._discard(dropped)
        if error is not None:
            raise error

    def flush(self):
        if asyncio.get_running_loop() is not self.loop:
            raise RuntimeError('Delivery flush requires the owner event loop')
        # The already-scheduled wakeup will drain any subsequent records;
        # flushing must not schedule another callback for every subscriber.
        self._drain(keep_scheduled=True)

    def _drain(self, *, keep_scheduled=False):
        with self._lock:
            pending, self._pending = self._pending, deque()
            if not keep_scheduled:
                self._scheduled = False
        for item in pending:
            try:
                self._deliver(item)
            except Exception as exc:
                self.loop.call_exception_handler({
                    'message': 'Stream delivery callback failed', 'exception': exc,
                })
