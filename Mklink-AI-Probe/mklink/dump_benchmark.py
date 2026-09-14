"""Bounded periodic mem_dump measurement without a waveform GUI."""
from __future__ import annotations

from collections import Counter
import math
import time


def measure(device, regions: list[tuple[int, int]], *, duration: float = 3,
            period: float = 0.000001, speed_profile: str | None = None) -> dict:
    from mklink.dump_memory import DumpMemoryStreamSession, build_dump_mem_command

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
    if speed_profile is not None:
        device.set_debug_speed(speed_profile)
    device._require_connected()
    session = DumpMemoryStreamSession(device._bridge, regions, period)
    intervals = Counter()
    first_seen = first = last = None
    count = 0
    pending_ts = None
    pending_blocks = pending_bytes = 0
    # Only interval counts are retained, not millions of raw sample objects.
    session.start()
    start = time.monotonic()
    try:
        while time.monotonic() - start < duration:
            frames = session.read_frames(max_bytes=262144)
            for frame in frames:
                if frame['flags']:
                    raise RuntimeError('mem_dump firmware reported a sample error')
                ts = frame['timestamp_us']
                payload_bytes = sum(len(data) for _, data in frame['regions'])
                if frame.get('format') == 'B1':
                    index = frame['block_index']
                    if index == 0:
                        if pending_blocks:
                            raise RuntimeError('mem_dump incomplete block sequence')
                        pending_ts, pending_bytes = ts, 0
                    # V4 timestamps each physical B1 block separately. Keep
                    # the first block's timestamp for the complete sample.
                    if pending_ts is None or ts < pending_ts or index != pending_blocks:
                        raise RuntimeError('mem_dump block sequence gap')
                    if frame['block_count'] != (size + 2047) // 2048:
                        raise RuntimeError('mem_dump block count mismatch')
                    pending_blocks += 1
                    pending_bytes += payload_bytes
                    if pending_blocks < frame['block_count']:
                        continue
                    payload_bytes = pending_bytes
                    pending_blocks = 0
                    ts = pending_ts
                else:
                    if sorted((i, len(data)) for i, data in frame['regions']) != list(enumerate(n for _, n in regions)):
                        raise RuntimeError('mem_dump region coverage mismatch')
                if payload_bytes != size:
                    raise RuntimeError('mem_dump sample byte count mismatch')
                if first_seen is None:
                    first_seen = ts
                if ts - first_seen < 200000:
                    continue
                if last is not None:
                    if ts <= last:
                        raise RuntimeError('mem_dump non-increasing timestamp')
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
    if any(stats[k] for k in ('parser_crc_errors','parser_dropped_frames','firmware_flagged_frames')):
        raise RuntimeError(f'mem_dump integrity failure: {stats}')
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
            'timing_source': 'probe sample timestamps; complete samples only'}
