"""Sanitized OS fixtures, not physical USB acceptance evidence."""
import json
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from mklink import posix_probe_volumes as posix, probe_volumes as volumes


def usb(serial, *children):
    return {'idVendor': 0xd28, 'idProduct': 0x202, 'USB Serial Number': serial,
            'IORegistryEntryChildren': list(children)}


def test_macos_media_binds_partition_to_physical_device_and_rejects_collision():
    tree = [usb('FIRST', {'BSD Name': 'disk4', 'IORegistryEntryChildren': [{'BSD Name': 'disk4s1'}]}),
            usb('SECOND', {'BSD Name': 'disk5'}), {'BSD Name': 'disk0'}]
    assert posix.macos_media_identities(tree) == {
        'disk4': (0xd28, 0x202, 'first'), 'disk4s1': (0xd28, 0x202, 'first'),
        'disk5': (0xd28, 0x202, 'second')}
    tree.append(usb('OTHER', {'BSD Name': 'disk4s1'}))
    assert 'disk4s1' not in posix.macos_media_identities(tree)
    assert posix.macos_media_identities([usb('', {'BSD Name': 'disk6'})]) == {}


def test_macos_firmware_disk_without_serial_uses_real_volume_label(monkeypatch):
    tree = [usb('', {'BSD Name': 'disk4s1'}), {'BSD Name': 'disk0'}]
    monkeypatch.setattr('mklink.usb_platform.macos_registry', lambda: tree)
    monkeypatch.setattr(posix, '_command', lambda _: plistlib.dumps({
        'DeviceIdentifier': 'disk4s1', 'MountPoint': '/Volumes/CHERRYUF2 1', 'VolumeName': 'CHERRYUF2'}))
    monkeypatch.setattr(posix, '_mount_signature', lambda _: (17, 2))
    assert posix.macos_volume_inventory() == []
    rows = posix.macos_volume_inventory(firmware=True)
    assert len(rows) == 1 and rows[0]['label'] == 'CHERRYUF2'
    monkeypatch.setattr(volumes, 'volume_inventory', lambda **kw: rows)
    def missing(*a, **kw): raise FileNotFoundError()
    monkeypatch.setattr(Path, 'read_text', missing)
    assert volumes.FirmwareVolumes({'identity_stable': False}).find(bootloader=True) == '/Volumes/CHERRYUF2 1'


@pytest.mark.parametrize('changed', [False, True])
def test_macos_inventory_uses_diskutil_plist_and_rechecks_usb_identity(monkeypatch, changed):
    tree = [usb('FIRST', {'BSD Name': 'disk4s1'}), usb('SECOND', {'BSD Name': 'disk5'})]
    fresh = [usb('REPLACED', {'BSD Name': 'disk4s1'}), tree[1]] if changed else tree
    snapshots = iter([tree, fresh])
    monkeypatch.setattr('mklink.usb_platform.macos_registry', lambda: next(snapshots))
    def command(args):
        assert args[:4] == ['/usr/sbin/diskutil', 'info', '-plist', args[3]]
        name = args[3][5:]
        return plistlib.dumps({'DeviceIdentifier': name, 'MountPoint': '/Volumes/' + name,
                              'VolumeName': 'MICROKEEN'})
    monkeypatch.setattr(posix, '_command', command)
    monkeypatch.setattr(posix, '_mount_signature', lambda _: (17, 2))
    rows = posix.macos_volume_inventory()
    assert len(rows) == (1 if changed else 2)
    monkeypatch.setattr(volumes, 'volume_inventory', lambda: rows)
    monkeypatch.setattr('mklink.probes.select_probe', lambda _: {
        'identity_stable': True, 'vid': 0xd28, 'pid': 0x202, 'serial_number': 'SECOND'})
    assert volumes.resolve_volume('second')['root'] == '/Volumes/disk5'


@pytest.mark.parametrize('info', [{}, {'DeviceIdentifier': 'disk9', 'MountPoint': '/Volumes/MICROKEEN'},
                                  {'DeviceIdentifier': 'disk4'}])
def test_macos_missing_mismatched_unmounted_disk_never_selected(monkeypatch, info):
    monkeypatch.setattr('mklink.usb_platform.macos_registry', lambda: [usb('FIRST', {'BSD Name': 'disk4'})])
    monkeypatch.setattr(posix, '_command', lambda _: plistlib.dumps(info))
    assert posix.macos_volume_inventory() == []


def test_linux_mountinfo_escapes_and_subdirectory_binds():
    assert posix.linux_mounts('41 30 8:17 / /media/user/MICROKEEN\\0401 rw - vfat /dev/sdb1 rw\n'
                             '42 30 8:17 /subdir /mnt/bind rw - vfat /dev/sdb1 rw\n'
                             'bad line\n') == [('8:17', '/media/user/MICROKEEN 1')]


def test_linux_sysfs_follows_usb_ancestry_and_requires_serial(tmp_path):
    # No links required: the fixture models a resolved sysfs device path.
    device = tmp_path / 'usb' / 'block'
    device.mkdir(parents=True)
    partition = device / 'partition'
    partition.mkdir()
    class SysfsRoot:
        def __truediv__(self, name):
            assert name == '8:17'
            return partition
    sysfs = SysfsRoot()  # Windows filenames cannot contain a colon.
    for name, value in [('idVendor', '0d28'), ('idProduct', '0202'), ('serial', 'FIRST')]:
        (device.parent / name).write_text(value)
    assert posix.linux_usb_identity('8:17', sysfs=sysfs) == (0xd28, 0x202, 'first')
    (device.parent / 'serial').unlink()
    assert posix.linux_usb_identity('8:17', sysfs=sysfs) is None
    assert posix.linux_usb_identity('8:17', sysfs=sysfs, require_serial=False) == (0xd28, 0x202, '')
    assert posix.linux_usb_identity('../usb', sysfs=sysfs) is None


