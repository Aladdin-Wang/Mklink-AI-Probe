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
    try:
        result = subprocess.run([shutil.which('pwsh') or 'powershell.exe', '-NoProfile', '-NonInteractive',
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
    matches = [row for row in volume_inventory() if row.get('usb_identity') == identity]
    if len(matches) != 1:
        raise RuntimeError('Bound probe must have exactly one verified MICROKEEN volume; no disk selected')
    row = matches[0]
    # Volume GUID paths remain tied to the volume if Windows reuses a drive letter.
    if not re.fullmatch(r'\\\\\?\\Volume\{[0-9a-f-]{36}\}\\', row['root'], re.I):
        raise RuntimeError('A stable Windows volume GUID is required')
    return {'probe_id': probe_id, 'root': row['root'], 'drive': row['drive'], 'verified': True}
