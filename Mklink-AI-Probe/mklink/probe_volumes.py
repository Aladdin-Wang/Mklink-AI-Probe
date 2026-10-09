"""Identity-bound Windows MSC discovery. Labels/drive letters never identify a probe."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def usb_ancestor(instance_id):
    api = ctypes.WinDLL('cfgmgr32')
    number = ctypes.c_ulong
    api.CM_Locate_DevNodeW.argtypes = [ctypes.POINTER(number), ctypes.c_wchar_p, number]
    api.CM_Get_Parent.argtypes = [ctypes.POINTER(number), number, number]
    api.CM_Get_Device_IDW.argtypes = [number, ctypes.c_wchar_p, number, number]
    node = number()
    if api.CM_Locate_DevNodeW(ctypes.byref(node), instance_id, 0):
        return None
    for _ in range(24):
        value = ctypes.create_unicode_buffer(1024)
        if api.CM_Get_Device_IDW(node, value, len(value), 0):
            return None
        match = re.fullmatch(r'USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})\\([^\\]+)', value.value, re.I)
        if match:
            return (int(match[1], 16), int(match[2], 16), match[3].casefold())
        parent = number()
        if api.CM_Get_Parent(ctypes.byref(parent), node, 0):
            return None
        node = parent
    return None


def volume_inventory():
    if os.name != 'nt':
        raise RuntimeError('Identity-bound MSC discovery is currently supported on Windows only')
    script = Path(__file__).with_name('windows_probe_volumes.ps1')
    powershell = shutil.which('pwsh') or shutil.which('powershell.exe')
    if not powershell:
        system_root = os.environ.get('SystemRoot') or os.environ.get('WINDIR')
        if not system_root:
            raise RuntimeError('Windows system directory unavailable; no disk selected')
        powershell = str(Path(system_root) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe')
    try:
        result = subprocess.run([powershell, '-NoProfile', '-NonInteractive',
                                 '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                                capture_output=True, encoding='utf-8-sig', errors='replace', timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('Windows volume inventory unavailable; no disk selected') from exc
    if result.returncode:
        raise RuntimeError('Windows volume inventory failed; no disk selected')
    try:
        rows = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError('Invalid Windows volume inventory; no disk selected') from exc
    for row in rows:
        row['usb_identity'] = usb_ancestor(row['pnp_id'])
    return rows


def resolve_volume(probe_id):
    from mklink.probes import select_probe
    probe = select_probe(probe_id)
    if not probe['identity_stable']:
        raise RuntimeError('MSC requires a unique USB serial number')
    identity = (probe['vid'], probe['pid'], probe['serial_number'].casefold())
    matches = [row for row in volume_inventory() if row.get('usb_identity') == identity
               and row.get('label', 'MICROKEEN') == 'MICROKEEN']
    if len(matches) != 1:
        raise RuntimeError('Bound probe must have exactly one verified MICROKEEN volume; no disk selected')
    row = matches[0]
    # Volume GUID paths remain tied to the volume if Windows reuses a drive letter.
    if not re.fullmatch(r'\\\\\?\\Volume\{[0-9a-f-]{36}\}\\', row['root'], re.I):
        raise RuntimeError('A stable Windows volume GUID is required')
    return {'probe_id': probe_id, 'root': row['root'], 'drive': row['drive'], 'verified': True}


class FirmwareVolumes:
    """Retain USB identity while CDC disappears during a UF2 update.

    V3/V4 application descriptors expose OTP words 88/89 (16 hex chars);
    MicroLink/HPMLink UF2 descriptors expose words 88..91 (32 hex chars).
    Never identify the bootloader by label, drive letter or enumeration order.
    """
    def __init__(self, probe):
        if not probe['identity_stable']:
            raise RuntimeError('Firmware update requires a unique USB serial number')
        self.identity = (probe['vid'], probe['pid'], probe['serial_number'].casefold())

    def find(self, *, bootloader=False):
        def matches(row):
            identity = row.get('usb_identity')
            if not identity:
                return False
            if identity == self.identity:
                return True
            return (bootloader and identity[:2] == self.identity[:2] == (0x0d28, 0x0202)
                    and re.fullmatch('[0-9a-f]{16}', self.identity[2]) is not None
                    and re.fullmatch('[0-9a-f]{32}', identity[2]) is not None
                    and identity[2][:16] == self.identity[2])
        rows = [row for row in volume_inventory() if matches(row)]
        if len(rows) != 1:
            return None
        root = rows[0]['root']
        if not re.fullmatch(r'\\\\\?\\Volume\{[0-9a-f-]{36}\}\\', root, re.I):
            return None
        if bootloader:
            try:
                info = (Path(root) / 'INFO_UF2.TXT').read_text(encoding='utf-8', errors='replace')
            except OSError:
                return None
            if not re.search(r'(?m)^Board-ID:\s*MicroKeenLink\s*$', info):
                return None
        elif rows[0].get('label') != 'MICROKEEN':
            return None
        return root