def test_linux_firmware_disk_without_serial_uses_mountinfo_and_label(monkeypatch):
    monkeypatch.setattr(posix, '_command', lambda _: json.dumps({'blockdevices': [
        {'name': '/dev/sdb1', 'maj:min': '8:17', 'label': 'CHERRYUF2'}]}).encode())
    def read_text(path, **kw):
        if path.as_posix() == '/proc/self/mountinfo':
            return '41 30 8:17 / /run/media/user/CHERRYUF2 rw - vfat /dev/sdb1 rw'
        raise FileNotFoundError()
    monkeypatch.setattr(Path, 'read_text', read_text)
    monkeypatch.setattr(posix, 'linux_usb_identity', lambda _, require_serial=True: None if require_serial else (0xd28, 0x202, ''))
    monkeypatch.setattr(posix, '_mount_signature', lambda _: (123, 2))
    monkeypatch.setattr(posix.os, 'major', lambda _: 8, raising=False)
    monkeypatch.setattr(posix.os, 'minor', lambda _: 17, raising=False)
    assert posix.linux_volume_inventory() == []
    rows = posix.linux_volume_inventory(firmware=True)
    assert len(rows) == 1 and rows[0]['label'] == 'CHERRYUF2'
    monkeypatch.setattr(volumes, 'volume_inventory', lambda **kw: rows)
    assert volumes.FirmwareVolumes({'identity_stable': False}).find(bootloader=True) == '/run/media/user/CHERRYUF2'


@pytest.mark.parametrize('stale', [False, True])
def test_linux_inventory_matches_block_number_not_mount_name(monkeypatch, stale):
    monkeypatch.setattr(posix, '_command', lambda _: json.dumps({'blockdevices': [
        {'name': '/dev/sdb', 'maj:min': '8:16', 'label': None, 'children': [
            {'name': '/dev/sdb1', 'maj:min': '8:17', 'label': 'MICROKEEN'}]}]}).encode())
    monkeypatch.setattr(Path, 'read_text', lambda _: '41 30 8:17 / /media/user/renamed rw - vfat /dev/sdb1 rw')
    monkeypatch.setattr(posix, 'linux_usb_identity', lambda _: (0xd28, 0x202, 'first'))
    monkeypatch.setattr(posix, '_mount_signature', lambda _: (123, 2))
    monkeypatch.setattr(posix.os, 'major', lambda _: 8, raising=False)
    monkeypatch.setattr(posix.os, 'minor', lambda _: 18 if stale else 17, raising=False)
    rows = posix.linux_volume_inventory()
    assert len(rows) == (0 if stale else 1)
    if rows:
        assert rows[0]['root'] == '/media/user/renamed'
        assert rows[0]['label'] == 'MICROKEEN'


def test_posix_mount_replacement_rejected_before_resolution_or_uf2(monkeypatch):
    row = {'usb_identity': (0xd28, 0x202, 'first'), 'root': '/media/probe', 'drive': '/media/probe',
           'platform': 'linux', 'mount_signature': (1, 2), 'label': 'MICROKEEN'}
    probe = {'identity_stable': True, 'vid': 0xd28, 'pid': 0x202, 'serial_number': 'FIRST'}
    monkeypatch.setattr(volumes, 'volume_inventory', lambda **kw: [row])
    monkeypatch.setattr('mklink.probes.select_probe', lambda _: probe)
    monkeypatch.setattr(posix, '_mount_signature', lambda _: (9, 2))
    with pytest.raises(RuntimeError, match='no longer mounted'):
        volumes.resolve_volume('first')
    assert volumes.FirmwareVolumes(probe).find(bootloader=True) is None
    monkeypatch.setattr(posix, '_mount_signature', lambda _: (1, 2))
    assert volumes.resolve_volume('first')['root'] == row['root']
    monkeypatch.setattr(Path, 'read_text', lambda *_a, **_kw: 'Board-ID: MicroKeenLink\n')
    assert volumes.FirmwareVolumes(probe).find(bootloader=True) == row['root']
    monkeypatch.setattr(volumes, 'volume_inventory', lambda: [row, row])
    with pytest.raises(RuntimeError, match='exactly one'):
        volumes.resolve_volume('first')


def test_mount_signature_rejects_unmounted_directory_and_symlink(monkeypatch):
    monkeypatch.setattr(posix.os.path, 'isabs', lambda _: True)
    monkeypatch.setattr(posix.os.path, 'realpath', lambda p: p)
    monkeypatch.setattr(posix.os.path, 'ismount', lambda _: False)
    assert posix._mount_signature('/Volumes/MICROKEEN') is None
    monkeypatch.setattr(posix.os.path, 'ismount', lambda _: True)
    monkeypatch.setattr(posix.os.path, 'realpath', lambda _: '/other')
    assert posix._mount_signature('/Volumes/MICROKEEN') is None


@pytest.mark.parametrize('platform', ['darwin', 'linux'])
def test_volume_inventory_dispatches_to_host_platform(monkeypatch, platform):
    monkeypatch.setattr(volumes, 'os', SimpleNamespace(name='posix'))
    monkeypatch.setattr(volumes.sys, 'platform', platform)
    monkeypatch.setattr(posix, 'macos_volume_inventory', lambda: ['mac'])
    monkeypatch.setattr(posix, 'linux_volume_inventory', lambda: ['linux'])
    assert volumes.volume_inventory() == (['mac'] if platform == 'darwin' else ['linux'])
