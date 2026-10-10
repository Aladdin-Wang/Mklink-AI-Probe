"""串口通信封装 — 通用 UART 读写，非 MKLink 调试探针。"""

from __future__ import annotations

import threading
from typing import Optional

import serial
import serial.tools.list_ports

from mklink.local_resources import _PortLock
from mklink.usb_interfaces import (
    MKLINK_COMMAND_INTERFACE,
    canonical_serial_port,
    require_uart_port,
    is_mklink_usb_port,
    usb_interface_number,
    usb_interface_numbers,
)


# ---------------------------------------------------------------------------
# MKLink port detection
# ---------------------------------------------------------------------------
def is_mklink_port(port: str) -> bool:
    """判断指定 COM 口是否为 MKLink 命令接口。"""
    ports = list(serial.tools.list_ports.comports())
    for info, number in zip(ports, usb_interface_numbers(ports)):
        if canonical_serial_port(info.device) != canonical_serial_port(port):
            continue
        return (
            is_mklink_usb_port(info)
            and number == MKLINK_COMMAND_INTERFACE
        )
    return False


def list_uart_ports() -> list[dict]:
    """列出通用串口，排除 MKLink 命令接口和身份不明的接口。"""
    results: list[dict] = []
    ports = list(serial.tools.list_ports.comports())
    for info, number in zip(ports, usb_interface_numbers(ports)):
        is_command = (
            is_mklink_usb_port(info)
            and number in (None, MKLINK_COMMAND_INTERFACE)
        )
        if not is_command:
            results.append({
                "device": info.device,
                "description": info.description or "",
                "manufacturer": getattr(info, "manufacturer", None) or "",
                "vid": info.vid,
                "pid": info.pid,
                "is_mklink": False,
            })
    return results


# ---------------------------------------------------------------------------
# SerialPort
# ---------------------------------------------------------------------------
class SerialPort:
    """通用串口通信类，支持跨进程端口锁与线程安全读写。"""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        databits: int = 8,
        stopbits: int = 1,
        parity: str = "N",
        timeout: float = 0.05,
    ):
        self._port = canonical_serial_port(port)
        self._baudrate = baudrate
        self._databits = databits
        self._stopbits = stopbits
        self._parity = parity
        self._timeout = timeout

        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._port_lock = _PortLock(port)

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def open(self) -> bool:
        """获取端口锁并打开串口，成功返回 True。"""
        if self.is_open:
            return True
        require_uart_port(self._port)
        if not self._port_lock.acquire():
            return False
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                bytesize=self._databits,
                stopbits=self._stopbits,
                parity=self._parity,
                timeout=self._timeout,
                write_timeout=1.0,
            )
            require_uart_port(self._port)
            return True
        except Exception as error:
            self.close()
            if isinstance(error, serial.SerialException):
                return False
            raise

    def close(self) -> None:
        """关闭串口并释放端口锁。"""
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
        self._port_lock.release()

    def write(self, data: bytes) -> None:
        """线程安全写入。"""
        with self._lock:
            if not self._serial or not self._serial.is_open:
                raise OSError("Serial port is closed")
            if self._serial.write(data) != len(data):
                raise OSError("Serial write was incomplete; data was not retried")

    def read_available(self) -> bytes:
        """非阻塞读取所有可用字节。"""
        with self._lock:
            if not self._serial or not self._serial.is_open:
                raise OSError("Serial port is closed")
            waiting = self._serial.in_waiting
            if waiting > 0:
                return self._serial.read(waiting)
            return b""

    def __enter__(self) -> "SerialPort":
        if not self.open():
            raise OSError(f"Serial port {self._port} is busy or unavailable")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
