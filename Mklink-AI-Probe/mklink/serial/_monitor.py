"""多串口监控线程管理器。"""

from __future__ import annotations

import heapq
import io
import queue
import threading
import time
from dataclasses import dataclass
from contextlib import contextmanager
from typing import Callable

from mklink.serial._autoreply import AutoReplyEngine
from mklink.serial._frame import FrameParser, ParsedFrame
from mklink.serial._port import SerialPort
from mklink.usb_interfaces import canonical_serial_port, require_uart_port


class _ProtocolQueue(queue.Queue):
    """Bound protocol RX without blocking the sole reader under admission."""
    CHUNK_BYTES = 4096
    MAX_CHUNKS = 128

    def __init__(self, *, raw_trace=False):
        self.raw_trace = raw_trace
        super().__init__(maxsize=self.MAX_CHUNKS)
        self.error = None

    def fail(self, error):
        if self.error is None:
            self.error = error

    def check(self):
        if self.error is not None:
            raise self.error

    def feed(self, data):
        self.check()
        try:
            for offset in range(0, len(data), self.CHUNK_BYTES):
                self.put_nowait(data[offset:offset + self.CHUNK_BYTES])
        except queue.Full:
            self.fail(BufferError('Serial protocol receive buffer overflow; transfer aborted'))
            self.check()


@dataclass
class SerialEvent:
    timestamp: float
    port: str
    direction: str
    raw: bytes
    parsed: ParsedFrame | None = None


