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
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from mklink.remote.stream_hub import StreamBatch, StreamHub  # noqa: E402
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


async def _run_async(
    stream: str,
    rate: int,
    duration: float,
    channels: int,
) -> BenchmarkResult:
    hub = StreamHub(max_batches_per_client=QUEUE_BATCH_CAPACITY)
    queue = hub.subscribe()
    loop = asyncio.get_running_loop()
    target_items = max(1, math.ceil(rate * duration))
    batch_items = max(1, math.ceil(rate / TARGET_BATCHES_PER_SECOND))
    producer_done = threading.Event()
    producer_errors: list[BaseException] = []
    start_gate = threading.Event()

    def produce() -> None:
        try:
            start_gate.wait()
            start = time.perf_counter()
            produced = 0
            while produced < target_items:
                count = min(batch_items, target_items - produced)
                hub.publish_threadsafe(
                    loop,
                    _payload(produced, count, channels),
                    item_count=count,
                )
                produced += count
                deadline = start + produced / rate
                remaining = deadline - time.perf_counter()
                if remaining > 0:
                    producer_done.wait(remaining)
        except BaseException as exc:  # propagate acquisition-thread failures
            producer_errors.append(exc)
        finally:
            producer_done.set()

    producer = threading.Thread(
        target=produce,
        name="stream-benchmark-acquisition",
        daemon=False,
    )
    producer.start()
    started = time.perf_counter()
    start_gate.set()

    consumed_items = 0
    encoded_bytes = 0
    sequence_errors = 0
    previous_item_sequence: int | None = None
    record = struct.Struct(f"<Q{channels}f")

    try:
        while True:
            if producer_done.is_set() and queue.empty():
                # Let any final call_soon_threadsafe delivery run before exit.
                await asyncio.sleep(0)
                if queue.empty():
                    break
            try:
                batch = await asyncio.wait_for(queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue
            try:
                if not isinstance(batch, StreamBatch):
                    sequence_errors += 1
                    continue
                wire = encode_frame(
                    Frame(
                        stream_type=STREAM_TYPES[stream],
                        flags=0,
                        stream_id=1,
                        sequence=batch.sequence,
                        timestamp_ns=batch.timestamp_ns,
                        item_count=batch.item_count,
                        payload=batch.payload,
                    )
                )
                decoded = decode_frame(wire)
                encoded_bytes += len(wire)
                if len(decoded.payload) != decoded.item_count * record.size:
                    sequence_errors += 1
                    continue
                for offset in range(0, len(decoded.payload), record.size):
                    item_sequence = record.unpack_from(decoded.payload, offset)[0]
                    if (
                        previous_item_sequence is not None
                        and item_sequence <= previous_item_sequence
                    ):
                        sequence_errors += 1
                    previous_item_sequence = item_sequence
                    consumed_items += 1
            finally:
                queue.task_done()
    finally:
        producer.join(timeout=max(1.0, duration + 1.0))
        hub.unsubscribe(queue)

    elapsed = time.perf_counter() - started
    if producer.is_alive():
        raise RuntimeError("acquisition thread did not stop")
    if producer_errors:
        raise RuntimeError("acquisition thread failed") from producer_errors[0]

    stats = hub.stats()
    missing_items = max(0, stats.produced_items - consumed_items)
    unreported_drops = max(0, missing_items - stats.dropped_items)
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
    return asyncio.run(_run_async(stream, rate, duration, channels))


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
    return 1 if result.sequence_errors or result.unreported_drops else 0


if __name__ == "__main__":
    raise SystemExit(main())
