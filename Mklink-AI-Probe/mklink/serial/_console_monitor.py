"""Passive console rendering of shared serial batches, with bounded per-source text."""
import codecs
import json
import re
import time
from datetime import datetime


class ConsoleMonitor:
    def __init__(self, mode='ascii', filter_pattern=None, logger=None):
        if mode not in ('ascii', 'hex'):
            raise ValueError('Monitor mode must be ascii or hex')
        try:
            self._filter = re.compile(filter_pattern) if filter_pattern else None
        except re.error as error:
            raise ValueError(f'Invalid monitor filter: {error}') from error
        self._mode, self._logger = mode, logger
        self._sources = {}

    def _write(self, port, direction, timestamp, text, *, partial=False):
        if self._filter is not None and not self._filter.search(text):
            return
        # Do not let received terminal controls erase or impersonate console lines.
        visible = ''.join(c if c.isprintable() or c == '\t' else repr(c)[1:-1] for c in text)
        stamp = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3]
        print(f"[{stamp}] {direction} {port}{' [partial]' if partial else ''}: {visible}", flush=True)

    def log(self, direction, port, data, *, timestamp=None, frames=None):
        if self._logger is not None:
            self._logger.log(direction, port, data, timestamp=timestamp, frames=frames)
        timestamp = time.time() if timestamp is None else timestamp
        if not data:
            pass  # Idle-frame annotations carry no additional wire bytes.
        elif self._mode == 'hex':
            self._write(port, direction, timestamp, data.hex(' ').upper())
        else:
            key = (port, direction)
            source = self._sources.get(key)
            if source is None:
                source = self._sources[key] = {
                    'decoder': codecs.getincrementaldecoder('utf-8')('replace'),
                    'text': '', 'timestamp': timestamp, 'updated': time.monotonic(),
                }
            if not source['text']:
                source['timestamp'] = timestamp
            source['text'] += source['decoder'].decode(data)
            source['updated'] = time.monotonic()
            while source['text']:
                end = source['text'].find('\n')
                complete = 0 <= end < 4096
                if not complete and len(source['text']) < 4096:
                    break
                count = end + 1 if complete else 4096
                text, source['text'] = source['text'][:count], source['text'][count:]
                self._write(port, direction, source['timestamp'], text[:-1] if complete else text, partial=not complete)
                source['timestamp'] = timestamp
        for frame in frames or []:
            self._write(port, direction, timestamp, 'decoded: ' + json.dumps(frame, ensure_ascii=False))

    def tick(self):
        now = time.monotonic()
        for (port, direction), source in self._sources.items():
            if source['text'] and now - source['updated'] >= .1:
                self._write(port, direction, source['timestamp'], source['text'], partial=True)
                source['text'] = ''

    def set_mode(self, mode):
        if mode not in ('ascii', 'hex'):
            raise ValueError('Mode must be ascii or hex')
        self.finish()
        self._mode = mode

    def set_filter(self, pattern):
        try:
            compiled = re.compile(pattern) if pattern else None
        except re.error as error:
            raise ValueError(f'Invalid monitor filter: {error}') from error
        self._filter = compiled

    def finish(self):
        for (port, direction), source in self._sources.items():
            text = source['text'] + source['decoder'].decode(b'', final=True)
            if text:
                self._write(port, direction, source['timestamp'], text, partial=True)
        self._sources.clear()
