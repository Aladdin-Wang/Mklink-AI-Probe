"""Deterministic, local acquisition-to-codec throughput benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import struct
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from mklink.remote.stream_hub import (  # noqa: E402
    StreamBatch,
    StreamHub,
    StreamHubStats,
)
from mklink.remote.stream_protocol import (  # noqa: E402
    Frame,
    StreamType,
    decode_frame,
    encode_frame,
)


STREAM_TYPES = {
    "systemview": StreamType.SYSTEMVIEW,
    "vofa": StreamType.WAVEFORM,
    "rtt": StreamType.RTT_RAW,
    "superwatch": StreamType.SUPERWATCH,
}
TARGET_BATCHES_PER_SECOND = 100
QUEUE_BATCH_CAPACITY = 64
FrameRoundTrip = Callable[[bytes], Frame]
StatsTransform = Callable[[StreamHubStats], StreamHubStats]


@dataclass(frozen=True)
class BenchmarkResult:
    produced_items: int
    consumed_items: int
    reported_drops: int
    sequence_errors: int
    unreported_drops: int
    bytes_per_sec: float
    peak_queue_depth: int
    elapsed: float

    @property
    def exit_code(self) -> int:
        return 1 if self.sequence_errors or self.unreported_drops else 0


def _loss_mismatch(
    *,
    produced_batches: int,
    consumed_batches: int,
    produced_items: int,
    consumed_items: int,
    reported_batches: int,
    reported_items: int,
) -> int:
    """Return nonzero when either loss counter disagrees with observation."""
    batch_difference = (produced_batches - consumed_batches) - reported_batches
    item_difference = (produced_items - consumed_items) - reported_items
    return abs(batch_difference) + abs(item_difference)


def _payload(first_sequence: int, item_count: int, channels: int) -> bytes:
    record = struct.Struct(f"<Q{channels}f")
    payload = bytearray(record.size * item_count)
    offset = 0
    for item in range(item_count):
        sequence = first_sequence + item
        values = tuple(
            float((sequence * (channel + 1)) % 10_000)
            for channel in range(channels)
        )
        record.pack_into(payload, offset, sequence, *values)
        offset += record.size
    return bytes(payload)


async def _next_delivery(
    queue: asyncio.Queue,
    deliveries_complete: asyncio.Event,
) -> StreamBatch | None:
    """Wait for a batch or the FIFO completion callback without polling."""
    if deliveries_complete.is_set():
        if queue.empty():
            return None
        return queue.get_nowait()

    delivery = asyncio.create_task(queue.get())
    completion = asyncio.create_task(deliveries_complete.wait())
    try:
        done, _ = await asyncio.wait(
            (delivery, completion),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if delivery in done:
            return delivery.result()
        if queue.empty():
            return None
        return await delivery
    finally:
        for task in (delivery, completion):
            if not task.done():
                task.cancel()
        await asyncio.gather(delivery, completion, return_exceptions=True)


async def _run_async(
    stream: str,
    rate: int,
    duration: float,
    channels: int,
    frame_round_trip: FrameRoundTrip,
    stats_transform: StatsTransform,
) -> BenchmarkResult:
    hub = StreamHub(max_batches_per_client=QUEUE_BATCH_CAPACITY)
    queue = hub.subscribe()
    loop = asyncio.get_running_loop()
    target_items = max(1, math.ceil(rate * duration))
    batch_items = max(1, math.ceil(rate / TARGET_BATCHES_PER_SECOND))
    producer_errors: list[BaseException] = []
    start_gate = threading.Event()
    stop_event = threading.Event()
    deliveries_complete = asyncio.Event()

    def produce() -> None:
        try:
            start_gate.wait()
            start = time.perf_counter()
            produced = 0
            while produced < target_items and not stop_event.is_set():
                count = min(batch_items, target_items - produced)
                hub.publish_threadsafe(
                    loop,
                    _payload(produced, count, channels),
                    item_count=count,
                )
                produced += count
                if produced >= target_items:
                    break
                deadline = start + produced / rate
                remaining = deadline - time.perf_counter()
                if remaining > 0 and stop_event.wait(remaining):
                    return
            remaining = start + duration - time.perf_counter()
            if remaining > 0:
                stop_event.wait(remaining)
        except BaseException as exc:  # propagate acquisition-thread failures
            producer_errors.append(exc)
        finally:
            loop.call_soon_threadsafe(deliveries_complete.set)

    producer = threading.Thread(
        target=produce,
        name="stream-benchmark-acquisition",
        daemon=False,
    )
    producer.start()
    started = time.perf_counter()
    start_gate.set()

    consumed_items = 0
    consumed_batches = 0
    encoded_bytes = 0
    sequence_errors = 0
    first_batch_sequence: int | None = None
    previous_batch_sequence: int | None = None
    observed_batch_gaps = 0
    first_item_sequence: int | None = None
    previous_item_sequence: int | None = None
    observed_item_gaps = 0
    record = struct.Struct(f"<Q{channels}f")

    try:
        while True:
            batch = await _next_delivery(queue, deliveries_complete)
            if batch is None:
                break
            try:
                if not isinstance(batch, StreamBatch):
                    sequence_errors += 1
                    continue
                consumed_batches += 1
                frame = Frame(
                    stream_type=STREAM_TYPES[stream],
                    flags=0,
                    stream_id=1,
                    sequence=batch.sequence,
                    timestamp_ns=batch.timestamp_ns,
                    item_count=batch.item_count,
                    payload=batch.payload,
                )
                wire = encode_frame(frame)
                decoded = frame_round_trip(wire)
                encoded_bytes += len(wire)
                if decoded.sequence != batch.sequence:
                    sequence_errors += 1
                if first_batch_sequence is None:
                    first_batch_sequence = decoded.sequence
                elif previous_batch_sequence is not None:
                    if decoded.sequence <= previous_batch_sequence:
                        sequence_errors += 1
                    else:
                        observed_batch_gaps += (
                            decoded.sequence - previous_batch_sequence - 1
                        )
                previous_batch_sequence = decoded.sequence
                if len(decoded.payload) != decoded.item_count * record.size:
                    sequence_errors += 1
                    continue
                for offset in range(0, len(decoded.payload), record.size):
                    item_sequence = record.unpack_from(decoded.payload, offset)[0]
                    if first_item_sequence is None:
                        first_item_sequence = item_sequence
                    elif previous_item_sequence is not None:
                        if item_sequence <= previous_item_sequence:
                            sequence_errors += 1
                        else:
                            observed_item_gaps += (
                                item_sequence - previous_item_sequence - 1
                            )
                    previous_item_sequence = item_sequence
                    consumed_items += 1
            finally:
                queue.task_done()
        await queue.join()
    finally:
        stop_event.set()
        producer.join(timeout=1.0)
        try:
            if producer.is_alive():
                raise RuntimeError("acquisition thread did not stop")
        finally:
            hub.unsubscribe(queue)

    elapsed = time.perf_counter() - started
    if producer_errors:
        raise RuntimeError("acquisition thread failed") from producer_errors[0]

    stats = stats_transform(hub.stats())
    if first_batch_sequence is None:
        observed_missing_batches = stats.produced_batches
    else:
        observed_missing_batches = first_batch_sequence - 1 + observed_batch_gaps
        if previous_batch_sequence is not None:
            if previous_batch_sequence > stats.produced_batches:
                sequence_errors += 1
            else:
                observed_missing_batches += (
                    stats.produced_batches - previous_batch_sequence
                )
    if first_item_sequence is None:
        observed_missing_items = stats.produced_items
    else:
        observed_missing_items = first_item_sequence + observed_item_gaps
        if previous_item_sequence is not None:
            if previous_item_sequence >= stats.produced_items:
                if previous_item_sequence != stats.produced_items - 1:
                    sequence_errors += 1
            else:
                observed_missing_items += (
                    stats.produced_items - previous_item_sequence - 1
                )
    unreported_drops = _loss_mismatch(
        produced_batches=stats.produced_batches,
        consumed_batches=consumed_batches,
        produced_items=stats.produced_items,
        consumed_items=consumed_items,
        reported_batches=stats.dropped_batches,
        reported_items=stats.dropped_items,
    )
    unreported_drops += abs(observed_missing_batches - stats.dropped_batches)
    unreported_drops += abs(observed_missing_items - stats.dropped_items)
    return BenchmarkResult(
        produced_items=stats.produced_items,
        consumed_items=consumed_items,
        reported_drops=stats.dropped_items,
        sequence_errors=sequence_errors,
        unreported_drops=unreported_drops,
        bytes_per_sec=encoded_bytes / elapsed if elapsed > 0 else 0.0,
        peak_queue_depth=stats.queue_high_water_mark,
        elapsed=elapsed,
    )


def run_benchmark(
    *,
    stream: str,
    rate: int,
    duration: float,
    channels: int = 1,
    _frame_round_trip: FrameRoundTrip | None = None,
    _stats_transform: StatsTransform | None = None,
) -> BenchmarkResult:
    """Run the benchmark; ``rate`` is aggregate samples per second."""
    if stream not in STREAM_TYPES:
        raise ValueError(f"stream must be one of: {', '.join(STREAM_TYPES)}")
    if isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0:
        raise ValueError("rate must be a positive integer samples/second")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be a positive finite number of seconds")
    if isinstance(channels, bool) or not isinstance(channels, int) or channels <= 0:
        raise ValueError("channels must be a positive integer")
    frame_round_trip = _frame_round_trip or decode_frame
    stats_transform = _stats_transform or (lambda stats: stats)
    return asyncio.run(
        _run_async(
            stream,
            rate,
            duration,
            channels,
            frame_round_trip,
            stats_transform,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream", choices=tuple(STREAM_TYPES), required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--rate", type=int, required=True, help="samples per second")
    parser.add_argument("--channels", type=int, default=1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = run_benchmark(
            stream=arguments.stream,
            rate=arguments.rate,
            duration=arguments.duration,
            channels=arguments.channels,
        )
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, separators=(",", ":")))
        return 2
    print(json.dumps(asdict(result), separators=(",", ":"), sort_keys=True))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
