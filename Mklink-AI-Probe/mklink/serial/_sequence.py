"""Bounded command sequence state, advanced only by the existing serial reader."""
import time


class SendSequence:
    def __init__(self, commands, interval_ms=1000, repeat=1):
        if type(interval_ms) is not int or not 20 <= interval_ms <= 3600000:
            raise ValueError('Sequence interval_ms must be 20..3600000')
        if type(repeat) is not int or not 0 <= repeat <= 1000000:
            raise ValueError('Sequence repeat must be 0..1000000 (0 means continuous)')
        if not isinstance(commands, list) or not 1 <= len(commands) <= 64:
            raise ValueError('Sequence requires 1..64 commands')
        payloads = []
        for command in commands:
            if not isinstance(command, dict) or set(command) - {'data', 'hex'}:
                raise ValueError('Sequence commands accept only data and hex')
            data, is_hex = command.get('data'), command.get('hex', False)
            if not isinstance(data, str) or type(is_hex) is not bool:
                raise ValueError('Sequence data must be text and hex must be boolean')
            payload = bytes.fromhex(data) if is_hex else data.encode('utf-8')
            if not 1 <= len(payload) <= 4096:
                raise ValueError('Each sequence command must contain 1..4096 bytes')
            payloads.append(payload)
        if sum(map(len, payloads)) > 65536:
            raise ValueError('Sequence payload exceeds 64 KiB')
        self.commands = tuple(payloads)
        self.interval_ms, self.repeat = interval_ms, repeat
        self.sent = 0
        self.state, self.error = 'running', ''
        self.due = time.monotonic()

    @property
    def active(self):
        return self.state == 'running'

    def finish_send(self):
        if self.active:
            if self.repeat and self.sent >= len(self.commands) * self.repeat:
                self.state = 'completed'
            # Never catch up a backlog with a burst after a delayed write.
            self.due = time.monotonic() + self.interval_ms / 1000

    def cancel(self, reason='', *, failed=False):
        if self.active:
            self.state, self.error = ('failed' if failed else 'cancelled'), reason

    def status(self):
        return dict(state=self.state, active=self.active, sent=self.sent,
                    command_count=len(self.commands), interval_ms=self.interval_ms,
                    repeat=self.repeat, error=self.error)
