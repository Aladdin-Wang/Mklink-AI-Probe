"""USB composite-interface metadata shared by MKLink transports."""

from __future__ import annotations

import re
import sys
from typing import Any


MKLINK_USB_VID_PID = (0x0D28, 0x0202)
MKLINK_COMMAND_INTERFACE = 0x04


def usb_interface_number(info: Any) -> int | None:
    """Return a USB interface number from pyserial port metadata."""
    # A macOS location (e.g. 0-1.3.4.2.1) is physical topology, not an
    # interface. Never infer an interface from its final dotted component.
    if sys.platform == "darwin" and str(getattr(info, "device", "")).startswith("/dev/"):
        from mklink.usb_platform import macos_interface_number
        return macos_interface_number(info)
    hwid = str(getattr(info, "hwid", "") or "")
    match = re.search(r"(?i)(?:^|[\\&\s])MI[_-]?([0-9a-f]{2})(?:$|[\\&\s])", hwid)
    if match is not None:
        return int(match.group(1), 16)
    location = str(getattr(info, "location", "") or "")
    # pyserial Windows: 1-2:x.4; Linux: 1-2.3:1.4 (configuration.interface).
    match = re.fullmatch(r"[0-9]+-[0-9]+(?:\.[0-9]+)*:(?:x|[0-9]+)\.([0-9]+)", location, re.I)
    if match:
        number = int(match.group(1), 10)
        return number if 0 <= number <= 255 else None
    if sys.platform.startswith("linux"):
        from mklink.usb_platform import linux_interface_number
        return linux_interface_number(info)
    return None


def is_mklink_usb_port(info: Any) -> bool:
    return (
        getattr(info, "vid", None),
        getattr(info, "pid", None),
    ) == MKLINK_USB_VID_PID


def usb_interface_numbers(ports):
    """One fresh OS snapshot per enumeration; no stale cross-call cache."""
    ports = list(ports)
    if sys.platform == "darwin" and any(is_mklink_usb_port(p) for p in ports):
        from mklink.usb_platform import macos_interface_from_registry, macos_registry
        tree = macos_registry()
        return [macos_interface_from_registry(p, tree)
                if is_mklink_usb_port(p) and str(getattr(p, "device", "")).startswith("/dev/")
                else usb_interface_number(p) for p in ports]
    return [usb_interface_number(p) for p in ports]


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
