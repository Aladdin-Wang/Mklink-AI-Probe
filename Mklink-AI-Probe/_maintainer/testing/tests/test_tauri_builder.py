import importlib.util
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest


BUILDER_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "tauri-gui-builder"
    / "scripts"
    / "build.py"
)
BUILTIN_PACK_BUILDER_PATH = BUILDER_PATH.with_name("builtin_packs.py")


@pytest.fixture
def builder():
    spec = importlib.util.spec_from_file_location("mklink_tauri_builder", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def builtin_pack_builder():
    spec = importlib.util.spec_from_file_location(
        "mklink_builtin_pack_builder", BUILTIN_PACK_BUILDER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_external_bin_patch_restores_exact_config(builder, tmp_path):
    config = tmp_path / "tauri.conf.json"
    original = b'{"bundle":{"active":true,"icon":[]}}\n'
    config.write_bytes(original)

    with builder.temporary_external_bin(config):
        assert "externalBin" in config.read_text(encoding="utf-8")

    assert config.read_bytes() == original


def test_external_bin_patch_restores_after_failure(builder, tmp_path):
    config = tmp_path / "tauri.conf.json"
    original = b'{"bundle":{"active":true,"icon":[]}}'
    config.write_bytes(original)

    with pytest.raises(RuntimeError, match="build failed"):
        with builder.temporary_external_bin(config):
            raise RuntimeError("build failed")

    assert config.read_bytes() == original


def test_release_bundle_forces_sidecar_rebuild(builder, monkeypatch, tmp_path):
    calls = []
    builder.TAURI_DIR = tmp_path
    (tmp_path / "tauri.conf.json").write_text(
        '{"bundle":{"active":true,"icon":[]}}', encoding="utf-8"
    )
    monkeypatch.setattr(
        builder,
        "build_sidecar",
        lambda force=False: calls.append(force) or True,
    )
    monkeypatch.setattr(builder, "build_tauri", lambda bundle=False: None)

    builder.build_release_bundle()

    assert calls == [True]


def test_tauri_build_injects_packaged_api_origin(builder, monkeypatch, tmp_path):
    builder.GUI_DIR = tmp_path
    builder.TAURI_DIR = tmp_path / "src-tauri"
    executable = builder.TAURI_DIR / "target" / "release" / "mklink-ai-probe.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"exe")
    calls = []
    monkeypatch.setattr(
        builder,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)) or 0,
    )

    builder.build_tauri(bundle=False)

    assert calls[0][1]["env"]["VITE_MKLINK_API"] == "http://127.0.0.1:8765"


def test_release_bundle_removes_stale_bundle_outputs(builder, monkeypatch, tmp_path):
    builder.TAURI_DIR = tmp_path
    (tmp_path / "tauri.conf.json").write_text(
        '{"version":"0.1.0-rc.2","bundle":{"active":true}}',
        encoding="utf-8",
    )
    stale_bundle = tmp_path / "target" / "release" / "bundle"
    stale_msi = stale_bundle / "msi" / "stale.msi"
    stale_msi.parent.mkdir(parents=True)
    stale_msi.write_bytes(b"stale")
    observed = []
    monkeypatch.setattr(builder, "build_sidecar", lambda force=False: True)
    monkeypatch.setattr(
        builder,
        "build_tauri",
        lambda bundle=False: observed.append((bundle, stale_bundle.exists())),
    )

    builder.build_release_bundle()

    assert observed == [(True, False)]


def test_release_bundle_aborts_when_stale_outputs_cannot_be_removed(
    builder, monkeypatch, tmp_path,
):
    builder.TAURI_DIR = tmp_path
    (tmp_path / "tauri.conf.json").write_text(
        '{"version":"0.1.0-rc.2","bundle":{"active":true}}',
        encoding="utf-8",
    )
    stale_bundle = tmp_path / "target" / "release" / "bundle"
    stale_bundle.mkdir(parents=True)
    built = []
    monkeypatch.setattr(builder, "build_sidecar", lambda force=False: True)
    monkeypatch.setattr(builder.shutil, "rmtree", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        builder, "build_tauri", lambda bundle=False: built.append(bundle),
    )

    with pytest.raises(RuntimeError, match="stale bundle"):
        builder.build_release_bundle()

    assert built == []


