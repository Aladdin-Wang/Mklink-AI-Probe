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
    monkeypatch.setattr('mklink.probes._bound_probe', 'selected')
    monkeypatch.setenv('MKLINK_MICROKEEN_DISK', 'Z:\\')
    def unavailable(probe_id):
        assert probe_id == 'selected'
        raise RuntimeError('identity missing')
    monkeypatch.setattr(volumes, 'resolve_volume', unavailable)
    with pytest.raises(RuntimeError, match='identity missing'):
        find_microkeen_disk()


def test_lobby_never_resolves_a_disk_even_with_a_matching_alias(monkeypatch, tmp_path):
    from mklink import probes
    from mklink.discovery import find_microkeen_disk
    from test_probe_identity import port
    monkeypatch.setenv('MKLINK_RUNTIME_DIR', str(tmp_path))
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [port('COM10', 'first')])
    selected = probes.inventory()[0]['probe_id']
    monkeypatch.setattr(probes, 'load_aliases', lambda: {selected: 'lobby'})
    monkeypatch.setattr(probes, '_bound_probe', 'lobby')
    monkeypatch.setattr(volumes, 'volume_inventory', lambda: pytest.fail('Lobby inspected hardware volumes'))
    with pytest.raises(ConnectionError, match='Select a physical probe'):
        find_microkeen_disk()
