from pathlib import Path
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mklink.firmware_check import Version, read_bridge_version, read_device_version
from mklink.offline_download import (
    OfflineDownloadError,
    deploy_offline_bundle,
    generate_offline_script,
    parse_offline_config,
    script_filename,
)
from mklink.remote.api import create_app
from mklink.remote.offline_download_api import detect_probe_model
from mklink.remote.resource_manager import ResourceGroup


def _config(model="V4"):
    return {
        "model": model,
        "script_name": "factory-line-a.py",
        "auto_download_count": 3,
        "wait_idcode_timeout_ms": 10000,
        "swd_clock_hz": 10000000,
        "algorithms": [
            {
                "id": "internal",
                "file_name": "STM32F10x_1024.FLM",
                "flash_base": "0x08000000",
                "ram_base": "0x20000000",
                "source_kind": "upload",
                "upload_index": 0,
            },
            {
                "id": "external",
                "file_name": "External.FLM",
                "flash_base": "0x90000000",
                "ram_base": "0x20010000",
                "source_kind": "upload",
                "upload_index": 1,
            },
        ],
        "firmwares": [
            {
                "id": "boot",
                "file_name": "boot.bin",
                "format": "bin",
                "base_address": "0x08000000",
                "algorithm_id": "internal",
                "upload_index": 0,
            },
            {
                "id": "app",
                "file_name": "rt-thread.hex",
                "format": "hex",
                "base_address": None,
                "algorithm_id": "internal",
                "upload_index": 1,
            },
            {
                "id": "assets",
                "file_name": "assets.bin",
                "format": "bin",
                "base_address": "0x90000000",
                "algorithm_id": "external",
                "upload_index": 2,
            },
        ],
    }


def test_probe_model_controls_script_filename():
    assert script_filename("V2", "custom.py") == "offline_download.py"
    assert script_filename("V3", "custom.py") == "offline_download.py"
    assert script_filename("V4", "custom.py") == "custom.py"


def test_v2_rejects_automatic_multi_round_downloads():
    payload = _config("V2")
    with pytest.raises(OfflineDownloadError, match="V2.*1"):
        parse_offline_config(payload)


def test_offline_swd_clock_is_limited_to_10_mhz():
    payload = _config()
    payload["swd_clock_hz"] = 10_000_001
    with pytest.raises(OfflineDownloadError, match="SWD clock.*10000000"):
        parse_offline_config(payload)


def test_bin_requires_an_address_and_hex_uses_embedded_addresses():
    payload = _config()
    payload["firmwares"][0]["base_address"] = None
    with pytest.raises(OfflineDownloadError, match="BIN.*base address"):
        parse_offline_config(payload)

    payload = _config()
    payload["firmwares"][1]["base_address"] = "0x08005000"
    parsed = parse_offline_config(payload)
    assert parsed.firmwares[1].base_address is None


def test_v4_script_supports_multiple_files_addresses_algorithms_and_rounds():
    config = parse_offline_config(_config())
    script = generate_offline_script(config)

    assert "AUTO_DOWNLOAD_COUNT = 3" in script
    assert "WAIT_IDCODE_TIMEOUT = 10000" in script
    assert "cmd.set_swd_clock(10000000)" in script
    assert 'load.flm("FLM/STM32F10x_1024.FLM", 0x08000000, 0x20000000)' in script
    assert 'load.bin("boot.bin", 0x08000000)' in script
    assert 'load.hex("rt-thread.hex")' in script
    assert 'load.flm("FLM/External.FLM", 0x90000000, 0x20010000)' in script
    assert 'load.bin("assets.bin", 0x90000000)' in script
    assert script.index('load.bin("boot.bin"') < script.index('load.hex("rt-thread.hex"')
    assert script.index('load.hex("rt-thread.hex"') < script.index('load.flm("FLM/External.FLM"')


def test_hpm_offline_script_uses_rom_api_without_flm():
    payload = {
        "model": "V4",
        "script_name": "hpm-offline.py",
        "auto_download_count": 2,
        "wait_idcode_timeout_ms": 10000,
        "swd_clock_hz": 10000000,
        "target_part": "HPM5301xEGx",
        "board": "hpm5301evklite",
        "algorithms": [],
        "firmwares": [{
            "id": "app",
            "file_name": "app.bin",
            "format": "bin",
            "base_address": "0x80000400",
            "algorithm_id": "",
            "upload_index": 0,
        }],
    }

    config = parse_offline_config(payload)
    script = generate_offline_script(config)

    assert config.algorithms == ()
    assert "import hpm" in script
    assert 'hpm.board("hpm5301evklite")' in script
    assert 'hpm.program("app.bin", 0x80000400)' in script
    assert "load.flm" not in script


