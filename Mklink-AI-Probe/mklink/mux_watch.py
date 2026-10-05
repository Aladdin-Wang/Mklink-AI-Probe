"""Adapt bounded multiplex watch events to the existing SuperWatch decoder."""
import math
import struct


class MuxWatchSession:
    def __init__(self, transport, regions, period):
        self.transport = transport
        self.regions = regions
        self.parts = [(index, address+offset, min(128, size-offset))
                      for index, (address, size) in enumerate(regions)
                      for offset in range(0, size, 128)]
        if not self.parts or len(self.parts) > 15:
            raise ValueError('Multiplex watch allows 15 regions of at most 128 bytes; select fewer/smaller variables')
        self.period = max(2, math.ceil(period*1000))
        if self.period > 60000:
            raise ValueError('Multiplex watch period exceeds 60 seconds')
        self._pending = []
        self._last_clock = None
        self._clock_high = 0
        self.samples = 0
        self.gaps = 0

    def start(self):
        self.transport.drain(0x41, 255)
        body = struct.pack('<HB', self.period, len(self.parts))
        body += b''.join(struct.pack('<IB', address, size) for _, address, size in self.parts)
        with self.transport._commands:
            self.transport.request(0x30, body)
            self.transport.watch_running = True
            self.transport.drain(0x41, 255)

    def read_frames(self):
        result = []
        for event in self.transport.drain(0x41, 255):
            index, status = event[:2]
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
            if self._last_clock is not None and timestamp < self._last_clock:
                self._clock_high += 1 << 32
            self._last_clock = timestamp
            self.samples += 1
            result.append({'format': 'mux', 'timestamp_us': (timestamp+self._clock_high)*1000,
                           'flags': 0, 'regions': [(i, bytes(data)) for i, data in enumerate(regions)]})
        return result

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
