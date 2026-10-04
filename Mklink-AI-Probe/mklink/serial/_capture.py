"""Shared raw serial capture; no serial reader or auto-reply in this process."""
import time
from mklink.runtime import RuntimeErrorResponse


class SerialCapture:
    def __init__(self, client, port, logger, parser=None):
        self.client, self.port, self.logger, self.parser = client, port, logger, parser
        tail = client.call('serial_history')
        self.session, self.cursor = tail['session'], tail['next_seq']
        if not tail['running'] or tail['ports'].get(port) != 'open':
            raise RuntimeErrorResponse('Selected serial port is not open')

    def page(self, target=None):
        page = self.client.call('serial_history', {'session': self.session, 'after': self.cursor, 'limit': 256})
        if page['dropped_batches']:
            raise RuntimeErrorResponse(f"Serial capture lost {page['dropped_batches']} batches; log is incomplete")
        for entry in page['entries']:
            if target is not None and entry['seq'] > target:
                break
            if entry['port'] == self.port:
                data = bytes.fromhex(entry['hex'])
                frames = []
                if self.parser is not None and entry['direction'] == 'RX':
                    frames = [{'raw_hex': frame.raw.hex(), 'crc_valid': frame.crc_valid, 'fields': frame.fields}
                              for frame in self.parser.feed(data)]
                self.logger.log(entry['direction'], self.port, data,
                                timestamp=entry['timestamp_ns'] / 1e9, frames=frames)
            self.cursor = entry['seq']
        status = page['ports'].get(self.port, 'closed')
        if status.startswith('error:') or (page['running'] and status != 'open'):
            raise RuntimeErrorResponse(f'Serial capture stopped: {status}')
        return page

    def drain(self):
        page = self.page()
        target = page['latest_seq']
        while self.cursor < target:
            self.page(target)

    def run(self, duration):
        deadline = time.monotonic() + duration if duration else None
        try:
            while deadline is None or time.monotonic() < deadline:
                page = self.page()
                if not page['running']:
                    return
                if self.cursor < page['latest_seq']:
                    continue
                remaining = deadline - time.monotonic() if deadline is not None else .02
                if remaining > 0:
                    time.sleep(min(.02, remaining))
        except KeyboardInterrupt:
            pass  # caller stops owned producer, drains final batches, then closes file
