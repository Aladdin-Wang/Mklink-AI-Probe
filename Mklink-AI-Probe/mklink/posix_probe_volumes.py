"""Read-only mounted-volume discovery bound to physical USB ancestry.

Ordinary target storage requires USB identity. Firmware inventory additionally
includes USB media without serial descriptors for CHERRYUF2 label selection.
Unmounted storage is left to the OS; discovery does not mount or change it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import re
import subprocess


def _command(args):
    try:
        return subprocess.run(args, capture_output=True, check=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('USB volume inventory unavailable; no disk selected') from exc


def _mount_signature(root):
    if not isinstance(root, str) or not os.path.isabs(root) or root == '/':
        return None
    # A link or a directory surviving unmount must never receive firmware.
    if os.path.realpath(root) != root or not os.path.ismount(root):
        return None
    try:
        stat = os.stat(root)
        return (stat.st_dev, stat.st_ino)
    except OSError:
        return None


def validate_mount(row):
    signature = _mount_signature(row.get('root'))
    return signature is not None and signature == row.get('mount_signature')


def macos_media_identities(tree, *, require_serial=True):
    """Associate IOMedia BSD names with the nearest USB device, not a label."""
    found = {}
    def visit(node, identity=None):
        if not isinstance(node, dict):
            return
        if 'idVendor' in node and 'idProduct' in node:
            serial = str(node.get('USB Serial Number') or '').strip().casefold()
            identity = (node['idVendor'], node['idProduct'], serial) if serial or not require_serial else None
        name = node.get('BSD Name')
        if isinstance(name, str) and re.fullmatch(r'disk\d+(?:s\d+)*', name):
            found.setdefault(name, set()).add(identity)
        for child in node.get('IORegistryEntryChildren', []):
            visit(child, identity)
    for node in tree if isinstance(tree, list) else [tree]:
        visit(node)
    return {name: next(iter(ids)) for name, ids in found.items()
            if len(ids) == 1 and None not in ids}


def macos_volume_inventory(*, firmware=False):
    from mklink.usb_platform import macos_registry
    identities = macos_media_identities(macos_registry(), require_serial=not firmware)
    rows = []
    for name, identity in identities.items():
        if not firmware and identity[:2] != (0x0d28, 0x0202):
            continue
        try:
            info = plistlib.loads(_command(['/usr/sbin/diskutil', 'info', '-plist', '/dev/' + name]))
        except (ValueError, RuntimeError, plistlib.InvalidFileException):
            continue  # Device may disappear during re-enumeration.
        if not isinstance(info, dict) or info.get('DeviceIdentifier') != name:
            continue
        root = info.get('MountPoint')
        signature = _mount_signature(root)
        if signature is None:
            continue
        rows.append({'usb_identity': identity, 'root': root, 'drive': root,
                     'label': info.get('VolumeName', ''), 'platform': 'darwin',
                     'device_node': '/dev/' + name, 'mount_signature': signature})
    # diskutil and IOKit are separate snapshots: reject a replaced BSD node.
    fresh = macos_media_identities(macos_registry(), require_serial=not firmware) if rows else {}
    return [row for row in rows if fresh.get(row['device_node'][5:]) == row['usb_identity']
            and validate_mount(row)]


def linux_usb_identity(major_minor, *, sysfs=Path('/sys/dev/block'), require_serial=True):
    if not re.fullmatch(r'\d+:\d+', major_minor):
        return None
    try:
        node = (sysfs / major_minor).resolve(strict=True)
        for parent in (node, *node.parents):
            if (parent / 'idVendor').is_file() and (parent / 'idProduct').is_file():
                try:
                    serial = (parent / 'serial').read_text().strip().casefold()
                except OSError:
                    serial = ''
                if not serial and require_serial:
                    return None
                return (int((parent / 'idVendor').read_text().strip(), 16),
                        int((parent / 'idProduct').read_text().strip(), 16), serial)
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def linux_mounts(text):
    """Read mountinfo (including escaped spaces), excluding subdirectory binds."""
    mounts = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 10 or '-' not in fields or fields[3] != '/':
            continue
        if not re.fullmatch(r'\d+:\d+', fields[2]):
            continue
        root = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[4])
        mounts.append((fields[2], root))
    return mounts


def linux_volume_inventory(*, firmware=False):
    try:
        inventory = json.loads(_command(['/usr/bin/lsblk', '--json', '--paths',
                                         '--output', 'NAME,MAJ:MIN,LABEL']))
        mounts = linux_mounts(Path('/proc/self/mountinfo').read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError('Linux volume inventory unavailable; no disk selected') from exc
    blocks = {}
    def visit(entries):
        for entry in entries:
            blocks.setdefault(entry.get('maj:min'), []).append(entry)
            visit(entry.get('children', []))
    visit(inventory.get('blockdevices', []))
    rows = []
    for major_minor, root in mounts:
        candidates = blocks.get(major_minor, [])
        if len(candidates) != 1:
            continue
        def read_identity():
            return (linux_usb_identity(major_minor, require_serial=False) if firmware
                    else linux_usb_identity(major_minor))
        identity = read_identity()
        if identity is None or (not firmware and identity[:2] != (0x0d28, 0x0202)):
            continue
        signature = _mount_signature(root)
        if signature is None or (os.major(signature[0]), os.minor(signature[0])) != tuple(map(int, major_minor.split(':'))):
            continue
        if read_identity() != identity:
            continue
        rows.append({'usb_identity': identity, 'root': root, 'drive': root,
                     'label': candidates[0].get('label') or '', 'platform': 'linux',
                     'device_node': candidates[0].get('name'), 'mount_signature': signature})
    return rows
