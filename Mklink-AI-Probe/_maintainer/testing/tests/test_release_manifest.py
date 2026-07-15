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
    msi = tmp_path / "input.msi"
    nsis = tmp_path / "input.exe"
    report = tmp_path / "full-report.md"
    msi.write_bytes(b"msi")
    nsis.write_bytes(b"exe")
    report.write_text("report", encoding="utf-8")
    return msi, nsis, report


def test_prepare_release_copies_named_assets_and_hashes_them(release_module, tmp_path):
    msi, nsis, report = release_inputs(tmp_path)
    output = tmp_path / "release"

    result = release_module.prepare_release(
        version="v0.1.0-rc.1",
        source_commit="a" * 40,
        output_dir=output,
        msi=msi,
        nsis=nsis,
        report=report,
        evidence=[],
    )

    assert {asset["name"] for asset in result["assets"]} == {
        "Mklink-AI-Probe-v0.1.0-rc.1-x64.msi",
        "Mklink-AI-Probe-v0.1.0-rc.1-x64-Setup.exe",
        "TEST-REPORT.md",
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


def test_prepare_release_rejects_duplicate_output_names(release_module, monkeypatch, tmp_path):
    msi, nsis, report = release_inputs(tmp_path)
    artifact_root = tmp_path / "docs" / "verification" / "artifacts"
    artifact_root.mkdir(parents=True)
    duplicate = artifact_root / "TEST-REPORT.md"
    duplicate.write_text("duplicate", encoding="utf-8")
    monkeypatch.setattr(release_module, "REPO_ROOT", tmp_path)

    with pytest.raises(ValueError, match="duplicate release asset name"):
        release_module.prepare_release(
            version="v0.1.0-rc.1",
            source_commit="a" * 40,
            output_dir=tmp_path / "release",
            msi=msi,
            nsis=nsis,
            report=report,
            evidence=[duplicate],
        )


def test_prepare_release_rejects_missing_inputs(release_module, tmp_path):
    _msi, nsis, report = release_inputs(tmp_path)
    with pytest.raises(FileNotFoundError, match="release input does not exist"):
        release_module.prepare_release(
            version="v0.1.0-rc.1",
            source_commit="a" * 40,
            output_dir=tmp_path / "release",
            msi=tmp_path / "missing.msi",
            nsis=nsis,
            report=report,
            evidence=[],
        )


def test_prepare_release_rejects_evidence_outside_artifact_root(release_module, monkeypatch, tmp_path):
    msi, nsis, report = release_inputs(tmp_path)
    outside = tmp_path / "private-hardware-log.json"
    outside.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(release_module, "REPO_ROOT", tmp_path)

    with pytest.raises(ValueError, match="docs/verification/artifacts"):
        release_module.prepare_release(
            version="v0.1.0-rc.1",
            source_commit="a" * 40,
            output_dir=tmp_path / "release",
            msi=msi,
            nsis=nsis,
            report=report,
            evidence=[outside],
        )
