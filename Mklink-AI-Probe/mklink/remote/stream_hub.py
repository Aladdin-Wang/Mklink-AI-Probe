"""Bounded fan-out queues for high-throughput stream batches."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Optional, Set, Union


BytesLike = Union[bytes, bytearray, memoryview]


@dataclass(frozen=True, eq=False)
class StreamBatch:
    """An immutable payload carrying the hub-assigned batch metadata."""

    payload: bytes
    sequence: int
    item_count: int

    def __bytes__(self) -> bytes:
        return self.payload

    def __len__(self) -> int:
        return len(self.payload)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, StreamBatch):
            return self.payload == other.payload
        if isinstance(other, (bytes, bytearray, memoryview)):
            return self.payload == bytes(other)
        return NotImplemented


@dataclass(frozen=True)
class StreamHubStats:
    produced_batches: int
    produced_items: int
    produced_bytes: int
    delivered_batches: int
    delivered_items: int
    delivered_bytes: int
    dropped_batches: int
    dropped_items: int
    dropped_bytes: int
    active_clients: int
    queue_high_water_mark: int
    last_sequence: int


class StreamHub:
    """Broadcast batches without allowing subscribers to block producers."""

    def __init__(self, max_batches_per_client: int):
        if isinstance(max_batches_per_client, bool) or not isinstance(
            max_batches_per_client, int
        ):
            raise TypeError("max_batches_per_client must be an integer")
        if max_batches_per_client <= 0:
            raise ValueError("max_batches_per_client must be greater than zero")
        self._max_batches_per_client = max_batches_per_client
        self._subscribers: Set[asyncio.Queue] = set()
        self._owner_loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()
        self._publish_lock = threading.Lock()
        self._last_sequence = 0
        self._produced_batches = 0
        self._produced_items = 0
        self._produced_bytes = 0
        self._delivered_batches = 0
        self._delivered_items = 0
        self._delivered_bytes = 0
        self._dropped_batches = 0
        self._dropped_items = 0
        self._dropped_bytes = 0
        self._queue_high_water_mark = 0

    def subscribe(self) -> asyncio.Queue:
        loop = self._running_loop()
        queue: asyncio.Queue = asyncio.Queue(
            maxsize=self._max_batches_per_client
        )
        with self._lock:
            self._bind_or_require_owner_loop(loop)
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> bool:
        loop = self._running_loop()
        with self._lock:
            self._require_owner_loop(loop)
            if queue not in self._subscribers:
                return False
            self._subscribers.remove(queue)
        while not queue.empty():
            queue.get_nowait()
            queue.task_done()
        return True

    def publish(self, batch: BytesLike, item_count: int) -> int:
        with self._publish_lock:
            published = self._prepare_batch(batch, item_count)
            self._schedule_delivery(published)
        return published.sequence

    def publish_threadsafe(
        self,
        loop: asyncio.AbstractEventLoop,
        batch: BytesLike,
        item_count: int = 0,
    ) -> int:
        with self._publish_lock:
            if loop.is_closed():
                raise RuntimeError("event loop is closed")
            with self._lock:
                self._bind_or_require_owner_loop(loop)
            published = self._prepare_batch(batch, item_count)
            self._schedule_delivery(published)
        return published.sequence

    def stats(self) -> StreamHubStats:
        with self._lock:
            return StreamHubStats(
                produced_batches=self._produced_batches,
                produced_items=self._produced_items,
                produced_bytes=self._produced_bytes,
                delivered_batches=self._delivered_batches,
                delivered_items=self._delivered_items,
                delivered_bytes=self._delivered_bytes,
                dropped_batches=self._dropped_batches,
                dropped_items=self._dropped_items,
                dropped_bytes=self._dropped_bytes,
                active_clients=len(self._subscribers),
                queue_high_water_mark=self._queue_high_water_mark,
                last_sequence=self._last_sequence,
            )

    def status_frame(self) -> StreamHubStats:
        return self.stats()

    def _prepare_batch(self, batch: BytesLike, item_count: int) -> StreamBatch:
        if not isinstance(batch, (bytes, bytearray, memoryview)):
            raise TypeError("batch must be bytes-like")
        if isinstance(item_count, bool) or not isinstance(item_count, int):
            raise TypeError("item_count must be an integer")
        if item_count < 0:
            raise ValueError("item_count must not be negative")
        payload = bytes(batch)
        with self._lock:
            self._last_sequence += 1
            self._produced_batches += 1
            self._produced_items += item_count
            self._produced_bytes += len(payload)
            sequence = self._last_sequence
        return StreamBatch(payload, sequence, item_count)

    def _schedule_delivery(self, batch: StreamBatch) -> None:
        with self._lock:
            loop = self._owner_loop
            has_subscribers = bool(self._subscribers)
        if loop is None or not has_subscribers:
            return
        if loop.is_closed():
            raise RuntimeError("owner event loop is closed")
        loop.call_soon_threadsafe(self._deliver, batch)

    def _deliver(self, batch: StreamBatch) -> None:
        loop = self._running_loop()
        with self._lock:
            self._require_owner_loop(loop)
            subscribers = tuple(self._subscribers)
        for queue in subscribers:
            dropped = None
            if queue.full():
                dropped = queue.get_nowait()
                queue.task_done()
            queue.put_nowait(batch)
            with self._lock:
                self._delivered_batches += 1
                self._delivered_items += batch.item_count
                self._delivered_bytes += len(batch)
                self._queue_high_water_mark = max(
                    self._queue_high_water_mark, queue.qsize()
                )
                if dropped is not None:
                    self._dropped_batches += 1
                    self._dropped_items += dropped.item_count
                    self._dropped_bytes += len(dropped)

    @staticmethod
    def _running_loop() -> asyncio.AbstractEventLoop:
        try:
            return asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError("operation requires the owner event loop") from exc

    def _bind_or_require_owner_loop(
        self, loop: asyncio.AbstractEventLoop
    ) -> None:
        if self._owner_loop is None:
            self._owner_loop = loop
        else:
            self._require_owner_loop(loop)

    def _require_owner_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if loop is not self._owner_loop:
            raise RuntimeError("operation requires the owner event loop")