def test_non_hpm_offline_config_rejects_hpm_board_settings():
    payload = _config()
    payload["target_part"] = "STM32F103RC"
    payload["board"] = "hpm5301evklite"

    with pytest.raises(OfflineDownloadError, match="only valid for HPM"):
        parse_offline_config(payload)


def test_deploy_copies_script_firmwares_and_flms_to_expected_usb_directories(tmp_path):
    config = parse_offline_config(_config())
    firmware_sources = []
    for name in ("boot.bin", "rt-thread.hex", "assets.bin"):
        path = tmp_path / ("source-" + name)
        path.write_bytes(name.encode("ascii"))
        firmware_sources.append(path)
    algorithm_sources = []
    for name in ("internal.flm", "external.flm"):
        path = tmp_path / name
        path.write_bytes(name.encode("ascii"))
        algorithm_sources.append(path)
    disk = tmp_path / "MICROKEEN"
    disk.mkdir()
    (disk / "keep.txt").write_text("keep", encoding="ascii")

    result = deploy_offline_bundle(
        config,
        disk,
        firmware_sources=firmware_sources,
        algorithm_sources=algorithm_sources,
    )

    assert result["script_name"] == "factory-line-a.py"
    assert (disk / "python" / "factory-line-a.py").is_file()
    assert (disk / "boot.bin").read_bytes() == b"boot.bin"
    assert (disk / "rt-thread.hex").read_bytes() == b"rt-thread.hex"
    assert (disk / "assets.bin").read_bytes() == b"assets.bin"
    assert (disk / "FLM" / "STM32F10x_1024.FLM").read_bytes() == b"internal.flm"
    assert (disk / "FLM" / "External.FLM").read_bytes() == b"external.flm"
    assert (disk / "keep.txt").read_text(encoding="ascii") == "keep"


def test_v3_deploy_forces_offline_download_script_name(tmp_path):
    payload = _config("V3")
    payload["auto_download_count"] = 1
    config = parse_offline_config(payload)
    firmware_sources = []
    for index, name in enumerate(("boot.bin", "rt-thread.hex", "assets.bin")):
        path = tmp_path / f"firmware-{index}"
        path.write_bytes(name.encode("ascii"))
        firmware_sources.append(path)
    algorithm_sources = []
    for index in range(2):
        path = tmp_path / f"algorithm-{index}"
        path.write_bytes(bytes([index]))
        algorithm_sources.append(path)
    disk = tmp_path / "MICROKEEN"
    disk.mkdir()

    deploy_offline_bundle(
        config,
        disk,
        firmware_sources=firmware_sources,
        algorithm_sources=algorithm_sources,
    )

    assert (disk / "python" / "offline_download.py").is_file()
    assert not (disk / "python" / "factory-line-a.py").exists()


def test_detect_probe_model_uses_cmd_get_version():
    with patch("mklink.discovery.find_mklink_cdc_port", return_value="TEST_CDC"), patch(
        "mklink.firmware_check.read_device_version",
        return_value=Version(4, 3, 3),
    ) as read_version:
        assert detect_probe_model() == {"model": "V4", "version": "V4.3.3"}
    read_version.assert_called_once_with("TEST_CDC")


def test_detect_probe_model_retries_a_transient_empty_response():
    with patch("mklink.discovery.find_mklink_cdc_port", return_value="TEST_CDC"), patch(
        "mklink.firmware_check.read_device_version",
        side_effect=[None, Version(4, 3, 4)],
    ) as read_version, patch("mklink.remote.offline_download_api.time.sleep") as sleep:
        assert detect_probe_model() == {"model": "V4", "version": "V4.3.4"}

    assert read_version.call_count == 2
    sleep.assert_called_once_with(0.5)


def test_read_device_version_imports_the_serial_bridge(monkeypatch):
    calls = []

    class Bridge:
        def __init__(self, port):
            calls.append(("init", port))

        def connect(self):
            calls.append(("connect",))
            return True

        def send_command(self, command, timeout):
            calls.append(("send", command, timeout))
            return "V4.3.3"

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr("mklink.bridge.MKLinkSerialBridge", Bridge)

    assert read_device_version("TEST_CDC") == Version(4, 3, 3)
    assert calls == [
        ("init", "TEST_CDC"),
        ("connect",),
        ("send", "cmd.get_version()", 5.0),
        ("close",),
    ]


def test_read_bridge_version_reuses_an_existing_connection():
    class Bridge:
        def send_command(self, command, timeout):
            assert (command, timeout) == ("cmd.get_version()", 5.0)
            return "V4.3.4"

    assert read_bridge_version(Bridge()) == Version(4, 3, 4)


