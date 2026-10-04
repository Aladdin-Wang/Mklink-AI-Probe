from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from mklink.cli import _cli_project_init
from mklink import discovery
from mklink.keil_parser import parse_uvprojx, _project_path
from mklink.project_config import (
    check_project_config, lint_config_semantic, load_config, load_project_info,
    save_config, save_project_info,
)


PROJECT = r'''<Project xmlns="urn:keil:test"><Targets><Target>
<TargetName>Test</TargetName><uAC6>1</uAC6>
<Groups><Group><Files><File><FileType>n/a</FileType><FileOption>
<TargetArmAds><LDads><umfTarg>0</umfTarg><ScatterFile>wrong.sct</ScatterFile></LDads>
</TargetArmAds></FileOption></File></Files></Group></Groups>
<TargetOption><TargetCommonOption><Device>STM32H750VBTx</Device>
<Cpu>IRAM(0x24000000,0x80000) IROM(0x08000000,0x20000)</Cpu>
<OutputDirectory>.\Objects\</OutputDirectory><OutputName>firmware</OutputName>
<ListingPath>.\Listings\</ListingPath></TargetCommonOption>
<TargetArmAds><LDads><umfTarg>0</umfTarg><ScatterFile>.\layout.sct</ScatterFile>
</LDads></TargetArmAds></TargetOption></Target></Targets></Project>'''


def project(tmp_path):
    path = tmp_path / "project.uvprojx"
    path.write_text(PROJECT, encoding="utf-8")
    (tmp_path / "layout.sct").write_text("LR_IROM1 0x08004000 0x10000 {}", encoding="utf-8")
    return path


def test_keil_namespace_file_options_and_windows_relative_paths(tmp_path):
    info = parse_uvprojx(str(project(tmp_path)))
    assert info["device"] == "STM32H750VBTx"
    assert info["compiler"] == "ac6"
    assert info["flash_base"] == "0x08004000"
    assert Path(info["hex_path"]) == tmp_path / "Objects" / "firmware.hex"
    assert Path(info["map_path"]) == tmp_path / "Listings" / "firmware.map"
    assert info["groups"][0]["files"][0]["type"] == 1
    assert parse_uvprojx(str(tmp_path / "project.uvprojx"), "Absent") is None


def test_windows_relative_path_on_posix():
    class PosixFixture(PurePosixPath):
        def resolve(self):
            return self
    assert str(_project_path(PosixFixture("/shared/project"), ".\\Objects\\")) == "/shared/project/Objects"


