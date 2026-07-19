from pathlib import Path

import pytest

from mklink.flash import FlashError, MKLinkFlash, burn_hex_file, parse_hpm_program_result
from mklink.hpm_config import HPM_BOARD_FLASH_CFG
from mklink.project_config import save_config, save_project_info
from intelhex import IntelHex


def test_hpm_program_requires_loaded_successfully_or_100_percent():
    assert parse_hpm_program_result(
        'hpm.program("demo.bin",0x80000400)\n'
        "open fileName: demo.bin success,file size: 63384 byte\n"
        " demo.bin loaded successfully.\n"
        "0\n"
    )["success"]
    assert parse_hpm_program_result(
        'hpm.program("demo.bin",0x80000400)\n'
        "Download:  96% ,used 2127 ms\n"
        "Download: 100% ,used 2222 ms\n"
        "0\n"
    )["success"]

    assert not parse_hpm_program_result(
        'hpm.board("hpm5301evklite")\n'
        "board name = hpm5301evklite\n"
        "0\n"
        'hpm.program("demo.bin",0x80000400)\n'
        "0\n"
    )["success"]

    assert not parse_hpm_program_result(
        'hpm.program("demo.bin",0x80000400)\n'
        "Download:  96% ,used 2127 ms\n"
        "0\n"
    )["success"]


def test_mklink_flash_rejects_swd_clock_above_10_mhz():
    flash = MKLinkFlash(type("Bridge", (), {"send_command": lambda *_args, **_kwargs: "0"})())

    with pytest.raises(FlashError, match="10MHz"):
        flash.set_swd_clock(10_000_001)


class _FakeBridge:
    def send_command(self, cmd, timeout=0, echo=False):
        if cmd.startswith("hpm.board"):
            return "board name = hpm5301evklite\n0\n"
        if cmd.startswith("hpm.program"):
            return "0\n"
        raise AssertionError(cmd)


def test_hpm_burn_bin_sends_four_word_flash_cfg(tmp_path: Path):
    bin_file = tmp_path / "demo.bin"
    bin_file.write_bytes(b"demo")
    commands = []

    class Bridge:
        def send_command(self, cmd, timeout=0, echo=False):
            commands.append(cmd)
            if cmd.startswith("hpm.flash_cfg"):
                return "Header = 0xfcf90001,opt1 = 0x7,opt2 = 0x0,xpi_base = 0xf3040000\n0\n"
            if cmd.startswith("hpm.program"):
                return "Download: 100% ,used 1 ms\n0\n"
            raise AssertionError(cmd)

    flash = MKLinkFlash(Bridge())
    flash._copy_to_microkeen = lambda local_path, microkeen_filename=None: "demo.bin"

    result = flash.burn_hpm_bin(
        str(bin_file),
        addr="0x80000400",
        flash_cfg=("0xfcf90001U", "0x00000007U", "0x00000000U", "0xf3040000U"),
    )

    assert result["success"] is True
    assert commands[0] == "hpm.flash_cfg(0xfcf90001U,0x00000007U,0x00000000U,0xf3040000U)"
    assert commands[1] == 'hpm.program("demo.bin",0x80000400)'


def test_hpm_burn_bin_does_not_treat_plain_zero_as_success(tmp_path: Path):
    bin_file = tmp_path / "demo.bin"
    bin_file.write_bytes(b"demo")

    flash = MKLinkFlash(_FakeBridge())
    flash._copy_to_microkeen = lambda local_path, microkeen_filename=None: "demo.bin"

    result = flash.burn_hpm_bin(
        str(bin_file),
        addr="0x80000400",
        board="hpm5301evklite",
    )

    assert result["success"] is False
    assert result["loaded_successfully"] is False
    assert result["download_100_percent"] is False


@pytest.mark.parametrize(
    ("board", "flash_cfg", "addr"),
    [
        ('hpm5300evk\");hpm.program("evil.bin",0)', None, "0x80000400"),
        ("hpm5300evk", ("0xfcf90002U", "0x5U", "0x1000U", "0xf3000000U);evil()"), "0x80000400"),
        ("hpm5300evk", None, "0x80000400);evil()"),
    ],
)
def test_hpm_burn_bin_rejects_script_injection(
    tmp_path: Path, board, flash_cfg, addr
):
    firmware = tmp_path / "demo.bin"
    firmware.write_bytes(b"demo")
    commands = []
    flash = MKLinkFlash(type("Bridge", (), {
        "send_command": lambda _self, command, **_kwargs: commands.append(command) or "0"
    })())
    flash._copy_to_microkeen = lambda *_args, **_kwargs: "demo.bin"

    with pytest.raises((FlashError, ValueError)):
        flash.burn_hpm_bin(
            str(firmware), addr=addr, board=board, flash_cfg=flash_cfg
        )

    assert commands == []