def test_read_device_version_rejects_failed_serial_connection(monkeypatch):
    calls = []

    class Bridge:
        def __init__(self, port):
            calls.append(("init", port))

        def connect(self):
            calls.append(("connect",))
            return False

        def send_command(self, command, timeout):
            raise AssertionError("send_command must not run without a connection")

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr("mklink.bridge.MKLinkSerialBridge", Bridge)

    with pytest.raises(ConnectionError, match="Unable to connect to MKLink CDC port"):
        read_device_version("TEST_CDC")
    assert calls == [("init", "TEST_CDC"), ("connect",), ("close",)]


def test_preview_api_generates_the_resolved_script():
    app = create_app(auth_token=None, project_root=".")
    with TestClient(app) as client:
        response = client.post("/api/offline-download/preview", json=_config())

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "V4"
    assert payload["script_name"] == "factory-line-a.py"
    assert 'load.hex("rt-thread.hex")' in payload["script"]


def test_trigger_api_runs_load_offline_with_both_resources_leased(monkeypatch):
    calls = []

    class Bridge:
        def __init__(self, port):
            calls.append(("init", port))

        def connect(self):
            calls.append(("connect",))
            return True

        def send_command(self, command, timeout, echo):
            calls.append(("send", command, timeout, echo))
            return "offline download finished"

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr("mklink.bridge.MKLinkSerialBridge", Bridge)
    monkeypatch.setattr("mklink.discovery.find_mklink_cdc_port", lambda: "TEST_CDC")
    app = create_app(auth_token=None, project_root=".")

    with TestClient(app) as client:
        response = client.post("/api/offline-download/trigger", json={})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert calls == [
        ("init", "TEST_CDC"),
        ("connect",),
        ("send", "load.offline()", 600, True),
        ("close",),
    ]
    assert app.state.mklink_state["resource_manager"].get_status() == {}


def test_trigger_api_preserves_a_conflicting_resource_lease(monkeypatch):
    monkeypatch.setattr("mklink.discovery.find_mklink_cdc_port", lambda: "TEST_CDC")
    app = create_app(auth_token=None, project_root=".")
    manager = app.state.mklink_state["resource_manager"]
    manager.acquire(ResourceGroup.MKLINK_BRIDGE, "user:dashboard:rtt")

    with TestClient(app) as client:
        response = client.post("/api/offline-download/trigger", json={})

    assert response.status_code == 409
    lease = manager.get_active_lease(ResourceGroup.MKLINK_BRIDGE)
    assert lease is not None
    assert lease.owner == "user:dashboard:rtt"
    assert manager.get_active_lease(ResourceGroup.TARGET_DEBUG) is None


def test_offline_api_reuses_the_connected_device_bridge():
    calls = []

    class Bridge:
        def send_command(self, command, timeout, echo=False):
            calls.append((command, timeout, echo))
            if command == "cmd.get_version()":
                return "V4.3.4"
            return "offline download finished"

    class Device:
        connected = True
        port = "TEST_CDC"
        _bridge = Bridge()

        def close(self):
            pass

    app = create_app(auth_token=None, project_root=".")
    app.state.mklink_state["device"] = Device()

    with TestClient(app) as client:
        detected = client.post("/api/offline-download/detect-model", json={})
        preview = client.post(
            "/api/offline-download/preview",
            json={**_config(), "model": "auto"},
        )
        triggered = client.post("/api/offline-download/trigger", json={})

    assert detected.json() == {"model": "V4", "version": "V4.3.4"}
    assert preview.status_code == 200, preview.text
    assert preview.json()["model"] == "V4"
    assert triggered.status_code == 200, triggered.text
    assert triggered.json()["status"] == "completed"
    assert calls == [
        ("cmd.get_version()", 5.0, False),
        ("cmd.get_version()", 5.0, False),
        ("load.offline()", 600, True),
    ]


def test_deploy_api_writes_uploaded_bundle_to_microkeen_disk(tmp_path):
    disk = tmp_path / "MICROKEEN"
    disk.mkdir()
    app = create_app(auth_token=None, project_root=".")
    files = [
        ("firmware_files", ("boot.bin", b"boot", "application/octet-stream")),
        ("firmware_files", ("rt-thread.hex", b":00000001FF", "application/octet-stream")),
        ("firmware_files", ("assets.bin", b"assets", "application/octet-stream")),
        ("flm_files", ("internal.flm", b"internal", "application/octet-stream")),
        ("flm_files", ("external.flm", b"external", "application/octet-stream")),
    ]
    with patch("mklink.discovery.find_microkeen_disk", return_value=str(disk)), TestClient(app) as client:
        response = client.post(
            "/api/offline-download/deploy",
            data={"config_json": json.dumps(_config())},
            files=files,
        )

    assert response.status_code == 200, response.text
    assert (disk / "python" / "factory-line-a.py").is_file()
    assert (disk / "boot.bin").read_bytes() == b"boot"
    assert (disk / "FLM" / "STM32F10x_1024.FLM").read_bytes() == b"internal"
