import pytest
from mklink import probe_volumes as volumes


@pytest.mark.parametrize('serial,expected', [
    ('0123456789abcdef', True), ('0123456789abcdef1111222233334444', True),
    ('0123456789abcdee1111222233334444', False), ('0123456789abcdef12', False),
])
def test_firmware_bootloader_uses_exact_or_documented_uid_mapping(monkeypatch, serial, expected):
    from pathlib import Path
    root = '\\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\'
    row = {'usb_identity': (0xd28, 0x202, serial), 'root': root, 'label': 'UF2'}
    monkeypatch.setattr(volumes, 'volume_inventory', lambda: [row])
    monkeypatch.setattr(Path, 'read_text', lambda self, **kw: 'UF2 Bootloader\r\nBoard-ID: MicroKeenLink\r\n')
    binding = volumes.FirmwareVolumes({'identity_stable': True, 'vid': 0xd28, 'pid': 0x202,
                                      'serial_number': '0123456789ABCDEF'})
    assert binding.find(bootloader=True) == (root if expected else None)
    assert binding.find() is None


def test_firmware_bootloader_never_uses_another_or_ambiguous_disk(monkeypatch):
    from pathlib import Path
    root = '\\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\'
    row = {'usb_identity': (0xd28, 0x202, '0123456789abcdef1111222233334444'), 'root': root}
    rows = [row, dict(row)]
    monkeypatch.setattr(volumes, 'volume_inventory', lambda: rows)
    monkeypatch.setattr(Path, 'read_text', lambda self, **kw: 'Board-ID: MicroKeenLink\n')
    binding = volumes.FirmwareVolumes({'identity_stable': True, 'vid': 0xd28, 'pid': 0x202,
                                      'serial_number': '0123456789abcdef'})
    assert binding.find(bootloader=True) is None
    rows.pop()
    row['root'] = 'G:\\'  # reused drive letters are never accepted
    assert binding.find(bootloader=True) is None
    row['root'] = root
    monkeypatch.setattr(Path, 'read_text', lambda self, **kw: 'Board-ID: OtherBoard\n')
    assert binding.find(bootloader=True) is None


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


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows volume inventory')
def test_minimal_path_uses_system_powershell_without_selecting_a_drive(monkeypatch):
    import subprocess
    from pathlib import Path
    from types import SimpleNamespace
    monkeypatch.setattr(volumes.shutil, 'which', lambda _: None)
    monkeypatch.setenv('SystemRoot', 'X:/Windows')
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='[]')
    monkeypatch.setattr(subprocess, 'run', run)
    assert volumes.volume_inventory() == []
    assert Path(calls[0][0][0]) == Path('X:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe')
    assert calls[0][1]['creationflags'] == subprocess.CREATE_NO_WINDOW
    assert calls[0][1]['encoding'] == 'utf-8-sig'