def test_init_offline_minimal_and_preserves_custom_settings(tmp_path, monkeypatch):
    project(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("project-init must not discover hardware or profiles")
    monkeypatch.setattr(discovery, "find_mklink_cdc_port", forbidden)
    monkeypatch.setattr("mklink.mcu_detect.inspect_mcu", forbidden)
    _cli_project_init(str(tmp_path))
    assert load_config(str(tmp_path)) == {"swd_clock": 1000000}
    info = load_project_info(str(tmp_path))
    assert info["device"] == "STM32H750VBTx"
    assert not {"mcu_key", "flm_name", "flm_path", "groups", "mcu_detect"} & info.keys()
    assert not (tmp_path / ".mklink/rtt_config.json").exists()
    assert not (tmp_path / ".mklink/toolchain.json").exists()
    assert check_project_config(str(tmp_path)).is_valid
    save_config(str(tmp_path), {"com_port": "/dev/cu.usbmodem1405", "swd_clock": 2000000})
    (tmp_path / ".mklink/rtt_config.json").write_text('{"channel": 2}', encoding="utf-8")
    _cli_project_init(str(tmp_path))
    assert load_config(str(tmp_path))["swd_clock"] == 2000000
    assert (tmp_path / ".mklink/rtt_config.json").read_text() == '{"channel": 2}'


def test_invalid_existing_config_is_not_overwritten(tmp_path):
    project(tmp_path)
    save_config(str(tmp_path), {})
    (tmp_path / ".mklink/config.json").write_text("{oops", encoding="utf-8")
    _cli_project_init(str(tmp_path))
    assert (tmp_path / ".mklink/config.json").read_text() == "{oops"
    assert load_project_info(str(tmp_path)) is None


@pytest.mark.parametrize("port", ["", "COM228", "com8", "/dev/cu.usbmodem1405", "/dev/ttyACM0", "/dev/serial/by-id/usb-test"])
def test_port_lint_accepts_auto_and_native_paths(tmp_path, port):
    save_config(str(tmp_path), {"com_port": port})
    assert lint_config_semantic(str(tmp_path)) == []


def test_missing_rtt_optional_but_malformed_rtt_is_error(tmp_path):
    save_config(str(tmp_path), {})
    save_project_info(str(tmp_path), {"device": "STM32H750VBTx"})
    assert not check_project_config(str(tmp_path)).warnings
    (tmp_path / ".mklink/rtt_config.json").write_text("{", encoding="utf-8")
    assert not check_project_config(str(tmp_path)).is_valid


def mock_volumes(monkeypatch, *, platform, directories, mounts):
    monkeypatch.setattr(discovery.sys, "platform", platform)
    monkeypatch.delenv("MKLINK_MICROKEEN_DISK", raising=False)
    monkeypatch.setattr(discovery.os.path, "ismount", lambda path: path in mounts)
    monkeypatch.setattr(discovery.os.path, "islink", lambda path: False)
    monkeypatch.setattr(discovery.os.path, "isdir", lambda path: True)
    class Scan:
        def __init__(self, path):
            self.paths = directories.get(path, [])
        def __enter__(self):
            return [SimpleNamespace(path=path, is_dir=lambda **kw: True) for path in self.paths]
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(discovery.os, "scandir", Scan)


def test_macos_only_mounted_volume_and_ambiguous_fail_closed(monkeypatch):
    mock_volumes(monkeypatch, platform="darwin", directories={"/Volumes": ["/Volumes/MICROKEEN", "/Volumes/MICROKEEN 1"]}, mounts={"/Volumes/MICROKEEN"})
    assert discovery._find_posix_microkeen_disk() == "/Volumes/MICROKEEN"
    monkeypatch.setattr(discovery.os.path, "ismount", lambda path: True)
    assert discovery._find_posix_microkeen_disk() is None
    monkeypatch.setattr(discovery.os.path, "ismount", lambda path: False)
    assert discovery._find_posix_microkeen_disk() is None


def test_linux_per_user_mount(monkeypatch):
    mock_volumes(monkeypatch, platform="linux", directories={"/run/media": ["/run/media/user"], "/run/media/user": ["/run/media/user/MICROKEEN"]}, mounts={"/run/media/user/MICROKEEN"})
    assert discovery._find_posix_microkeen_disk() == "/run/media/user/MICROKEEN"

@pytest.mark.parametrize('reverse', [False, True])
def test_profile_resolution_uses_specificity_and_rejects_ambiguous_idcode(reverse):
    from mklink.profiles import match_mcu_by_device, match_mcu_by_idcode
    profiles = {
        'family': {'device_prefix': 'CHIP', 'idcode_pattern': '0x12345678'},
        'part': {'device_prefix': 'CHIP123', 'idcode_pattern': '0X12345678'},
        'neighbor': {'device_prefix': 'OTHER', 'idcode_pattern': '0x87654321'},
        'unidentified': {'idcode_pattern': None},
    }
    if reverse:
        profiles = dict(reversed(list(profiles.items())))
    assert match_mcu_by_device('chip123re', profiles) == 'part'
    assert match_mcu_by_device('CHIP999', profiles) == 'family'
    assert match_mcu_by_device('missing', profiles) is None
    assert match_mcu_by_idcode(0x12345678, profiles) is None
    assert match_mcu_by_idcode(0x87654321, profiles) == 'neighbor'
    profiles['duplicate'] = {'device_prefix': 'chip123'}
    assert match_mcu_by_device('CHIP123RE', profiles) is None


def test_device_profile_falls_back_to_specific_model_when_idcode_is_ambiguous(monkeypatch):
    from mklink.device import Device
    from types import SimpleNamespace
    profiles = {
        'family': {'device_prefix': 'CHIP', 'idcode_pattern': '0x12345678'},
        'part': {'device_prefix': 'CHIP123', 'idcode_pattern': '0x12345678'},
    }
    monkeypatch.setattr('mklink.profiles.load_mcu_profiles', lambda: profiles)
    device = object.__new__(Device)
    device._bridge = SimpleNamespace(idcode=0x12345678, current_mcu='CHIP123RE')
    assert device._get_mcu_profile() is profiles['part']
    device._bridge.current_mcu = ''
    assert device._get_mcu_profile() is None
