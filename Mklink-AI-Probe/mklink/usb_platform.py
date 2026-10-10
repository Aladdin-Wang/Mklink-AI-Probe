"""Passive OS USB metadata: exact device-node binding, never serial I/O."""
from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path


def _same_device(info, properties):
    if (properties.get("idVendor"), properties.get("idProduct")) != (getattr(info, "vid", None), getattr(info, "pid", None)):
        return False
    expected = str(getattr(info, "serial_number", "") or "").strip()
    actual = str(properties.get("USB Serial Number", "") or "").strip()
    return not expected or expected == actual


def _interface_nodes(device):
    """Do not cross into another USB device while collecting interfaces."""
    result = []
    def visit(node):
        if node is not device and "idVendor" in node and "idProduct" in node:
            return
        number = node.get("bInterfaceNumber")
        if type(number) is int and 0 <= number <= 255:
            result.append(node)
        for child in node.get("IORegistryEntryChildren", []):
            if isinstance(child, dict):
                visit(child)
    visit(device)
    return result


def macos_interface_from_registry(info, tree):
    """Bind IOSerialBSDClient to its actual USB interface ancestor.

    ACM serial clients can be below the data interface. For MKLink only,
    normalize it to the descriptor-confirmed control/data pair, not a suffix
    of the BSD device name. Ambiguous or conflicting metadata is rejected.
    """
    device_path = str(getattr(info, "device", ""))
    matches = []
    def visit(node, device=None, interface=None):
        if not isinstance(node, dict):
            return
        if "idVendor" in node and "idProduct" in node:
            device, interface = node, None
        if "bInterfaceNumber" in node:
            interface = node
        if device_path in (node.get("IOCalloutDevice"), node.get("IODialinDevice")):
            if device is not None and interface is not None and _same_device(info, device):
                matches.append((device, interface))
        for child in node.get("IORegistryEntryChildren", []):
            visit(child, device, interface)
    for root in tree if isinstance(tree, list) else [tree]:
        visit(root)
    if len(matches) != 1:
        return None
    device, interface = matches[0]
    number = interface.get("bInterfaceNumber")
    if type(number) is not int or not 0 <= number <= 255:
        return None
    if (device.get("idVendor"), device.get("idProduct")) == (0x0D28, 0x0202) and interface.get("bInterfaceClass") == 0x0A:
        expected_names = {3: "MKLink USB to UART", 5: "MKLink Python Console", 7: "MKLink USB to RS485"}
        expected = expected_names.get(number)
        if not expected:
            return None
        controls = [entry for entry in _interface_nodes(device)
                    if entry.get("bInterfaceNumber") == number - 1
                    and entry.get("bInterfaceClass") == 2
                    and entry.get("bInterfaceSubClass") == 2
                    and (entry.get("USB Interface Name") or entry.get("IORegistryEntryName")) == expected]
        return number - 1 if len(controls) == 1 else None
    return number


def macos_registry():
    try:
        result = subprocess.run(["/usr/sbin/ioreg", "-a", "-l", "-p", "IOService"],
                                capture_output=True, check=True, timeout=5)
        return plistlib.loads(result.stdout)
    except (OSError, ValueError, plistlib.InvalidFileException, subprocess.SubprocessError):
        return []


def macos_interface_number(info):
    return macos_interface_from_registry(info, macos_registry())


def linux_interface_number(info, *, sysfs_root=Path("/sys/class/tty")):
    """Use bInterfaceNumber from the selected tty's sysfs ancestry."""
    device_string = str(getattr(info, "device", ""))
    if not device_string.startswith("/dev/"):
        return None
    device = Path(device_string)
    try:
        node = (Path(sysfs_root) / device.resolve().name / "device").resolve(strict=True)
        number = None
        for parent in (node, *node.parents):
            if number is None and (parent / "bInterfaceNumber").is_file():
                number = int((parent / "bInterfaceNumber").read_text().strip(), 16)
            if (parent / "idVendor").is_file() and (parent / "idProduct").is_file():
                properties = {"idVendor": int((parent / "idVendor").read_text().strip(), 16),
                              "idProduct": int((parent / "idProduct").read_text().strip(), 16),
                              "USB Serial Number": (parent / "serial").read_text().strip() if (parent / "serial").is_file() else ""}
                return number if _same_device(info, properties) and number is not None and 0 <= number <= 255 else None
    except (OSError, ValueError, RuntimeError):
        return None
    return None
