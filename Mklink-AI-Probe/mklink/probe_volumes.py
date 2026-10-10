"""Identity-bound MSC discovery. Labels/mount names never identify a probe."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


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


def volume_inventory(*, firmware=False):
    if os.name != 'nt':
        from mklink.posix_probe_volumes import macos_volume_inventory, linux_volume_inventory
        if sys.platform == 'darwin':
            return macos_volume_inventory(firmware=True) if firmware else macos_volume_inventory()
        if sys.platform.startswith('linux'):
            return linux_volume_inventory(firmware=True) if firmware else linux_volume_inventory()
        raise RuntimeError('USB volume discovery is unavailable on this operating system')
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


def validated_volume_root(row):
    if row.get('platform') in ('darwin', 'linux'):
        from mklink.posix_probe_volumes import validate_mount
        if not validate_mount(row):
            raise RuntimeError('Verified USB volume is no longer mounted; no disk selected')
    elif not re.fullmatch(r'\\\\\?\\Volume\{[0-9a-f-]{36}\}\\', row['root'], re.I):
        raise RuntimeError('A stable Windows volume GUID is required')
    return row['root']


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
    return {'probe_id': probe_id, 'root': validated_volume_root(row), 'drive': row['drive'], 'verified': True}


class FirmwareVolumes:
    """Follow the selected application disk, then its newly appearing UF2 disk.

    CHERRYUF2 is the dedicated upgrade label. Old bootloaders may have broken
    or missing serial descriptors, so their serial is not an admission gate.
    Exclude pre-existing upgrade volumes and reject multiple new candidates.
    Ordinary offline target files still use resolve_volume's strict identity.
    """
    def __init__(self, probe):
        self.identity = ((probe['vid'], probe['pid'], probe['serial_number'].casefold())
                         if probe.get('identity_stable') and probe.get('serial_number') else None)
        self._existing_boot_roots = set()

    @staticmethod
    def _boot_root(row):
        label = (row.get('label') or '').strip().upper()
        if label not in {'CHERRYUF2', 'MICROKEEN'}:
            return None
        try:
            root = validated_volume_root(row)
            try:
                info = (Path(root) / 'INFO_UF2.TXT').read_text(encoding='utf-8', errors='replace')
            except FileNotFoundError:
                info = ''  # Older CHERRYUF2 firmware need not expose a marker.
            board = re.search(r'(?m)^Board-ID:\s*([^\r\n]+)', info)
            if board and board[1].strip() != 'MicroKeenLink':
                return None
            if label == 'MICROKEEN' and not board:
                return None  # An ordinary data disk is not an upgrade disk.
            return root
        except (OSError, RuntimeError):
            return None

    def begin_update(self):
        # Snapshot just before sending the reboot command, not before a slow
        # download. A different probe already in UF2 mode must never be chosen.
        self._existing_boot_roots = {
            root for row in volume_inventory(firmware=True)
            if (root := self._boot_root(row)) is not None
        }

    def find(self, *, bootloader=False):
        rows = volume_inventory(firmware=True)
        if bootloader:
            roots = [root for row in rows if (root := self._boot_root(row)) is not None
                     and root not in self._existing_boot_roots]
            return roots[0] if len(roots) == 1 else None
        rows = [row for row in rows if (row.get('label') or '').strip().upper() == 'MICROKEEN']
        if self.identity is not None:
            # Keep the pre-reboot source/model tied to the selected application.
            rows = [row for row in rows if row.get('usb_identity') == self.identity]
        if len(rows) != 1:
            return None
        try:
            return validated_volume_root(rows[0])
        except RuntimeError:
            return None
