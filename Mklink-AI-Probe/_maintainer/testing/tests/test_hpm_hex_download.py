from pathlib import Path

import pytest

from mklink.flash import FlashError, MKLinkFlash, parse_hpm_program_result
from mklink.hpm_image import _record


def source(tmp_path):
    path = tmp_path / 'source.hex'
    path.write_bytes(_record(4, 0, b'\x80\x00') +
                     _record(0, 0x30, b'late') + _record(0, 0x10, b'early') +
                     _record(1, 0, b''))
    return path


@pytest.mark.parametrize('capability', ['AttributeError: program_hex\n', '0\n', '', 'Error\n-1\n'])
def test_old_firmware_rejected_before_copy_or_setup(tmp_path, capability):
    calls = []
    class Bridge:
        def send_command(self, command, **kwargs):
            calls.append(command)
            return capability
    flash = MKLinkFlash(Bridge())
    flash._copy_to_microkeen = lambda *args: pytest.fail('must not stage for old firmware')
    with pytest.raises(FlashError, match='requires downloader firmware'):
        flash.burn_hpm_hex(str(source(tmp_path)), board='hpm6e00evk')
    assert calls == ['hpm.program_hex()']


def test_hex_is_normalized_and_uses_dedicated_entry(tmp_path, monkeypatch):
    calls, staged = [], []
    monkeypatch.setattr('mklink.flash.time.sleep', lambda _: None)
    class Bridge:
        def send_command(self, command, **kwargs):
            calls.append(command)
            if command == 'hpm.program_hex()':
                return 'hpm.program_hex()\n-1\n'
            if command.startswith('hpm.board'):
                return '0\n'
            return 'source.hex loaded successfully.\n0\n'
    flash = MKLinkFlash(Bridge())
    def copy(path, name):
        staged.append((Path(path), Path(path).read_bytes()))
        return name
    flash._copy_to_microkeen = copy
    result = flash.burn_hpm_hex(str(source(tmp_path)), board='hpm6e00evk')
    assert result['success']
    assert calls[-1] == "hpm.program_hex('source.hex')"
    assert staged[0][1].index(b'6561726C79') < staged[0][1].index(b'6C617465')
    assert not staged[0][0].exists()


def test_invalid_hex_rejected_before_any_device_command(tmp_path):
    class Bridge:
        def send_command(self, *args, **kwargs):
            pytest.fail('invalid input must not access probe')
    path = tmp_path / 'bad.hex'
    path.write_text(':0000000100\n')
    with pytest.raises(Exception):
        MKLinkFlash(Bridge()).burn_hpm_hex(str(path), board='hpm6e00evk')


def test_configuration_failure_does_not_program(tmp_path, monkeypatch):
    calls = []
    class Bridge:
        def send_command(self, command, **kwargs):
            calls.append(command)
            return '-1\n'
    flash = MKLinkFlash(Bridge())
    flash._copy_to_microkeen = lambda *args: 'source.hex'
    with pytest.raises(FlashError, match='configuration failed'):
        flash.burn_hpm_hex(str(source(tmp_path)), board='hpm6e00evk')
    assert calls == ['hpm.program_hex()', 'hpm.board("hpm6e00evk")']


@pytest.mark.parametrize('marker', ['HPM_HEX_FAIL phase=-5', 'HPM_BIN_FAIL storage busy'])
def test_failure_marker_overrides_earlier_success(marker):
    assert not parse_hpm_program_result('loaded successfully\n' + marker)['success']


def test_offline_hex_capability_precedes_first_bin_and_stages_canonical(tmp_path):
    from mklink.offline_download import parse_offline_config, generate_offline_script, _transactional_copy
    config = parse_offline_config({
        'model':'V4', 'script_name':'hex.py', 'target_part':'HPM6E80',
        'board':'hpm6e00evk', 'algorithms':[], 'firmwares':[
            {'id':'bin','file_name':'first.bin','format':'bin','base_address':'0x80000000','upload_index':0},
            {'id':'hex','file_name':'second.hex','format':'hex','upload_index':1},
        ],
    })
    script = generate_offline_script(config)
    assert script.index('hpm.program_hex()') < script.index('hpm.program("first.bin"')
    assert 'hpm.program_hex("second.hex")' in script
    disk = tmp_path/'disk';disk.mkdir()
    _transactional_copy(disk, [(Path('second.hex'),source(tmp_path),None)],
                        hpm_hex_files=frozenset({'second.hex'}))
    content=(disk/'second.hex').read_bytes()
    assert content.index(b'6561726C79') < content.index(b'6C617465')


def test_offline_invalid_hex_does_not_touch_existing_bundle(tmp_path):
    from mklink.offline_download import _transactional_copy
    disk=tmp_path/'disk';disk.mkdir()
    (disk/'a.bin').write_bytes(b'keep')
    bad=tmp_path/'bad.hex';bad.write_text(':0000000100\n')
    with pytest.raises(Exception):
        _transactional_copy(disk,[(Path('a.bin'),None,b'new'),(Path('bad.hex'),bad,None)],
                            hpm_hex_files=frozenset({'bad.hex'}))
    assert (disk/'a.bin').read_bytes()==b'keep'
    assert not (disk/'bad.hex').exists()
