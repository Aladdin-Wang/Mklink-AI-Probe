from pathlib import Path
import io
import os
from urllib.error import URLError

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


def test_materialize_firmware_falls_back_from_github_to_gitee(monkeypatch):
    github = fc.FirmwareInfo(
        "MicroLink_V3.3.7.uf2",
        fc.Version(3, 3, 7),
        "V3",
        Path("MicroLink_V3.3.7.uf2"),
        download_url="https://github.example/MicroLink_V3.3.7.uf2",
        download_source="github",
    )
    gitee = fc.FirmwareInfo(
        github.name,
        github.version,
        github.model,
        github.path,
        download_url="https://gitee.example/MicroLink_V3.3.7.uf2",
        download_source="gitee",
    )
    monkeypatch.setattr(fc, "_remote_firmware_from_source", lambda model, source: gitee)
    requested = []

    def open_download(request, timeout):
        requested.append(request.full_url)
        if "github" in request.full_url:
            raise URLError("github unavailable")
        return io.BytesIO(b"gitee-uf2")

    monkeypatch.setattr(fc, "urlopen", open_download)

    path, temporary, source = fc._materialize_firmware(github)
    try:
        assert temporary is True
        assert source == "gitee"
        assert path.read_bytes() == b"gitee-uf2"
        assert requested == [github.download_url, gitee.download_url]
    finally:
        path.unlink(missing_ok=True)


def test_materialize_firmware_does_not_query_gitee_when_github_succeeds(monkeypatch):
    github = fc.FirmwareInfo(
        "MicroLink_V3.3.7.uf2",
        fc.Version(3, 3, 7),
        "V3",
        Path("MicroLink_V3.3.7.uf2"),
        download_url="https://github.example/MicroLink_V3.3.7.uf2",
        download_source="github",
    )
    monkeypatch.setattr(
        fc,
        "_remote_firmware_from_source",
        lambda model, source: (_ for _ in ()).throw(AssertionError("Gitee must stay lazy")),
    )
    monkeypatch.setattr(fc, "urlopen", lambda request, timeout: io.BytesIO(b"github-uf2"))

    path, temporary, source = fc._materialize_firmware(github)
    try:
        assert temporary is True
        assert source == "github"
        assert path.read_bytes() == b"github-uf2"
    finally:
        path.unlink(missing_ok=True)


def test_manual_upgrade_result_includes_latest_download_details(monkeypatch, tmp_path):
    disk = tmp_path / "disk"
    disk.mkdir()
    _readme(disk, "V3.3.6")
    firmware_root = tmp_path / "firmware"
    firmware_root.mkdir()
    candidate = fc.FirmwareInfo(
        "MicroLink_V3.3.7.uf2",
        fc.Version(3, 3, 7),
        "V3",
        Path("MicroLink_V3.3.7.uf2"),
        download_url="https://github.example/MicroLink_V3.3.7.uf2",
        download_source="github",
    )
    monkeypatch.setattr(fc, "_probe_disk", lambda: str(disk))
    monkeypatch.setattr(fc, "_remote_firmware", lambda model: candidate)

    result = fc.upgrade_probe_firmware(object(), firmware_root, confirm=True)

    assert result == {
        "status": "manual_required",
        "message": "当前后端不支持自动进入 Bootloader",
        "current_version": "V3.3.6",
        "latest_version": "V3.3.7",
        "firmware": "MicroLink_V3.3.7.uf2",
        "model": "V3",
        "download_available": True,
    }


def test_firmware_download_endpoint_returns_binary_and_source(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from mklink.remote.api import create_app

    firmware = tmp_path / "MicroLink_V3.3.7.uf2"
    firmware.write_bytes(b"release-uf2")
    candidate = fc.FirmwareInfo(
        firmware.name,
        fc.Version(3, 3, 7),
        "V3",
        firmware,
    )
    monkeypatch.setattr(fc, "latest_firmware", lambda model, root: candidate)
    monkeypatch.setattr(fc, "_materialize_firmware", lambda info: (firmware, False, "gitee"))
    app = create_app(auth_token=None, project_root=str(tmp_path))

    with TestClient(app) as client:
        response = client.get("/api/probe/firmware-download?model=V3")

    assert response.status_code == 200
    assert response.content == b"release-uf2"
    assert response.headers["x-mklink-firmware-name"] == firmware.name
    assert response.headers["x-mklink-firmware-version"] == "V3.3.7"
    assert response.headers["x-mklink-firmware-source"] == "gitee"
