"""RTT adapter over the shared framed transport; never reads the COM handle."""
import struct
import time


class MuxRTTSession:
    def __init__(self, transport, info, channel=0, channels=None):
        self.transport = transport
        self.info = info
        self._channel = channel
        self.channels = list(channels or [channel])
        self._running = False

    def start(self, addr, **unused):
        up = sum(1 << ch for ch in self.channels)
        down = sum(1 << item['channel'] for item in self.info['down_buffers']
                   if item['active'] and item['channel'] in self.channels)
        with self.transport._commands:
            self.transport.request(0x20, struct.pack('<IBB', int(addr, 0), up, down))
            self.transport.rtt_mask = up
            for ch in self.channels:
                self.transport.drain(0x40, ch)
        self._running = True
        return {'control_block_addr': addr, 'transport': 'cdc-mux', 'channels': self.channels}

    def read_channels(self, duration=.01):
        deadline = time.monotonic()+max(0, duration)
        result = {ch: bytearray() for ch in self.channels}
        while True:
            for ch in self.channels:
                for frame in self.transport.drain(0x40, ch):
                    if frame[1] == 7:
                        raise RuntimeError('DAP changed the target; RTT capture was invalidated. Restart capture after debugging.')
                    if frame[1]:
                        raise RuntimeError('RTT target read failed')
                    result[ch].extend(frame[6:])
            if time.monotonic() >= deadline or any(result.values()):
                return {ch: bytes(data) for ch, data in result.items()}
            time.sleep(min(.005, max(0, deadline-time.monotonic())))

    def read_output_bytes(self, duration=10):
        return self.read_channels(duration).get(self._channel, b'')

    def read_output(self, duration=10):
        return self.read_output_bytes(duration).decode('utf-8', 'replace')

    def send_input(self, data, channel=None):
        channel = self._channel if channel is None else channel
        if channel not in self.channels:
            raise ValueError('RTT channel is not subscribed')
        offset = 0
        deadline = time.monotonic()+3
        while offset < len(data):
            answer = self.transport.request(0x21, bytes([channel])+data[offset:offset+128])
            if len(answer) != 1 or answer[0] > min(128, len(data)-offset):
                raise RuntimeError('Invalid RTT acceptance count; do not replay')
            offset += answer[0]
            if not answer[0]:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f'RTT target buffer full; {offset} bytes accepted, do not replay the whole request')
                time.sleep(.005)
        return True

    def stop(self):
        if self._running:
            with self.transport._commands:
                self.transport.request(0x22)
                self.transport.rtt_mask = 0
            self._running = False
        return ''

    def reset_failed_start(self):
        # A timed-out framed command is never recovered with raw text.
        return ''
