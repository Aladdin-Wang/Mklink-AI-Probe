from pathlib import Path
import os

from mklink import firmware_check as fc


def _readme(path: Path, version: str) -> None:
    (path / "readme.txt").write_text(f"Firmware Build Date:test\n{version}\n", encoding="utf-8")


def test_read_microkeen_version_uses_first_changelog_version(tmp_path):
    _readme(tmp_path, "V3.3.7\nV3.3.6")
    assert fc.read_microkeen_version(tmp_path) == fc.Version(3, 3, 7)


def test_find_bootloader_disk_uses_uf2_marker(monkeypatch, tmp_path):
    (tmp_path / "INFO_UF2.TXT").write_text("UF2 Bootloader", encoding="ascii")
    monkeypatch.setenv("MKLINK_BOOTLOADER_DISK", str(tmp_path))
    assert fc._find_bootloader_disk() == str(tmp_path).rstrip("\\/") + ("\\" if os.name == "nt" else "/")


def test_upgrade_probe_firmware_returns_up_to_date_without_reboot(monkeypatch, tmp_path):
    disk = tmp_path / "disk"
    disk.mkdir()
    _readme(disk, "V3.3.7")
    firmware_root = tmp_path / "firmware"
    firmware_root.mkdir()
    (firmware_root / "MicroLink_V3.3.7.uf2").write_bytes(b"uf2")
    monkeypatch.setattr(fc, "_probe_disk", lambda: str(disk))
    monkeypatch.setattr(fc, "_remote_firmware", lambda model: None)

    class Device:
        def enter_bootloader(self):
            raise AssertionError("up-to-date firmware must not reboot")

    result = fc.upgrade_probe_firmware(Device(), firmware_root, confirm=True)
    assert result["status"] == "up_to_date"


def test_upgrade_probe_firmware_copies_and_verifies(monkeypatch, tmp_path):
    disk = tmp_path / "disk"
    disk.mkdir()
    _readme(disk, "V3.3.7")
    boot = tmp_path / "boot"
    boot.mkdir()
    (boot / "INFO_UF2.TXT").write_text("UF2 Bootloader", encoding="ascii")
    firmware_root = tmp_path / "firmware"
    firmware_root.mkdir()
    firmware = firmware_root / "MicroLink_V3.3.8.uf2"
    firmware.write_bytes(b"new-uf2")
    sequence = iter([str(disk), str(boot), str(disk)])
    monkeypatch.setattr(fc, "_probe_disk", lambda: next(sequence, str(disk)))
    monkeypatch.setattr(fc, "_find_bootloader_disk", lambda: str(boot))
    monkeypatch.setattr(
        fc,
        "_remote_firmware",
        lambda model: fc.FirmwareInfo("MicroLink_V3.3.8.uf2", fc.Version(3, 3, 8), "V3", firmware),
    )
    entered = []

    class Device:
        def enter_bootloader(self):
            entered.append(True)
            _readme(disk, "V3.3.8")

    result = fc.upgrade_probe_firmware(
        Device(), firmware_root, confirm=True, bootloader_timeout=0.1, verify_timeout=0.6
    )
    assert entered == [True]
    assert result["status"] == "updated"
    assert (boot / firmware.name).read_bytes() == b"new-uf2"
