"""Serialized Modbus I/O primitives shared by Web dashboards.

One :class:`ModbusWorker` owns one client.  Callers may submit requests from
different HTTP/polling threads, but the worker is the only thread that touches
the serial client.
"""

from __future__ import annotations

from concurrent.futures import CancelledError, Future
from dataclasses import dataclass
import queue
import threading
from typing import Any, Callable

from mklink.modbus._format import RegisterSpec, registers_to_values
from mklink.modbus._poller import _group_consecutive


READ_LIMITS = {1: 2000, 2: 2000, 3: 125, 4: 125}
WRITE_LIMITS = {5: 1, 6: 1, 15: 1968, 16: 123}
SUPPORTED_FUNCTIONS = frozenset(READ_LIMITS | WRITE_LIMITS)


def validate_slave(slave: int) -> int:
    if type(slave) is not int or not 1 <= slave <= 247:
        raise ValueError('Slave address must be in the range 1..247')
    return slave


@dataclass(slots=True)
class _Task:
    operation: Callable[[], Any]
    future: Future


def validate_transaction(
    fc: int,
    start: int,
    *,
    quantity: int | None = None,
    values: list[int | bool] | None = None,
) -> tuple[int, int, int | None, list[int | bool] | None]:
    """Validate and normalize a public Modbus transaction request."""
    if isinstance(fc, bool) or fc not in SUPPORTED_FUNCTIONS:
        raise ValueError("Function code must be one of 1, 2, 3, 4, 5, 6, 15, 16")
    if isinstance(start, bool) or not 0 <= int(start) <= 0xFFFF:
        raise ValueError("Start address must be in the range 0..65535")
    start = int(start)

    if fc in READ_LIMITS:
        if quantity is None or isinstance(quantity, bool):
            raise ValueError("Read operations require a quantity")
        quantity = int(quantity)
        if not 1 <= quantity <= READ_LIMITS[fc]:
            raise ValueError(f"FC{fc:02d} quantity must be in the range 1..{READ_LIMITS[fc]}")
        if start + quantity > 0x10000:
            raise ValueError("Requested address range exceeds 65535")
        return fc, start, quantity, None

    normalized = list(values or [])
    limit = WRITE_LIMITS[fc]
    if not normalized:
        raise ValueError("Write operations require at least one value")
    if fc in (5, 6) and len(normalized) != 1:
        raise ValueError(f"FC{fc:02d} requires exactly one value")
    if len(normalized) > limit:
        raise ValueError(f"FC{fc:02d} accepts at most {limit} values")
    if start + len(normalized) > 0x10000:
        raise ValueError("Requested address range exceeds 65535")
    if fc in (5, 15):
        bits: list[bool] = []
        for value in normalized:
            if not isinstance(value, bool) and value not in (0, 1):
                raise ValueError("Coil values must be true/false or 0/1")
            bits.append(bool(value))
        normalized = bits
    else:
        ints: list[int] = []
        for value in normalized:
            if isinstance(value, bool) or not 0 <= int(value) <= 0xFFFF:
                raise ValueError("Register values must be in the range 0..65535")
            ints.append(int(value))
        normalized = ints
    return fc, start, None, normalized


def modbus_crc16(payload: bytes) -> int:
    """Return the Modbus RTU CRC16 for *payload*."""
    crc = 0xFFFF
    for byte in payload:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def frame_crc_ok(frame: bytes) -> bool | None:
    """Return CRC validity for a complete RTU frame, or None when too short."""
    if len(frame) < 4:
        return None
    expected = frame[-2] | (frame[-1] << 8)
    return modbus_crc16(frame[:-2]) == expected


def rtu_frame_length(sending: bool, frame: bytes) -> int | None:
    """Return the expected length of a supported RTU request/response."""
    if len(frame) < 2:
        return None
    fc = frame[1]
    if fc & 0x80:
        return 5
    if sending:
        if fc in (1, 2, 3, 4, 5, 6):
            return 8
        if fc in (15, 16) and len(frame) >= 7:
            return 9 + frame[6]
        return None
    if fc in (1, 2, 3, 4) and len(frame) >= 3:
        return 5 + frame[2]
    if fc in (5, 6, 15, 16):
        return 8
    return None


