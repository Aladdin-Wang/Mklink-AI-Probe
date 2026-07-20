import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "release"
    / "prepare_release.py"
)


@pytest.fixture
def release_module():
    spec = importlib.util.spec_from_file_location("mklink_prepare_release", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_inputs(tmp_path):
    nsis = tmp_path / "input.exe"
    signature = tmp_path / "input.exe.sig"
    nsis.write_bytes(b"exe")
    signature.write_text("signature", encoding="ascii")
    return nsis, signature


def test_prepare_release_copies_named_assets_and_hashes_them(release_module, tmp_path):
    nsis, signature = release_inputs(tmp_path)
    output = tmp_path / "release"

    result = release_module.prepare_release(
        version="0.1.0",
        source_commit="a" * 40,
        output_dir=output,
        nsis=nsis,
        updater_signature=signature,
    )

    assert {asset["name"] for asset in result["assets"]} == {
        "Mklink-AI-Probe-v0.1.0-x64-Setup.exe",
        "Mklink-AI-Probe-v0.1.0-x64-Setup.exe.sig",
    }
    assert all(len(asset["sha256"]) == 64 for asset in result["assets"])
    assert all(set(asset) == {"name", "size", "sha256"} for asset in result["assets"])
    assert (output / "release-manifest.json").is_file()
    assets_by_name = sorted(result["assets"], key=lambda asset: asset["name"].casefold())
    assert (output / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines() == [
        f'{asset["sha256"]}  {asset["name"]}' for asset in assets_by_name
    ]
    manifest_text = (output / "release-manifest.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in manifest_text
    assert json.loads(manifest_text) == result


def test_prepare_release_rejects_missing_inputs(release_module, tmp_path):
    _nsis, signature = release_inputs(tmp_path)
    with pytest.raises(FileNotFoundError, match="release input does not exist"):
        release_module.prepare_release(
            version="0.1.0",
            source_commit="a" * 40,
            output_dir=tmp_path / "release",
            nsis=tmp_path / "missing.exe",
            updater_signature=signature,
        )
