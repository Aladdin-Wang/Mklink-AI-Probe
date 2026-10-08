"""Modbus RTU 客户端 — pymodbus ModbusSerialClient 封装。"""

from __future__ import annotations

from collections.abc import Callable

from pymodbus.client import ModbusSerialClient
from pymodbus import FramerType, ModbusException

from mklink.local_resources import _PortLock
from mklink.usb_interfaces import canonical_serial_port, require_uart_port


class ModbusError(Exception):
    """Modbus 操作失败。"""


class ModbusSlaveError(ModbusError):
    """从站返回异常响应。"""

    def __init__(self, slave: int, fc: int, response):
        self.slave = slave
        self.fc = fc
        self.response = response
        super().__init__(f"从站 {slave} 返回异常 (FC={fc:#04x}): {response}")


class _ExplicitSerialClient(ModbusSerialClient):
    """pymodbus requests may check connectivity, but must never reopen a COM port."""

    def open_port(self) -> bool:
        if not super().connect():
            return False
        self.socket.write_timeout = self.comm_params.timeout_connect
        return True

    def connect(self) -> bool:
        return bool(self.socket and self.socket.is_open)


class ModbusClient:
    """Modbus RTU 客户端，封装 pymodbus 同步串口通信。"""

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: int = 1,
        timeout: float = 1.0,
        retries: int = 3,
        handle_local_echo: bool = False,
        trace_packet: Callable[[bool, bytes], bytes] | None = None,
        trace_connect: Callable[[bool], None] | None = None,
    ):
        port = canonical_serial_port(port)
        self._client = _ExplicitSerialClient(
            port=port,
            framer=FramerType.RTU,
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            timeout=timeout,
            retries=retries,
            handle_local_echo=handle_local_echo,
            trace_packet=trace_packet,
            trace_connect=trace_connect,
        )
        self._port = port
        self._lock = _PortLock(port)
        self._is_open = False

    def open(self) -> bool:
        """打开串口连接。"""
        if self._is_open:
            if self._client.connect():
                return True
            self.close()
        require_uart_port(self._port)
        if not self._lock.acquire():
            print(f"[FAIL] Modbus 串口 {self._port} 已被 mklink 其他进程占用；不要并发访问同一串口")
            return False
        try:
            ok = self._client.open_port()
            if not ok:
                try:
                    self._client.close()
                finally:
                    self._lock.release()
                return False
            require_uart_port(self._port)
            self._is_open = True
            return True
        except Exception as e:
            try:
                self._client.close()
            finally:
                self._lock.release()
            if isinstance(e, ValueError):
                raise
            print(f"[FAIL] 无法打开端口 {self._port}: {e}")
            return False

    def close(self) -> None:
        """关闭串口连接。"""
        if not self._is_open:
            self._lock.release()
            return
        try:
            self._client.close()
        finally:
            self._is_open = False
            self._lock.release()

    def _check(self, result, slave: int, fc: int):
        """检查 pymodbus 响应，异常时抛出 ModbusSlaveError。"""
        if isinstance(result, ModbusException):
            raise ModbusError(f"pymodbus 库异常: {result}")
        if result.isError():
            raise ModbusSlaveError(slave, fc, result)
        return result

    # ---- FC01: Read Coils ----
    def read_coils(self, address: int, count: int, slave: int) -> list[bool]:
        rr = self._check(
            self._client.read_coils(address, count=count, device_id=slave),
            slave, 0x01,
        )
        return rr.bits[:count]

    # ---- FC02: Read Discrete Inputs ----
    def read_discrete_inputs(self, address: int, count: int, slave: int) -> list[bool]:
        rr = self._check(
            self._client.read_discrete_inputs(address, count=count, device_id=slave),
            slave, 0x02,
        )
        return rr.bits[:count]

    # ---- FC03: Read Holding Registers ----
    def read_holding_registers(self, address: int, count: int, slave: int) -> list[int]:
        rr = self._check(
            self._client.read_holding_registers(address, count=count, device_id=slave),
            slave, 0x03,
        )
        return rr.registers

    # ---- FC04: Read Input Registers ----
    def read_input_registers(self, address: int, count: int, slave: int) -> list[int]:
        rr = self._check(
            self._client.read_input_registers(address, count=count, device_id=slave),
            slave, 0x04,
        )
        return rr.registers

    # ---- FC05: Write Single Coil ----
    def write_coil(self, address: int, value: bool, slave: int) -> None:
        self._check(
            self._client.write_coil(address, value, device_id=slave),
            slave, 0x05,
        )

    # ---- FC06: Write Single Register ----
    def write_register(self, address: int, value: int, slave: int) -> None:
        self._check(
            self._client.write_register(address, value, device_id=slave),
            slave, 0x06,
        )

    # ---- FC07: Read Exception Status ----
    def read_exception_status(self, slave: int) -> int:
        rr = self._check(
            self._client.read_exception_status(device_id=slave),
            slave, 0x07,
        )
        return rr.status

    # ---- FC15: Write Multiple Coils ----
    def write_coils(self, address: int, values: list[bool], slave: int) -> None:
        self._check(
            self._client.write_coils(address, values, device_id=slave),
            slave, 0x0F,
        )

    # ---- FC16: Write Multiple Registers ----
    def write_registers(self, address: int, values: list[int], slave: int) -> None:
        self._check(
            self._client.write_registers(address, values, device_id=slave),
            slave, 0x10,
        )

    # ---- FC22: Mask Write Register ----
    def mask_write_register(
        self, address: int, and_mask: int, or_mask: int, slave: int
    ) -> None:
        self._check(
            self._client.mask_write_register(
                address=address, and_mask=and_mask, or_mask=or_mask, device_id=slave
            ),
            slave, 0x16,
        )

    # ---- FC23: Read/Write Multiple Registers ----
    def read_write_registers(
        self,
        read_address: int,
        read_count: int,
        write_address: int,
        write_values: list[int],
        slave: int,
    ) -> list[int]:
        rr = self._check(
            self._client.readwrite_registers(
                read_address=read_address,
                read_count=read_count,
                write_address=write_address,
                values=write_values,
                device_id=slave,
            ),
            slave, 0x17,
        )
        return rr.registers

    # ---- 数据类型转换 ----
    def convert_from_registers(self, registers: list[int], data_type) -> int | float:
        """将 16 位寄存器列表转换为指定类型值。"""
        return self._client.convert_from_registers(registers, data_type=data_type)

    def convert_to_registers(self, value: int | float, data_type) -> list[int]:
        """将指定类型值转换为 16 位寄存器列表。"""
        return self._client.convert_to_registers(value, data_type=data_type)

    @property
    def DATATYPE(self):
        """pymodbus DATATYPE 枚举，用于类型转换。"""
        return self._client.DATATYPE

    @property
    def raw_client(self) -> ModbusSerialClient:
        """直接访问底层 pymodbus 客户端（用于诊断等高级操作）。"""
        return self._client

    def probe_slave(self, slave: int, register: int = 0) -> dict:
        """One read-only probe; the caller must serialize access to this client."""
        from pymodbus.exceptions import ModbusIOException
        from mklink.modbus._session import validate_slave, validate_transaction
        validate_slave(slave)
        validate_transaction(3, register, quantity=1)
        raw = self._client
        if not raw.connect():
            raise ModbusError('Modbus port is closed; reconnect explicitly before scanning')
        # pymodbus copies retries into its transaction object at construction.
        # Its serial receive loop and socket also have separate timeout values.
        settings = [(raw.comm_params, 'timeout_connect', .15), (raw, 'retries', 0),
                    (raw.transaction, 'retries', 0), (raw.socket, 'timeout', .15),
                    (raw.socket, 'write_timeout', .15)]
        previous = [(obj, key, getattr(obj, key)) for obj, key, _ in settings]
        # Absent addresses during discovery must not consume the connected
        # slave's failure budget used by subsequent GUI transactions.
        previous.append((raw.transaction, 'count_until_disconnect', raw.transaction.count_until_disconnect))
        try:
            for obj, key, value in settings:
                setattr(obj, key, value)
            try:
                self.read_holding_registers(register, 1, slave)
            except ModbusSlaveError as exc:
                return {'slave': slave, 'responded': True,
                        'exception_code': exc.response.exception_code}
            except ModbusIOException as exc:
                return {'slave': slave, 'responded': False, 'error': str(exc)}
            return {'slave': slave, 'responded': True}
        finally:
            restore_error = None
            for obj, key, value in reversed(previous):
                try:
                    setattr(obj, key, value)
                except Exception as exc:
                    if restore_error is None:
                        restore_error = exc
            if restore_error is not None:
                # Stop using a port whose timing could not be restored. Keep
                # the outer client's ownership lock until explicit close/stop.
                try:
                    raw.close()
                finally:
                    raise restore_error