class ModbusWorker:
    """Serialize every operation for one connected Modbus client."""

    def __init__(self, client, slave: int):
        self._client = client
        self._slave = slave
        self._queue: queue.Queue[_Task | None] = queue.Queue(maxsize=64)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._stopping = False

    @property
    def slave(self) -> int:
        return self._slave

    @property
    def worker_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._stopping:
                raise RuntimeError("Previous Modbus worker must finish stopping first")
            if self._running.is_set():
                return
            if self.worker_alive:
                raise RuntimeError("Previous Modbus worker is still active")
            self._running.set()
            self._thread = threading.Thread(
                target=self._run, name="mklink-modbus-io", daemon=True,
            )
            try:
                self._thread.start()
            except Exception:
                self._running.clear()
                self._thread = None
                raise

    def request_stop(self) -> None:
        """Reject new submissions and cancel queued work, without joining I/O."""
        with self._lifecycle_lock:
            self._stopping = True
            self._running.clear()
            while True:
                try:
                    task = self._queue.get_nowait()
                except queue.Empty:
                    break
                if task is not None:
                    task.future.cancel()
            self._queue.put_nowait(None)

    def stop(self, timeout: float = 3.0) -> None:
        self.request_stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0, timeout))
        if self.worker_alive:
            raise TimeoutError("Modbus I/O worker is still active; ownership retained")
        with self._lifecycle_lock:
            self._thread = None
            self._stopping = False
            # A never-started/already-exited worker cannot consume the wakeup.
            while not self._queue.empty():
                self._queue.get_nowait()

    def _submit(self, operation: Callable[[], Any], timeout: float = 10.0) -> Any:
        task = _Task(operation=operation, future=Future())
        with self._lifecycle_lock:
            if not self._running.is_set():
                raise RuntimeError("Modbus I/O worker is not running")
            try:
                self._queue.put_nowait(task)
            except queue.Full:
                raise RuntimeError("Modbus request queue is full; request was not submitted") from None
        try:
            return task.future.result(timeout=timeout)
        except CancelledError:
            raise RuntimeError("Modbus request cancelled before execution") from None
        except TimeoutError:
            if task.future.cancel():
                raise TimeoutError("Modbus request timed out in queue and was cancelled before execution") from None
            if task.future.done():
                return task.future.result()
            raise TimeoutError("Modbus request is already executing; result unknown, do not retry") from None

    def execute(
        self,
        fc: int,
        start: int,
        *,
        quantity: int | None = None,
        values: list[int | bool] | None = None,
        slave: int | None = None,
    ) -> list[int | bool]:
        fc, start, quantity, values = validate_transaction(
            fc, start, quantity=quantity, values=values
        )
        target = validate_slave(self._slave if slave is None else slave)

        def operation() -> list[int | bool]:
            if fc == 1:
                return self._client.read_coils(start, quantity, target)
            if fc == 2:
                return self._client.read_discrete_inputs(start, quantity, target)
            if fc == 3:
                return self._client.read_holding_registers(start, quantity, target)
            if fc == 4:
                return self._client.read_input_registers(start, quantity, target)
            if fc == 5:
                self._client.write_coil(start, values[0], target)
            elif fc == 6:
                self._client.write_register(start, values[0], target)
            elif fc == 15:
                self._client.write_coils(start, values, target)
            else:
                self._client.write_registers(start, values, target)
            return list(values)

        return list(self._submit(operation))

    def submit_read(self, specs: list[RegisterSpec]) -> dict[int, int | float]:
        return dict(self._submit(lambda: self._batch_read(specs)))

    def probe_slave(self, slave: int, register: int = 0) -> dict:
        validate_slave(slave)
        validate_transaction(3, register, quantity=1)
        return self._submit(lambda: self._client.probe_slave(slave, register))

    def submit_write(self, addr: int, value: int) -> None:
        self.execute(6, addr, values=[value])

    def submit_debug_read(self, fc: int, start: int, quantity: int) -> list[int | bool]:
        return self.execute(fc, start, quantity=quantity)

    def submit_debug_write(self, fc: int, start: int, values: list[int | bool]) -> None:
        self.execute(fc, start, values=values)

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                return
            with self._lifecycle_lock:
                if not self._running.is_set():
                    task.future.cancel()
                if not task.future.set_running_or_notify_cancel():
                    continue
            try:
                result = task.operation()
            except BaseException as error:
                task.future.set_exception(error)
            else:
                task.future.set_result(result)

    def _batch_read(self, specs: list[RegisterSpec]) -> dict[int, int | float]:
        result: dict[int, int | float] = {}
        for group in _group_consecutive(specs):
            start = group[0].addr
            count = group[-1].addr + group[-1].reg_count - start
            read = (self._client.read_input_registers if group[0].register_type == 'input'
                    else self._client.read_holding_registers)
            registers = read(start, count, self._slave)
            if len(registers) != count:
                raise OSError("Modbus read returned an incomplete register group")
            for spec in group:
                offset = spec.addr - start
                result[spec.addr] = registers_to_values(
                    registers[offset:offset + spec.reg_count], spec.type,
                )[0]
        return result
