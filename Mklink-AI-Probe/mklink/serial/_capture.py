"""Shared raw serial capture; no serial reader or auto-reply in this process."""
import time
from mklink.runtime import RuntimeErrorResponse


def _frame_records(frames):
    return [{'raw_hex': frame.raw.hex(), 'crc_valid': frame.crc_valid, 'fields': frame.fields}
            for frame in frames]


class SerialCapture:
    def __init__(self, client, parsers, logger):
        self.client, self.parsers, self.logger = client, dict(parsers), logger
        tail = client.call('serial_history')
        self.session, self.cursor = tail['session'], tail['next_seq']
        if not tail['running'] or any(tail['ports'].get(port) != 'open' for port in self.parsers):
            raise RuntimeErrorResponse('Selected serial port is not open')

    def page(self, target=None):
        page = self.client.call('serial_history', {'session': self.session, 'after': self.cursor, 'limit': 256})
        if page['dropped_batches']:
            raise RuntimeErrorResponse(f"Serial capture lost {page['dropped_batches']} batches; capture is incomplete")
        for entry in page['entries']:
            if target is not None and entry['seq'] > target:
                break
            if entry['port'] in self.parsers:
                data = bytes.fromhex(entry['hex'])
                frames = []
                parser = self.parsers[entry['port']]
                try:
                    if parser is not None and entry['direction'] == 'RX':
                        frames = _frame_records(parser.feed(data,
                            monotonic_time=entry['first_monotonic'], end_time=entry['last_monotonic']))
                finally:
                    # Preserve the offending raw batch even when decoding fails.
                    # Advance only after a successful write so it is not repeated.
                    self.logger.log(entry['direction'], entry['port'], data,
                                    timestamp=entry['timestamp_ns'] / 1e9, frames=frames)
                    self.cursor = entry['seq']
            self.cursor = entry['seq']
        if self.cursor >= page['latest_seq']:
            for port, parser in self.parsers.items():
                if parser is None:
                    continue
                cutoff = page['idle_cutoffs'].get(port)
                if cutoff is not None:
                    frames = _frame_records(parser.feed(b'', monotonic_time=cutoff))
                    if frames:
                        # Annotation-only record; never invent or repeat RX bytes.
                        self.logger.log('PARSED', port, b'', timestamp=time.time(), frames=frames)
        for port in self.parsers:
            status = page['ports'].get(port, 'closed')
            if status.startswith('error:') or (page['running'] and status != 'open'):
                raise RuntimeErrorResponse(f'Serial capture stopped on {port}: {status}')
        return page

    def drain(self):
        page = self.page()
        target = page['latest_seq']
        while self.cursor < target:
            self.page(target)

    def run(self, duration, *, on_poll=None):
        deadline = time.monotonic() + duration if duration else None
        try:
            while deadline is None or time.monotonic() < deadline:
                page = self.page()
                if not page['running']:
                    return
                if on_poll is not None and on_poll() is False:
                    return
                if self.cursor < page['latest_seq']:
                    continue
                remaining = deadline - time.monotonic() if deadline is not None else .02
                if remaining > 0:
                    time.sleep(min(.02, remaining))
        except KeyboardInterrupt:
            pass  # caller stops owned producer, drains final batches, then closes file
