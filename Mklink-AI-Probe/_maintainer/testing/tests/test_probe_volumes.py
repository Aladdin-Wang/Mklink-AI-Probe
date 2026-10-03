import pytest
from mklink import probe_volumes as volumes


def test_volume_binding_uses_full_usb_identity_and_stable_volume_path(monkeypatch):
    monkeypatch.setattr('mklink.probes.select_probe', lambda _: {
        'identity_stable': True, 'vid': 0xd28, 'pid': 0x202, 'serial_number': 'FIRST'})
    rows = [
        {'usb_identity': (0xd28, 0x202, 'second'), 'drive': 'G:', 'root': 'wrong'},
        {'usb_identity': (0xd28, 0x202, 'first'), 'drive': 'H:', 'root': '\\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\'},
    ]
    monkeypatch.setattr(volumes, 'volume_inventory', lambda: rows)
    result = volumes.resolve_volume('first')
    assert result['drive'] == 'H:' and result['root'].startswith('\\\\?\\Volume{')
    rows[1]['usb_identity'] = (0xd28, 0x202, 'second')
    with pytest.raises(RuntimeError, match='exactly one'):
        volumes.resolve_volume('first')


def test_duplicate_missing_serial_and_drive_letter_fallback_rejected(monkeypatch):
    probe = {'identity_stable': False, 'vid': 1, 'pid': 2, 'serial_number': 'serial'}
    monkeypatch.setattr('mklink.probes.select_probe', lambda _: probe)
    with pytest.raises(RuntimeError, match='unique'):
        volumes.resolve_volume('probe')
    probe['identity_stable'] = True
    row = {'usb_identity': (1, 2, 'serial'), 'root': 'G:\\', 'drive': 'G:'}
    monkeypatch.setattr(volumes, 'volume_inventory', lambda: [row])
    with pytest.raises(RuntimeError, match='GUID'):
        volumes.resolve_volume('probe')
    monkeypatch.setattr(volumes, 'volume_inventory', lambda: [row, row])
    with pytest.raises(RuntimeError, match='exactly one'):
        volumes.resolve_volume('probe')


def test_runtime_disk_failure_never_uses_label_or_environment_fallback(monkeypatch):
    from mklink.discovery import find_microkeen_disk
    monkeypatch.setattr(volumes, '_bound_probe', 'selected')
    monkeypatch.setenv('MKLINK_MICROKEEN_DISK', 'Z:\\')
    def unavailable(): raise RuntimeError('identity missing')
    monkeypatch.setattr(volumes, 'bound_disk', unavailable)
    with pytest.raises(RuntimeError, match='identity missing'):
        find_microkeen_disk()