def test_hpm_flash_does_not_require_mcu_profile(tmp_path: Path, monkeypatch):
    bin_file = tmp_path / "demo.bin"
    bin_file.write_bytes(b"demo")
    save_config(str(tmp_path), {
        "com_port": "COM9",
        "mcu_key": None,
        "swd_clock": 1000000,
    })
    save_project_info(str(tmp_path), {
        "vendor": "HPMicro",
        "board": "hpm6e00evk",
        "flash_base": "0x80003000",
        "bin_base": "0x80000400",
        "bin_path": str(bin_file),
    })

    calls = []

    class FakeFlash:
        def set_swd_clock(self, swd_clock):
            calls.append(("clock", swd_clock))

        def get_idcode(self):
            return 0x00000000

        def burn_hpm_bin(self, path, *, addr, board=None, flash_cfg=None, progress_callback=None):
            calls.append(("hpm", Path(path).name, addr, board))
            return {"success": True}

        def beep(self):
            calls.append(("beep",))

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(MKLinkFlash, "connect", staticmethod(lambda port=None: FakeFlash()))

    result = burn_hex_file(project_root=str(tmp_path))

    assert result["success"] is True
    assert result["algorithm_source"] == "hpm-rom-api"
    assert ("hpm", "demo.bin", "0x80000400", "hpm6e00evk") in calls


def test_hpm_custom_mcu_burn_hex_file_routes_to_hpm_program(tmp_path: Path, monkeypatch):
    bin_file = tmp_path / "demo.bin"
    bin_file.write_bytes(b"demo")
    save_config(str(tmp_path), {
        "com_port": "COM9",
        "mcu_key": "custom",
        "swd_clock": 1000000,
    })
    save_project_info(str(tmp_path), {
        "vendor": "HPMicro",
        "board": "hpm5301evklite",
        "flash_base": "0x80003000",
        "bin_base": "0x80000400",
        "bin_path": str(bin_file),
    })

    calls = []

    class FakeFlash:
        def set_swd_clock(self, swd_clock):
            calls.append(("clock", swd_clock))

        def get_idcode(self):
            calls.append(("idcode",))
            return 0x1000563D

        def load_flm(self, flm_path, flash_base, ram_base):
            raise AssertionError("custom HPM route must not load FLM")

        def burn_hpm_bin(self, path, *, addr, board=None, flash_cfg=None, progress_callback=None):
            calls.append(("hpm", Path(path).name, addr, board, tuple(flash_cfg)))
            return {"success": True}

        def burn_bin(self, *args, **kwargs):
            raise AssertionError("HPM BIN route must use burn_hpm_bin")

        def burn_hex(self, *args, **kwargs):
            raise AssertionError("HPM BIN route must not use burn_hex")

        def beep(self):
            calls.append(("beep",))

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(MKLinkFlash, "connect", staticmethod(lambda port=None: FakeFlash()))

    result = burn_hex_file(project_root=str(tmp_path))

    assert result["success"] is True
    assert result["algorithm_source"] == "hpm-rom-api"
    assert ("hpm", "demo.bin", "0x80000400", "hpm5301evklite", HPM_BOARD_FLASH_CFG["hpm5301evklite"]) in calls
    assert calls[-1] == ("close",)


def test_cli_flash_uses_builtin_catalog_algorithm_without_keil(tmp_path: Path, monkeypatch):
    from mklink.cmsis_dap.algorithm_catalog import FlashAlgorithm

    firmware = tmp_path / "external.hex"
    image = IntelHex()
    image.puts(0x90000000, b"external")
    image.write_hex_file(str(firmware))
    save_config(str(tmp_path), {"mcu_key": "custom", "swd_clock": 10_000_000})
    save_project_info(str(tmp_path), {
        "device": "DEVICE_A",
        "hex_path": str(firmware),
        "flash_base": "0x90000000",
    })
    algorithm = FlashAlgorithm(
        algorithm_id="a" * 64,
        target_part="DEVICE_A",
        file_name="External.FLM",
        flash_start=0x90000000,
        flash_size=0x800000,
        ram_start=0x20001000,
        ram_size=0x10000,
        default=False,
        source_kind="builtin-pack",
        source_name="Vendor.Pack@1",
        source_token="catalog:bundle:Vendor.Pack:1:DEVICE_A:0",
    )
    monkeypatch.setattr(
        "mklink.cmsis_dap.algorithm_catalog.discover_flash_algorithms",
        lambda part_number: [algorithm] if part_number == "DEVICE_A" else [],
    )
    monkeypatch.setattr(
        "mklink.cmsis_dap.algorithm_catalog.deploy_algorithm_to_probe",
        lambda selected: "/FLM/External_hash.flm",
    )
    calls = []

    class FakeFlash:
        def set_swd_clock(self, value): calls.append(("clock", value))
        def get_idcode(self): return 1
        def load_flm(self, path, flash_base, ram_base):
            calls.append(("flm", path, flash_base, ram_base))
            return True
        def burn_hex(self, path, progress_callback=None):
            calls.append(("hex", Path(path).name))
            return {"success": True}
        def beep(self): pass
        def close(self): pass

    monkeypatch.setattr(MKLinkFlash, "connect", staticmethod(lambda port=None: FakeFlash()))

    result = burn_hex_file(project_root=str(tmp_path))

    assert result["algorithm_source"] == "builtin-pack"
    assert ("flm", "/FLM/External_hash.flm", "0x90000000", "0x20001000") in calls
