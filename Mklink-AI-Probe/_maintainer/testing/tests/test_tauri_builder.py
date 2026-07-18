import importlib.util
from pathlib import Path

import pytest


BUILDER_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "tauri-gui-builder"
    / "scripts"
    / "build.py"
)


@pytest.fixture
def builder():
    spec = importlib.util.spec_from_file_location("mklink_tauri_builder", BUILDER_PATH)
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
