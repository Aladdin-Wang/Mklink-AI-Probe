"""Adapt bounded multiplex watch events to the existing SuperWatch decoder."""
import math
import struct
import time
from typing import NamedTuple


class PackedWatchSample(NamedTuple):
    timestamp_us: int
    payload: bytes
    offset: int


class MuxWatchCapacityError(ValueError):
    """Configuration cannot fit the bounded multiplex sampler."""


class MuxWatchSession:
    def __init__(self, transport, regions, period):
        self.transport = transport
        self.regions = regions
        self.parts = [(index, address+offset, min(128, size-offset))
                      for index, (address, size) in enumerate(regions)
                      for offset in range(0, size, 128)]
        if not self.parts or len(self.parts) > 15:
            raise MuxWatchCapacityError('Multiplex watch allows 15 regions of at most 128 bytes; select fewer/smaller variables')
        if not math.isfinite(period) or period < 0:
            raise MuxWatchCapacityError('Multiplex watch period must be finite and nonnegative')
        self.period = max(1, math.ceil(period*1000000))
        if period == 0:
            self.period = 2000
        if self.period > 60000000:
            raise MuxWatchCapacityError('Multiplex watch period exceeds 60 seconds')
        self._pending = []
        self._last_clock = None
        self._clock_high = 0
        self.samples = 0
        self.gaps = 0
        self.read_errors = 0
        self._read_failure_since = None
        # A read error is not a transport disconnect. Allow subsequent scheduled
        # samples to recover, including slow configurations and batched delivery.
        self._read_failure_timeout = max(3.0, self.period / 1000000 * 3 + 0.5)

    def start(self):
        # DumpMemoryStreamSession validates capacity before opening transport.
        # Negotiate units only after the real firmware capabilities are known.
        if not getattr(self.transport, 'capabilities', 0) & 8:
            raise RuntimeError('SuperWatch requires the matching grouped-sampling firmware; update the probe firmware and host together')
        self.transport.drain(0x41, 255)
        body = struct.pack('<IB', self.period, len(self.parts))
        body += b''.join(struct.pack('<IB', address, size) for _, address, size in self.parts)
        with self.transport._commands:
            self.transport.request(0x32, body)
            self.transport.watch_running = True

    def read_frames(self, *, packed=False):
        result = []
        now = time.monotonic()
        # Keep decoding/publication bursts below the bounded RX queue's time
        # budget. Draining 64 KiB expands into thousands of Python sample
        # objects and can stall the next drain long enough to overflow it.
        for event in self.transport.drain(0x41, 255, max_bytes=16384):
            if len(event) < 6:
                raise RuntimeError('Invalid multiplex watch event')
            index, status = event[:2]
            if status == 7:
                self._pending = []
                raise RuntimeError('DAP changed the target; SuperWatch capture was invalidated. Restart capture after debugging.')
            if status == 5:
                if len(event) != 6 or index >= len(self.parts):
                    raise RuntimeError('Invalid multiplex watch read-error event')
                self._pending = []
                self.gaps += 1
                self.read_errors += 1
                if self._read_failure_since is None:
                    self._read_failure_since = now
                # Firmware retains the subscription. Do not replay commands,
                # reset the target, lower its clock or publish stale/zero values.
                continue
            if status and status != 9:
                self._pending = []
                self.gaps += 1
                raise RuntimeError(f'SuperWatch target read failed (status {status}); capture stopped. Check the target connection and sampling debug speed before restarting.')
            if status == 9:
                size = sum(n for _, _, n in self.parts)
                stride = 4+size
                if (len(event) < 4 or event[0] or not 4 <= size <= 64 or size % 4
                        or event[3] != size or not 1 <= event[2] <= min(127, 1020//stride)
                        or len(event) != 4+stride*event[2]):
                    raise RuntimeError('Invalid multiplex watch batch')
                self._pending = []
                self._read_failure_since = None
                for offset in range(4, len(event), stride):
                    timestamp = struct.unpack_from('<I', event, offset)[0]
                    if packed:
                        result.append(PackedWatchSample(self._timestamp(timestamp), event, offset+4))
                        continue
                    cursor = offset+4
                    regions = []
                    for index, (_, length) in enumerate(self.regions):
                        regions.append((index, event[cursor:cursor+length]))
                        cursor += length
                    result.append(self._frame(timestamp, regions))
                continue
            timestamp = struct.unpack_from('<I', event, 2)[0]
            if index == 0:
                if self._pending:
                    self.gaps += 1
                self._pending = []
            if index >= len(self.parts) or index != len(self._pending) or status or len(event)-6 != self.parts[index][2]:
                self._pending = []
                self.gaps += 1
                continue
            self._pending.append(event[6:])
            if len(self._pending) != len(self.parts):
                continue
            regions = [bytearray() for _ in self.regions]
            for (logical, _, _), data in zip(self.parts, self._pending):
                regions[logical].extend(data)
            self._pending = []
            self._read_failure_since = None
            result.append(self._frame(timestamp, [(i, bytes(data)) for i, data in enumerate(regions)]))
        if (self._read_failure_since is not None
                and now - self._read_failure_since >= self._read_failure_timeout
                and not result):
            raise RuntimeError(
                f'SuperWatch target read failed continuously (status 5); '
                f'no valid sample for {self._read_failure_timeout:g}s. Capture stopped; '
                'check the target connection, selected addresses and sampling debug speed.'
            )
        return result

    def _frame(self, timestamp, regions):
        return {'format': 'mux', 'timestamp_us': self._timestamp(timestamp),
                'flags': 0, 'regions': regions}

    def _timestamp(self, timestamp):
        if self._last_clock is not None and timestamp < self._last_clock:
            self._clock_high += 1 << 32
        self._last_clock = timestamp
        self.samples += 1
        return timestamp+self._clock_high

    def write(self, address, data, future):
        try:
            self.transport.write_memory(address, data)
            readback = self.transport.read_memory(address, len(data))
            if readback != data:
                raise RuntimeError('Multiplex write readback mismatch')
            future.set_result({'data': readback, 'mode': 'cdc-mux', 'timestamp_us': None})
        except Exception as exc:
            future.set_exception(exc)
            raise

    def stop(self):
        with self.transport._commands:
            self.transport.request(0x31)
            self.transport.watch_running = False
