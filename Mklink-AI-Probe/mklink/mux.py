"""Bounded V4 CDC multiplex transport, fed by the bridge's sole reader.

No serial handle or reader thread here. Writes share one request slot; a timeout
poisons the session and is never retried or silently converted into Pika source.
"""
from __future__ import annotations

from collections import deque
import binascii
import secrets
import struct
import threading
import time


class MuxError(ConnectionError):
    pass


class MuxTargetError(RuntimeError):
    def __init__(self, status):
        self.status = status
        message = ('Multiplex target busy (status 6); debugger access is currently reserved. '
                   'Retry explicitly when available; the request was not replayed'
                   if status == 6 else
                   f'Multiplex target status {status}; failed writes may have an unknown outcome')
        super().__init__(message)


def packet(op, epoch, request, payload=b''):
    if len(payload) > 256:
        raise ValueError('Multiplex payload exceeds 256 bytes')
    raw = struct.pack('<4sBBHII', b'MLX1', 1, op, len(payload), epoch, request) + payload
    return raw + struct.pack('<I', binascii.crc32(raw) & 0xffffffff)


class MuxTransport:
    MAX_QUEUE_BYTES = 65536
    # ~160 ms at 200k 4-byte samples/s (timestamp + value). RTT queues keep
    # their original limit; replies bypass event queues. Still drop oldest on
    # sustained overload, never block the sole USB reader or command replies.
    WATCH_QUEUE_BYTES = 262144

    def __init__(self, write, command_lock=None):
        self._write = write
        self._condition = threading.Condition()
        self._commands = command_lock or threading.RLock()
        self._rx = bytearray()
        self._pending = None
        self._reply = None
        self._error = None
        self._next_id = 0
        self.epoch = 0
        self.nonce = secrets.token_bytes(8)
        self.ready = False
        self.capabilities = 0
        self.rtt_mask = 0
        self.watch_running = False
        self._last_command = time.monotonic()
        self._queues = {}
        self._sizes = {}
        self.dropped_bytes = {}
        self.event_gaps = 0
        self._event_id = None

    @property
    def sampling(self):
        return bool(self.rtt_mask or self.watch_running)

    def fail(self, error):
        with self._condition:
            if self._error is None:
                self._error = MuxError(str(error))
            self.ready = False
            self._condition.notify_all()

    def _check(self):
        if self._error:
            raise self._error

    def _send(self, op, payload, heartbeat=False):
        self._next_id += 1
        if self._next_id > 0xffffffff:
            raise MuxError('Request IDs exhausted; close and create a new session')
        req = self._next_id
        self._pending = (op, req, time.monotonic()+3, heartbeat)
        self._reply = None
        wire = packet(op, 0 if op == 1 else self.epoch, req,
                      (self.nonce if 0x10 <= op < 0x40 else b'') + payload)
        self._last_command = time.monotonic()
        try:
            count = self._write(wire)
            if count is not None and count != len(wire):
                raise MuxError('Partial serial write; outcome unknown')
        except Exception as exc:
            self.fail(exc)
            raise

    def request(self, op, payload=b''):
        with self._commands, self._condition:
            self._check()
            while self._pending:
                self._wait()
            self._send(op, payload)
            while self._pending:
                self._wait()
            self._check()
            answer = self._reply
            self._reply = None
            if not answer:
                raise MuxError('Empty command response')
            if answer[0] in (3, 4):
                self.fail('Claim expired or request duplicated; reconnect explicitly')
                self._check()
            if answer[0]:
                raise MuxTargetError(answer[0])
            return answer[1:]

    def _wait(self):
        self._check()
        remaining = self._pending[2]-time.monotonic()
        if remaining <= 0:
            self.fail('Multiplex command timed out; outcome unknown, no replay')
            self._check()
        self._condition.wait(min(remaining, .1))
        self._check()

    def handshake(self):
        caps = self.request(1)
        if len(caps) != 8 or struct.unpack_from('<I', caps)[0] & 3 != 3:
            raise MuxError('Firmware does not support multiplex target operations')
        self.capabilities = struct.unpack_from('<I', caps)[0]
        if self.request(4, self.nonce) != self.nonce:
            raise MuxError('Session claim mismatch')
        self.ready = True

    def tick(self):
        """Called by the serial reader even when no bytes arrive."""
        with self._condition:
            if self._error:
                return
            if self._pending and time.monotonic() >= self._pending[2]:
                self.fail('Multiplex response timed out; outcome unknown')
            elif self.ready and not self._pending and self._reply is None and time.monotonic()-self._last_command >= 1:
                self._send(2, b'', heartbeat=True)

    def feed(self, data):
        with self._condition:
            if self._error:
                return
            self._rx.extend(data)
            while True:
                at = self._rx.find(b'MLX1')
                if at < 0:
                    del self._rx[:-3]
                    return
                if at:
                    del self._rx[:at]
                if len(self._rx) < 16:
                    return
                _, version, op, n, epoch, req = struct.unpack_from('<4sBBHII', self._rx)
                limit = 1024 if op == 0x41 and self.capabilities & 8 else 256
                # Version 2 is restricted to advertised Watch events. Commands,
                # replies and RTT retain their CRC-protected version 1 framing.
                watch_raw = version == 2 and op == 0x41 and bool(self.capabilities & 16)
                if (version != 1 and not watch_raw) or n > limit:
                    self.fail('Malformed multiplex frame')
                    self._rx.clear()
                    return
                frame_size = n + (16 if watch_raw else 20)
                if len(self._rx) < frame_size:
                    return
                raw = bytes(self._rx[:frame_size]); del self._rx[:frame_size]
                if not watch_raw and binascii.crc32(raw[:-4]) & 0xffffffff != struct.unpack_from('<I', raw, n+16)[0]:
                    self.fail('Multiplex CRC error; session requires explicit reconnect')
                    return
                payload = raw[16:16+n]
                if op & 0x80:
                    if not self._pending or (op & 0x7f, req) != self._pending[:2]:
                        self.fail('Unexpected multiplex response')
                        return
                    hello = self._pending[0] == 1
                    if not hello and epoch != self.epoch:
                        self.fail('Multiplex session expired; no automatic reconfiguration')
                        return
                    if hello:
                        self.epoch = epoch
                    heartbeat = self._pending[3]
                    self._reply = payload
                    self._pending = None
                    if heartbeat and payload != b'\0':
                        self.fail('Heartbeat rejected')
                    if heartbeat:
                        self._reply = None
                    self._condition.notify_all()
                elif op in (0x40, 0x41):
                    if epoch != self.epoch or len(payload) < 6:
                        self.fail('Invalid stream event')
                        return
                    if payload[0] >= (8 if op == 0x40 else 15):
                        self.fail('Invalid event channel')
                        return
                    if self._event_id is not None:
                        self.event_gaps += (req-self._event_id-1) & 0xffffffff
                    self._event_id = req
                    key = (op, payload[0] if op == 0x40 else 255)
                    queue = self._queues.setdefault(key, deque())
                    size = self._sizes.get(key, 0)
                    budget = self.WATCH_QUEUE_BYTES if op == 0x41 else self.MAX_QUEUE_BYTES
                    while queue and size+len(payload) > budget:
                        removed = queue.popleft()
                        size -= len(removed)
                        self.dropped_bytes[key] = self.dropped_bytes.get(key, 0)+len(removed)-6
                    queue.append(payload)
                    self._sizes[key] = size+len(payload)
                    self._condition.notify_all()

    def stats(self):
        with self._condition:
            return {'event_gaps': self.event_gaps,
                    'rtt_dropped_bytes': {ch: self.dropped_bytes.get((0x40, ch), 0) for ch in range(8)},
                    'watch_dropped_bytes': self.dropped_bytes.get((0x41, 255), 0)}

    def drain(self, op, channel, *, max_bytes=None):
        with self._condition:
            self._check()
            key = (op, channel)
            if max_bytes is None:
                frames = list(self._queues.pop(key, ()))
                self._sizes.pop(key, None)
                return frames
            if max_bytes <= 0:
                raise ValueError('Drain budget must be positive')
            queue = self._queues.get(key)
            frames = []
            used = 0
            while queue and (not frames or used+len(queue[0]) <= max_bytes):
                frame = queue.popleft()
                frames.append(frame)
                used += len(frame)
            if queue:
                self._sizes[key] -= used
            else:
                self._queues.pop(key, None)
                self._sizes.pop(key, None)
            return frames

    def read_memory(self, address, size):
        if not 0 <= address <= 0xffffffff or size < 0 or address+size > 0x100000000:
            raise ValueError('Invalid memory range')
        result = bytearray()
        for offset in range(0, size, 128):
            n = min(128, size-offset)
            data = self.request(0x11, struct.pack('<IH', address+offset, n))
            if len(data) != n:
                self.fail('Incomplete memory response')
                raise self._error
            result.extend(data)
        return bytes(result)

    def write_memory(self, address, data):
        if not 0 <= address <= 0xffffffff or address+len(data) > 0x100000000:
            raise ValueError('Invalid memory range')
        for offset in range(0, len(data), 128):
            self.request(0x12, struct.pack('<I', address+offset)+data[offset:offset+128])

    def close(self):
        with self._commands:
            if self._error is None:
                self.request(3)
            self.ready = False
