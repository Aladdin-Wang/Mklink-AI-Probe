"""USB composite-interface metadata shared by MKLink transports."""

from __future__ import annotations

import re
from typing import Any


MKLINK_USB_VID_PID = (0x0D28, 0x0202)
MKLINK_COMMAND_INTERFACE = 0x04


def usb_interface_number(info: Any) -> int | None:
    """Return a USB interface number from pyserial port metadata."""
    text = " ".join(
        str(getattr(info, key, "") or "")
        for key in ("hwid", "location", "interface")
    ).strip()
    match = re.search(r"(?i)MI[_-]?([0-9a-f]{2})", text)
    if match is not None:
        return int(match.group(1), 16)
    match = re.search(r"(?i)(?:x\.|\.)(\d+)$", text)
    return int(match.group(1), 10) if match else None


def is_mklink_usb_port(info: Any) -> bool:
    return (
        getattr(info, "vid", None),
        getattr(info, "pid", None),
    ) == MKLINK_USB_VID_PID


def canonical_serial_port(port: str) -> str:
    """Normalize Windows COM spellings before identity checks and locking."""
    if not isinstance(port, str) or not port.strip() or '\x00' in port:
        raise ValueError('Serial port is required')
    port = port.strip()
    candidate = port[4:] if port.startswith('\\\\.\\') else port
    match = re.fullmatch(r'COM(\d+)', candidate, re.IGNORECASE)
    return f'COM{int(match.group(1))}' if match else port


def require_uart_port(port: str) -> str:
    """Reject command/unknown MKLink interfaces without opening or probing them."""
    from serial.tools import list_ports
    port = canonical_serial_port(port)
    for info in list_ports.comports():
        if canonical_serial_port(info.device) != port or not is_mklink_usb_port(info):
            continue
        interface = usb_interface_number(info)
        if interface is None or interface == MKLINK_COMMAND_INTERFACE:
            raise ValueError(f'{port} is a MKLink command or unidentified interface; select a UART port')
    return port