class SerialMonitor:
    def __init__(
        self,
        ports: list[dict],
        profile: dict | None = None,
        auto_reply_rules: list[dict] | None = None,
        event_callback: Callable[[SerialEvent], None] | None = None,
        chunk_callback: Callable[[str, str, bytes, float, float], None] | None = None,
        protocol_callback: Callable[[str, str, bytes, float], None] | None = None,
    ):
        self._port_configs = [dict(cfg, port=canonical_serial_port(cfg["port"])) for cfg in ports]
        ports = self._port_configs
        if not ports or len(ports) > 16 or len({cfg["port"] for cfg in ports}) != len(ports):
            raise ValueError("Select 1..16 distinct UART ports")
        self._profile = profile
        self._auto_reply_rules = auto_reply_rules
        self._event_callback = event_callback
        self._chunk_callback = chunk_callback
        self._protocol_callback = protocol_callback

        self._stop_event = threading.Event()
        self._running = False
        self._threads: list[threading.Thread] = []
        self._serial_ports: dict[str, SerialPort] = {}
        self._port_statuses: dict[str, str] = {cfg["port"]: "closed" for cfg in ports}
        self._observation_times: dict[str, float] = {}
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._stop_timeout = 3.0
        self._protocol_lock = threading.Lock()
        self._protocol_queues: dict[str, _ProtocolQueue] = {}
        # Completed protocols hand unread terminal bytes back to the normal
        # reader here.  Only the reader thread emits them, preserving parser,
        # event and callback ordering without a second serial consumer.
        self._protocol_handoffs: dict[str, bytearray] = {}
        self._pending_replies: dict[str, list[tuple[float, int, bytes]]] = {}
        self._send_sequences = {}
        self._reply_sequence = 0
        self._reply_generation = {cfg['port']: 0 for cfg in ports}

        self._auto_reply_engine: AutoReplyEngine | None = None
        if auto_reply_rules:
            self._auto_reply_engine = AutoReplyEngine()
            self._auto_reply_engine.load_rules(auto_reply_rules)

        self._parsers: dict[str, FrameParser] = {}
        if profile:
            for cfg in ports:
                self._parsers[cfg["port"]] = FrameParser(profile, max_buffer_bytes=1024 * 1024)

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.is_running():
                return
            if self._running:
                self.stop()
            if self.worker_alive:
                raise RuntimeError('Previous serial reader is still active')
            with self._protocol_lock:
                if self._protocol_queues:
                    raise RuntimeError('Previous serial protocol is still active')
                self._pending_replies.clear()
                self._send_sequences.clear()
                self._protocol_handoffs.clear()
                for port in self._reply_generation:
                    self._reply_generation[port] += 1
                for parser in self._parsers.values():
                    parser.reset()
            self._threads.clear()
            self._stop_event.clear()
            with self._lock:
                self._observation_times = {cfg['port']: time.monotonic() for cfg in self._port_configs}
            # Validate every selection before opening the first port. No retry or
            # automatic reattachment: COM numbers can be reused by another device.
            for cfg in self._port_configs:
                require_uart_port(cfg['port'])
            try:
                for cfg in self._port_configs:
                    name = cfg['port']
                    sp = SerialPort(port=name, baudrate=cfg.get('baudrate', 115200),
                                    databits=cfg.get('databits', 8), stopbits=cfg.get('stopbits', 1),
                                    parity=cfg.get('parity', 'N'))
                    if not sp.open():
                        self._port_statuses[name] = 'error: port is busy or unavailable'
                        raise OSError(f'Serial port {name} is busy or unavailable')
                    self._serial_ports[name] = sp
                    self._port_statuses[name] = 'open'
                self._running = True
                for cfg in self._port_configs:
                    thread = threading.Thread(target=self._reader_loop, args=(cfg,), daemon=True,
                                              name=f"serial-reader-{cfg['port']}")
                    thread.start()
                    self._threads.append(thread)
            except Exception:
                self.stop()
                raise

    @property
    def worker_alive(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop_event.set()
            deadline = time.monotonic() + self._stop_timeout
            for thread in self._threads:
                if thread is not threading.current_thread():
                    thread.join(timeout=max(0, deadline - time.monotonic()))
            if self.worker_alive:
                raise TimeoutError('Serial reader is still active; port ownership retained')
            self._threads.clear()
            with self._protocol_lock:
                self._pending_replies.clear()
            with self._lock:
                for name, sp in self._serial_ports.items():
                    sp.close()
                    self._port_statuses[name] = 'closed'
                self._serial_ports.clear()
            self._running = False

    def _write_ordinary_locked(self, port: str, data: bytes) -> bool:
        # Caller holds the protocol admission lock through the physical write.
        if self._stop_event.is_set() or port in self._protocol_queues:
            return False
        with self._lock:
            sp = self._serial_ports.get(port)
            if sp is None or not sp.is_open:
                return False
            try:
                sp.write(data)
            except Exception:
                return False
        return True

    def _record_sent(self, port: str, data: bytes) -> None:
        timestamp = time.time()
        self._emit_chunk(port, 'TX', data, timestamp, time.monotonic())
        self._emit_event(SerialEvent(timestamp=timestamp, port=port, direction='TX', raw=data))

    def send(self, port: str, data: bytes) -> bool:
        port = canonical_serial_port(port)
        with self._protocol_lock:
            if not self._write_ordinary_locked(port, data):
                return False
        self._record_sent(port, data)
        return True

    def start_sequence(self, port, commands, interval_ms=1000, repeat=1):
        from mklink.serial._sequence import SendSequence
        sequence = SendSequence(commands, interval_ms, repeat)
        port = canonical_serial_port(port)
        with self._protocol_lock:
            if self._stop_event.is_set() or port in self._protocol_queues:
                raise RuntimeError('Serial port is stopping or transferring a protocol')
            with self._lock:
                sp = self._serial_ports.get(port)
                if sp is None or not sp.is_open:
                    raise RuntimeError('Serial port is not open')
            previous = self._send_sequences.get(port)
            if previous is not None and previous.active:
                raise RuntimeError('Send sequence is already active on this port')
            self._send_sequences[port] = sequence
            return sequence.status()

    def stop_sequence(self, port):
        port = canonical_serial_port(port)
        with self._protocol_lock:
            sequence = self._send_sequences.get(port)
            if sequence is None:
                return {'state': 'idle', 'active': False}
            sequence.cancel('Stopped by client')
            return sequence.status()

    def sequence_status(self):
        with self._protocol_lock:
            return {port: sequence.status() for port, sequence in self._send_sequences.items()}

    def _advance_sequence(self, port):
        with self._protocol_lock:
            sequence = self._send_sequences.get(port)
            if sequence is None or not sequence.active:
                return
            if self._stop_event.is_set() or port in self._protocol_queues:
                sequence.cancel('Serial stopped or protocol started')
                return
            if sequence.due > time.monotonic():
                return
            data = sequence.commands[sequence.sent % len(sequence.commands)]
            if not self._write_ordinary_locked(port, data):
                sequence.cancel('Write failed; result may be partial, no retry', failed=True)
                raise OSError(sequence.error)
            sequence.sent += 1
        # As for auto replies, raw history callbacks run outside protocol admission.
        try:
            self._record_sent(port, data)
        except Exception as error:
            with self._protocol_lock:
                sequence.cancel(str(error) or type(error).__name__, failed=True)
            raise
        with self._protocol_lock:
            sequence.finish_send()

    @contextmanager
    def _protocol_session(self, port, *, cancel_event=None, cancel_error=RuntimeError, tail=None, raw_trace=False):
        """Reserve one monitored port; the existing reader remains its sole consumer."""
        port = canonical_serial_port(port)
        receive_queue = _ProtocolQueue(raw_trace=raw_trace)
        with self._protocol_lock:
            if self._stop_event.is_set():
                raise RuntimeError("Serial monitor is stopping")
            if port in self._protocol_queues:
                raise RuntimeError(f"serial port {port} already has an active transfer")
            with self._lock:
                serial_port = self._serial_ports.get(port)
                if serial_port is None or not serial_port.is_open:
                    raise RuntimeError(f"serial port {port} is not open")
            self._pending_replies.pop(port, None)
            sequence = self._send_sequences.get(port)
            if sequence is not None:
                sequence.cancel('Protocol transfer started')
            self._reply_generation[port] += 1
            self._protocol_queues[port] = receive_queue

        cancellation = cancel_event or threading.Event()

        def read_protocol(timeout: float) -> bytes:
            deadline = time.monotonic() + timeout
            while True:
                receive_queue.check()
                if cancellation.is_set() or self._stop_event.is_set():
                    raise cancel_error("Serial protocol cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return b""
                try:
                    data = receive_queue.get(timeout=min(remaining, 0.1))
                    receive_queue.check()
                    return data
                except queue.Empty:
                    continue

        def write_protocol(payload: bytes) -> None:
            receive_queue.check()
            if cancellation.is_set() or self._stop_event.is_set():
                raise cancel_error("Serial protocol cancelled")
            with self._lock:
                current = self._serial_ports.get(port)
                if current is not serial_port or not current.is_open:
                    raise RuntimeError(f"serial port {port} closed during protocol transfer")
                current.write(payload)
            if raw_trace:
                self._record_sent(port, payload)
            else:
                self._emit_protocol_chunk(port, "TX", payload, time.time())

        completed = False
        try:
            yield read_protocol, write_protocol
            receive_queue.check()
            completed = True
        finally:
            with self._protocol_lock:
                if self._protocol_queues.get(port) is receive_queue:
                    try:
                        pending = bytearray()
                        if completed and receive_queue.error is None and not raw_trace:
                            if tail is not None:
                                pending.extend(tail())
                            # Reader queue writes also hold _protocol_lock, so once
                            # this lock is acquired no late put can race the drain.
                            while True:
                                try:
                                    pending.extend(receive_queue.get_nowait())
                                except queue.Empty:
                                    break
                            if pending:
                                self._protocol_handoffs.setdefault(
                                    port, bytearray(),
                                ).extend(pending)
                    finally:
                        self._protocol_queues.pop(port, None)
            receive_queue.check()

    def send_ymodem(self, port, data, filename, *, cancel_event=None, progress_callback=None):
        from mklink.serial._ymodem import YModemCancelled, YModemSender
        sender = None
        def tail():
            pending = getattr(sender, 'take_pending_rx', None)
            return pending() if callable(pending) else b''
        with self._protocol_session(port, cancel_event=cancel_event,
                                    cancel_error=YModemCancelled, tail=tail) as (read, write):
            sender = YModemSender(read, write, cancel_event=cancel_event,
                                 progress_callback=progress_callback)
            sender.send(io.BytesIO(data), filename, len(data))

    def exchange(self, port, data, timeout=.1):
        """Write once and collect raw RX in a bounded exclusive protocol window.

        RX starts at admission and may include unsolicited or already-buffered
        device bytes; no protocol-level request/response correlation is inferred.
        """
        import math
        if not isinstance(data, bytes) or len(data) > 4096:
            raise ValueError('Exchange data must contain at most 4096 bytes')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 <= timeout <= 5:
            raise ValueError('Exchange timeout must be finite and in 0..5 seconds')
        result = bytearray()
        with self._protocol_session(port, raw_trace=True) as (read, write):
            if data:
                write(data)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                chunk = read(max(0, deadline - time.monotonic()))
                if len(result) + len(chunk) > 65536:
                    raise BufferError('Serial exchange response exceeds 64 KiB; result incomplete')
                result.extend(chunk)
        return bytes(result)

    def send_all(self, data: bytes) -> dict:
        results = {}
        for cfg in self._port_configs:
            port = cfg['port']
            try:
                ok = self.send(port, data)
                results[port] = {'ok': ok, **({'bytes': len(data)} if ok else {
                    'error': 'Write refused or failed; result may be partial, no retry'})}
            except Exception as error:
                results[port] = {'ok': False, 'error': f'{error}; result may already be sent, no retry'}
        return {'ok': all(item['ok'] for item in results.values()), 'results': results}

    def is_running(self) -> bool:
        return self._running and self.worker_alive

    @property
    def port_status(self) -> dict[str, str]:
        with self._lock:
            return dict(self._port_statuses)

    @property
    def observation_times(self) -> dict[str, float]:
        """Completed reader iterations; consumers must not idle-flush past these."""
        with self._lock:
            return dict(self._observation_times)

    def __enter__(self) -> SerialMonitor:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()

    def _emit_event(self, evt: SerialEvent) -> None:
        if self._event_callback:
            try:
                self._event_callback(evt)
            except Exception:
                pass

    def _emit_chunk(
        self,
        port: str,
        direction: str,
        data: bytes,
        timestamp: float,
        monotonic_time: float,
    ) -> None:
        if not data or self._chunk_callback is None:
            return
        self._chunk_callback(port, direction, data, timestamp, monotonic_time)

    def _emit_protocol_chunk(
        self,
        port: str,
        direction: str,
        data: bytes,
        timestamp: float,
    ) -> None:
        if not data or self._protocol_callback is None:
            return
        try:
            self._protocol_callback(port, direction, data, timestamp)
        except Exception:
            pass

    def _reader_loop(self, cfg: dict) -> None:
        port_name = cfg['port']
        sp = self._serial_ports[port_name]
        parser = self._parsers.get(port_name)
        line_buffer = bytearray()
        observed_generation = self._reply_generation[port_name]
        reader_error = ''

        try:
            while not self._stop_event.is_set():
                self._drain_auto_replies(port_name)
                self._advance_sequence(port_name)
                data = sp.read_available()
                with self._protocol_lock:
                    generation = self._reply_generation[port_name]
                    protocol_queue = self._protocol_queues.get(port_name)
                    if protocol_queue is not None:
                        if data:
                            if not protocol_queue.raw_trace:
                                self._emit_protocol_chunk(port_name, "RX", data, time.time())
                            # Keep the put inside the lock.  Transfer
                            # teardown can now remove+drain atomically.
                            protocol_queue.feed(data)
                        handoff = b""
                    else:
                        handoff = bytes(
                            self._protocol_handoffs.pop(port_name, b""),
                        )
                if generation != observed_generation:
                    line_buffer.clear()
                    if parser is not None:
                        parser.reset()
                    observed_generation = generation
                if protocol_queue is not None:
                    if data and protocol_queue.raw_trace:
                        # Raw GUI/history observation, without framing or auto replies.
                        self._emit_chunk(port_name, "RX", data, time.time(), time.monotonic())
                    if not data:
                        self._stop_event.wait(0.01)
                    if protocol_queue.raw_trace:
                        with self._lock:
                            self._observation_times[port_name] = time.monotonic()
                    continue
                if handoff:
                    # A protocol may start and finish between reader
                    # iterations, so the handoff itself is also a boundary.
                    line_buffer.clear()
                    self._process_rx_data(
                        port_name, handoff, parser, line_buffer, generation=generation,
                    )
                if data:
                    self._process_rx_data(
                        port_name, data, parser, line_buffer, generation=generation,
                    )
                elif not handoff:
                    if parser is not None:
                        self._process_rx_data(port_name, b'', parser, line_buffer, generation=generation)
                    self._stop_event.wait(0.01)
                with self._lock:
                    self._observation_times[port_name] = time.monotonic()

        except Exception as e:
            reader_error = str(e) or type(e).__name__
            with self._protocol_lock:
                protocol_queue = self._protocol_queues.get(port_name)
                if protocol_queue is not None:
                    protocol_queue.fail(RuntimeError(f'Serial reader failed: {reader_error}'))
            with self._lock:
                self._port_statuses[port_name] = f"error: {e}"
        finally:
            with self._protocol_lock:
                self._pending_replies.pop(port_name, None)
                sequence = self._send_sequences.get(port_name)
                if sequence is not None:
                    sequence.cancel(reader_error or 'Serial stopped', failed=bool(reader_error))
            sp.close()
            with self._lock:
                self._serial_ports.pop(port_name, None)

                if not self._port_statuses[port_name].startswith('error:'):
                    self._port_statuses[port_name] = 'closed'

    def _process_rx_data(
        self,
        port_name: str,
        data: bytes,
        parser: FrameParser | None,
        line_buffer: bytearray,
        *, generation: int | None = None,
    ) -> None:
        """Publish one ordinary RX chunk from the sole reader thread."""
        monotonic_time = time.monotonic()
        self._emit_chunk(port_name, "RX", data, time.time(), monotonic_time)

        if parser:
            frames = parser.feed(data, monotonic_time=monotonic_time)
            for frame in frames:
                evt = SerialEvent(
                    timestamp=time.time(),
                    port=port_name,
                    direction="RX",
                    raw=frame.raw,
                    parsed=frame,
                )
                self._emit_event(evt)
                self._handle_auto_reply(port_name, frame.raw, generation)
            return

        line_buffer.extend(data)
        while b"\n" in line_buffer:
            idx = line_buffer.index(b"\n")
            line = bytes(line_buffer[: idx + 1])
            del line_buffer[: idx + 1]
            evt = SerialEvent(
                timestamp=time.time(),
                port=port_name,
                direction="RX",
                raw=line,
            )
            self._emit_event(evt)
            self._handle_auto_reply(port_name, line, generation)

        if len(line_buffer) > 4096:
            raw = bytes(line_buffer)
            evt = SerialEvent(
                timestamp=time.time(),
                port=port_name,
                direction="RX",
                raw=raw,
            )
            self._emit_event(evt)
            self._handle_auto_reply(port_name, raw, generation)
            line_buffer.clear()

    def _handle_auto_reply(self, port_name: str, data: bytes, generation: int | None = None) -> None:
        if not self._auto_reply_engine:
            return
        if generation is None:
            with self._protocol_lock:
                generation = self._reply_generation[port_name]
        replies = self._auto_reply_engine.check(data)
        if not replies:
            return
        with self._protocol_lock:
            if (self._stop_event.is_set() or port_name in self._protocol_queues
                    or generation != self._reply_generation[port_name]):
                return
            pending = self._pending_replies.setdefault(port_name, [])
            if len(pending) + len(replies) > 128:
                raise RuntimeError('Automatic reply queue exceeded 128 entries; port stopped')
            now = time.monotonic()
            for reply_data, delay in replies:
                self._reply_sequence += 1
                heapq.heappush(pending, (now + delay, self._reply_sequence, reply_data))

    def _drain_auto_replies(self, port_name: str) -> None:
        # Only the existing reader executes scheduled replies. No timers survive
        # its exit, and protocol admission cancels that port's pending replies.
        while True:
            with self._protocol_lock:
                if self._stop_event.is_set() or port_name in self._protocol_queues:
                    self._pending_replies.pop(port_name, None)
                    return
                pending = self._pending_replies.get(port_name)
                if not pending or pending[0][0] > time.monotonic():
                    return
                _, _, data = heapq.heappop(pending)
                if not self._write_ordinary_locked(port_name, data):
                    if self._stop_event.is_set():
                        self._pending_replies.pop(port_name, None)
                        return
                    raise OSError('Automatic reply write failed; data was not retried')
            # External callbacks must never run under protocol admission.
            self._record_sent(port_name, data)