def test_bundle_config_preserves_product_version_and_builds_only_nsis(builder, tmp_path):
    config = tmp_path / "tauri.conf.json"
    original = b'{"version":"0.1.0-rc.1","bundle":{"active":true}}\n'
    config.write_bytes(original)

    with builder.temporary_bundle_config(config):
        patched = config.read_text(encoding="utf-8")
        assert '"version": "0.1.0-rc.1"' in patched
        assert '"targets": [' in patched
        assert '"nsis"' in patched
        assert '"msi"' not in patched
        assert '"externalBin"' in patched

    assert config.read_bytes() == original


def test_sidecar_collects_pyocd_plugins_metadata_and_hid_binary(builder, monkeypatch, tmp_path):
    builder.SKILL_DIR = tmp_path
    builder.TAURI_DIR = tmp_path / "gui" / "src-tauri"
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        output = tmp_path / "dist" / "mklink-sidecar.exe"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"sidecar")
        return 0

    monkeypatch.setattr(builder, "run", fake_run)

    assert builder.build_sidecar(force=True) is True

    pairs = [commands[0][index:index + 2] for index in range(len(commands[0]) - 1)]
    assert ["--collect-all", "pyocd"] in pairs
    assert ["--copy-metadata", "pyocd"] in pairs
    assert ["--collect-all", "cmsis_pack_manager"] in pairs
    assert ["--collect-all", "hid"] in pairs


