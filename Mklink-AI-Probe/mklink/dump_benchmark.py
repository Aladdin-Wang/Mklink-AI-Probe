"""Bounded periodic mem_dump measurement without a waveform GUI."""
from __future__ import annotations

from collections import Counter
import math
import time


def validate_measurement(regions: list[tuple[int, int]], duration: float = 3,
                         period: float = 0.000001, speed_profile: str | None = None) -> int:
    from mklink.dump_memory import build_dump_mem_command

    if isinstance(duration, bool) or not isinstance(duration, (float, int)) or not math.isfinite(duration) or not .5 <= duration <= 30:
        raise ValueError("duration must be 0.5..30 seconds")
    if isinstance(period, bool) or not isinstance(period, (float, int)) or not math.isfinite(period) or not .000001 <= period <= .1:
        raise ValueError("period must be 0.000001..0.1 seconds")
    if not isinstance(regions, list) or not 1 <= len(regions) <= 15:
        raise ValueError("regions must contain 1..15 address/size pairs")
    for pair in regions:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise ValueError("invalid address/size pair")
        a, n = pair
        if type(a) is not int or type(n) is not int or a < 0 or n <= 0 or a + n > 0x100000000:
            raise ValueError("invalid 32-bit memory range")
    size = sum(n for _, n in regions)
    if size > 4096:
        raise ValueError("measurement is limited to 4096 bytes per sample")
    build_dump_mem_command(regions, period)
    if speed_profile is not None and speed_profile not in ('low', 'medium', 'high', 'ultra'):
        raise ValueError('speed_profile must be low/medium/high/ultra')
    return size


def measurement_regions(regions):
    if not isinstance(regions, list) or any(not isinstance(r, dict) or set(r) != {'address', 'size'} for r in regions):
        raise ValueError('regions must be address/size objects')
    return [(r['address'], r['size']) for r in regions]


def measure(device, regions: list[tuple[int, int]], *, duration: float = 3,
            period: float = 0.000001, speed_profile: str | None = None, cancelled=None) -> dict:
    """Measure complete samples, using the common assembler and stream lifecycle.

    Allow 2s for startup; duration begins at the first complete sample and
    includes the existing 200ms probe-timestamp warmup. No raw sample history.
    """
    from mklink.dump_memory import DumpMemoryStreamSession, DumpSampleAssembler, check_capture_cancelled
    from mklink.mux_watch import PackedWatchSample
    size = validate_measurement(regions, duration, period, speed_profile)
    check_capture_cancelled(cancelled)
    device._require_connected()
    if speed_profile is not None:
        device.set_debug_speed(speed_profile)
    session = DumpMemoryStreamSession(device._bridge, regions, period, allow_legacy_bulk=True)
    # MUX batches already contain validated complete samples. Avoid expanding
    # each one into region dictionaries and assembling it a second time.
    session.packed_frames = True
    intervals = Counter()
    first_seen = first = last = last_complete = None
    count = 0
    assembler = DumpSampleAssembler([n for _, n in regions], ordered=True)
    # Keep only interval counts, not millions of raw sample objects.
    try:
        session.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            check_capture_cancelled(cancelled)
            frames = session.read_frames(max_bytes=262144)
            for frame in frames:
                check_capture_cancelled(cancelled)
                if isinstance(frame, PackedWatchSample):
                    ts = frame.timestamp_us
                else:
                    payloads = assembler.feed(frame)
                    if payloads is None:
                        continue
                    ts = assembler.timestamp_us
                    assembler = DumpSampleAssembler([n for _, n in regions], ordered=True)
                if last_complete is not None and ts <= last_complete:
                    raise RuntimeError('mem_dump non-increasing timestamp')
                last_complete = ts
                if first_seen is None:
                    first_seen = ts
                    deadline = time.monotonic() + duration
                if ts - first_seen < 200000:
                    continue
                if last is not None:
                    intervals[ts-last] += 1
                else:
                    first = ts
                last = ts
                count += 1
            if not frames:
                time.sleep(.0005)
    finally:
        session.stop()
    stats = session.stats
    if any(stats.get(k, 0) for k in ('parser_crc_errors','parser_dropped_frames',
                                   'parser_dropped_bytes','firmware_flagged_frames')):
        raise RuntimeError(f'mem_dump integrity failure: {stats}; max_interval_us={max(intervals, default=0)}')
    if count < 2 or last <= first:
        raise RuntimeError('Not enough complete mem_dump samples')
    def quantile(fraction):
        target = max(1, math.ceil((count-1)*fraction))
        total = 0
        for value, occurrences in sorted(intervals.items()):
            total += occurrences
            if total >= target:
                return value
    hz = (count-1)*1e6/(last-first)
    return {'clock_hz': device._bridge._ctx.swd_clock_hz,
            'duration_s': duration, 'warmup_us': 200000, 'period_s': period,
            'regions': [{'address': hex(a), 'size': n} for a,n in regions],
            'samples': count, 'sample_hz': hz, 'payload_bytes_per_second': hz*size,
            'median_interval_us': quantile(.5), 'p99_interval_us': quantile(.99),
            'max_interval_us': max(intervals), 'integrity': stats,
            'incomplete_tail': bool(assembler.blocks),
            'timing_source': 'probe sample timestamps; complete samples only'}
