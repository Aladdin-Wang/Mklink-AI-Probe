"""One bounded acquisition cache, independent cursors for every client/channel."""
import threading


class RttChannelCache:
    LIMIT = 65536
    READ_LIMIT = 16384

    def __init__(self):
        self._lock = threading.Lock()
        self.reset('', [])

    def reset(self, session, channels):
        with self._lock:
            self.session = session
            self._data = {ch: bytearray() for ch in channels}
            self._ends = {ch: 0 for ch in channels}

    @property
    def channels(self):
        with self._lock:
            return list(self._data)

    def append(self, channel, data):
        with self._lock:
            buf = self._data[channel]
            self._ends[channel] += len(data)
            buf.extend(data[-self.LIMIT:])
            del buf[:-self.LIMIT]

    def read(self, channel=0, cursor=0, session=None):
        with self._lock:
            if type(channel) is not int or channel not in self._data:
                raise ValueError('RTT channel is not subscribed')
            if type(cursor) is not int or cursor < 0:
                raise ValueError('cursor must be a nonnegative integer')
            reset = session is not None and session != self.session
            if reset:
                cursor = 0
            end = self._ends[channel]
            if cursor > end:
                raise ValueError('cursor exceeds channel position')
            buf = self._data[channel]
            first = end - len(buf)
            lost = max(0, first - cursor)
            start = max(cursor, first)
            data = bytes(buf[start-first:start-first+self.READ_LIMIT])
            return dict(channel=channel, session=self.session, reset=reset,
                        cursor=start+len(data), available_end=end,
                        lost_bytes=lost, data_hex=data.hex())