def test_builtin_pack_builder_keeps_only_descriptor_algorithms_and_licenses(
    builtin_pack_builder, monkeypatch, tmp_path,
):
    pack_root = tmp_path / "packs"
    source = pack_root / "Keil" / "Test_DFP" / "1.0.0"
    (source / "Flash").mkdir(parents=True)
    (source / "Keil.Test_DFP.pdsc").write_text(
        '<package><vendor>Keil</vendor><name>Test_DFP</name>'
        '<releases><release version="1.0.0"/></releases>'
        '<devices><family Dfamily="Test"><device Dname="TEST123">'
        '<algorithm name="Flash/Test.FLM" start="0x08000000" size="0x1000"/>'
        '</device></family></devices></package>',
        encoding="utf-8",
    )
    (source / "Flash" / "Test.FLM").write_bytes(b"algorithm")
    (source / "LICENSE").write_text("Apache-2.0", encoding="utf-8")
    (source / "example.bin").write_bytes(b"do-not-bundle")
    config = tmp_path / "builtin-packs.json"
    config.write_text(json.dumps({
        "schema": 1,
        "packs": [{
            "pack_id": "Keil.Test_DFP",
            "version": "1.0.0",
            "license_files": ["LICENSE"],
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(
        builtin_pack_builder,
        "_read_targets",
        lambda _path: [{"part_number": "TEST123", "vendor": "Keil"}],
    )
    output = tmp_path / "bundle"

    manifest = builtin_pack_builder.build_bundle(config, [pack_root], output)

    slim_pack = output / manifest["packs"][0]["file"]
    with ZipFile(slim_pack) as archive:
        assert sorted(archive.namelist()) == [
            "Flash/Test.FLM",
            "Keil.Test_DFP.pdsc",
            "LICENSE",
        ]
    assert manifest["target_count"] == 1
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8")) == manifest


def test_builtin_pack_builder_accepts_explicit_authorized_slim_archives(
    builtin_pack_builder, monkeypatch, tmp_path,
):
    pack_root = tmp_path / "pyocd-packs"
    pack_root.mkdir()
    archive_path = pack_root / "Vendor.Device_DFP.1.0.0-small.pack"
    descriptor = (
        '<package><vendor>Vendor</vendor><name>Device_DFP</name>'
        '<license>LICENSE.txt</license>'
        '<releases><release version="1.0.0"/></releases>'
        '<devices><family Dfamily="Test"><device Dname="DEVICE_A">'
        '<algorithm name="Flash/Test.FLM" start="0x08000000" size="0x1000"/>'
        '</device></family></devices></package>'
    )
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("Vendor.Device_DFP.pdsc", descriptor)
        archive.writestr("Flash/Test.FLM", b"algorithm")
        archive.writestr("LICENSE.txt", "Redistribution terms")
        archive.writestr("Examples/large.bin", b"do-not-bundle")
    config = tmp_path / "builtin-packs.json"
    config.write_text(json.dumps({
        "schema": 1,
        "packs": [],
        "archives": [{
            "file": archive_path.name,
            "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            "redistribution_authorized": True,
            "provenance": "local pyOCD resource bundle",
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(
        builtin_pack_builder,
        "_read_targets",
        lambda _path: [{"part_number": "DEVICE_A", "vendor": "Vendor"}],
    )

    manifest = builtin_pack_builder.build_bundle(config, [pack_root], tmp_path / "out")

    record = manifest["packs"][0]
    assert record["pack_id"] == "Vendor.Device_DFP"
    assert record["version"] == "1.0.0"
    assert record["provenance"] == "local pyOCD resource bundle"
    with ZipFile(tmp_path / "out" / record["file"]) as archive:
        assert sorted(archive.namelist()) == ["Flash/Test.FLM", "LICENSE.txt", "Vendor.Device_DFP.pdsc"]


def test_builtin_archive_requires_allowlisted_digest_and_descriptor_license(
    builtin_pack_builder, tmp_path,
):
    pack_root = tmp_path / "packs"
    pack_root.mkdir()
    archive_path = pack_root / "Vendor.Unlicensed.1.0.0.pack"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "Vendor.Unlicensed.pdsc",
            '<package><vendor>Vendor</vendor><name>Unlicensed</name>'
            '<releases><release version="1.0.0"/></releases></package>',
        )
    config = tmp_path / "builtin-packs.json"
    config.write_text(json.dumps({
        "schema": 1,
        "packs": [],
        "archives": [{
            "file": archive_path.name,
            "sha256": "0" * 64,
            "redistribution_authorized": True,
            "provenance": "fixture",
        }],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        builtin_pack_builder.build_bundle(config, [pack_root], tmp_path / "bad-hash")

    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["archives"][0]["sha256"] = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    config.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="license"):
        builtin_pack_builder.build_bundle(config, [pack_root], tmp_path / "no-license")


def test_sidecar_collects_generated_builtin_pack_bundle(builder, monkeypatch, tmp_path):
    builder.SKILL_DIR = tmp_path
    builder.TAURI_DIR = tmp_path / "gui" / "src-tauri"
    config = tmp_path / "skills" / "tauri-gui-builder" / "builtin-packs.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"schema":1,"packs":[]}', encoding="utf-8")
    pack_root = tmp_path / "pack-root"
    pack_root.mkdir()
    monkeypatch.setenv("MKLINK_BUILTIN_PACK_ROOTS", str(pack_root))
    generated = []
    commands = []

    def fake_bundle(_config, roots, output):
        generated.append((list(roots), output))
        output.mkdir(parents=True)
        (output / "manifest.json").write_text('{"schema":1,"packs":[]}', encoding="utf-8")
        return {"target_count": 0, "packs": []}

    def fake_run(command, **_kwargs):
        commands.append(command)
        output = tmp_path / "dist" / "mklink-sidecar.exe"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"sidecar")
        return 0

    monkeypatch.setattr(builder, "build_builtin_pack_bundle", fake_bundle)
    monkeypatch.setattr(builder, "run", fake_run)

    assert builder.build_sidecar(force=True) is True

    command = commands[0]
    add_data_index = command.index("--add-data")
    assert command[add_data_index + 1].endswith(";mklink/builtin_packs")
    assert generated[0][0] == [pack_root]
