import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "skill_update.py"


@pytest.fixture
def updater():
    spec = importlib.util.spec_from_file_location("mklink_skill_update", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_root(path: Path, version: str, skill_text: str = "old") -> Path:
    (path / ".claude-plugin").mkdir(parents=True)
    (path / "pyproject.toml").write_text(
        f'[project]\nname = "mklink"\nversion = "{version}"\n', encoding="utf-8"
    )
    (path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "mklink-flash", "version": version}), encoding="utf-8"
    )
    (path / "SKILL.md").write_text(skill_text, encoding="utf-8")
    return path


def make_archive(path: Path, source: Path, prefix: str = "Mklink-AI-Probe-v0.1.3") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for file in source.rglob("*"):
            if file.is_file():
                archive.write(file, f"{prefix}/{file.relative_to(source).as_posix()}")
    return path


def test_version_comparison_handles_stable_and_prerelease(updater):
    assert updater.version_key("0.1.3") > updater.version_key("0.1.2")
    assert updater.version_key("0.1.3") > updater.version_key("0.1.3-rc.1")
    with pytest.raises(ValueError, match="unsupported version"):
        updater.version_key("latest")


def test_check_uses_24_hour_cache_without_hiding_newer_version(
    updater, monkeypatch, tmp_path,
):
    root = make_root(tmp_path / "root", "0.1.2")
    cache = tmp_path / "cache.json"
    manifest = {"version": "0.1.3", "notes": "New release"}
    calls = []
    monkeypatch.setattr(
        updater,
        "fetch_manifest",
        lambda urls: calls.append(tuple(urls)) or (manifest, "https://example/latest.json"),
    )

    first = updater.check_for_update(root=root, cache_file=cache)
    second = updater.check_for_update(root=root, cache_file=cache)

    assert first["update_available"] is True and first["cached"] is False
    assert second["update_available"] is True and second["cached"] is True
    assert len(calls) == 1


def test_extract_rejects_path_traversal(updater, tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("../outside.txt", "bad")
    with pytest.raises(RuntimeError, match="unsafe path"):
        updater.extract_skill_archive(archive, tmp_path / "stage")


def test_copy_installed_skill_is_backed_up_and_replaced(
    updater, monkeypatch, tmp_path,
):
    root = make_root(tmp_path / "installed", "0.1.2")
    source = make_root(tmp_path / "source", "0.1.3", skill_text="new skill")
    archive = make_archive(tmp_path / "skill.zip", source)
    cache = tmp_path / "cache" / "skill-update-check.json"
    monkeypatch.setattr(updater, "default_cache_file", lambda: cache)

    result = updater.install_skill_archive(
        root=root,
        archive_path=archive,
        expected_version="0.1.3",
        source_commit="a" * 40,
    )

    assert updater.current_version(root) == "0.1.3"
    assert (root / "SKILL.md").read_text(encoding="utf-8") == "new skill"
    assert Path(result["backup"]).is_file()
    marker = json.loads((root / ".mklink-skill-install.json").read_text(encoding="utf-8"))
    assert marker["version"] == "0.1.3"
    assert marker["source_commit"] == "a" * 40


def test_git_checkout_is_never_overwritten(updater, tmp_path):
    root = make_root(tmp_path / "checkout", "0.1.2")
    (root / ".git").mkdir()
    source = make_root(tmp_path / "source", "0.1.3")
    archive = make_archive(tmp_path / "skill.zip", source)

    with pytest.raises(RuntimeError, match="Git checkout"):
        updater.install_skill_archive(
            root=root,
            archive_path=archive,
            expected_version="0.1.3",
            source_commit="a" * 40,
        )


def test_desktop_update_is_not_skipped_when_skill_is_already_current(
    updater, monkeypatch, tmp_path,
):
    root = make_root(tmp_path / "installed", "0.1.3")
    observed = []
    monkeypatch.setattr(updater, "_installed_app", lambda: (tmp_path / "app", "0.1.2"))
    monkeypatch.setattr(
        updater,
        "download_verified",
        lambda url, destination, sha256, size: destination.write_bytes(b"installer"),
    )
    monkeypatch.setattr(
        updater,
        "install_desktop",
        lambda installer: observed.append(installer) or {"installed": True},
    )
    manifest = {
        "version": "0.1.3",
        "platforms": {
            "windows-x86_64": {
                "url": "https://example/setup.exe",
                "sha256": "a" * 64,
                "size": 9,
            }
        },
    }

    result = updater.install_update(
        root=root, manifest=manifest, install_skill=True, install_app=True,
    )

    assert result["status"] == "updated"
    assert result["desktop"] == {"installed": True}
    assert len(observed) == 1
    assert "skill" not in result


def test_skill_instructions_require_proactive_check_and_user_approval():
    text = (SCRIPT_PATH.parents[1] / "SKILL.md").read_text(encoding="utf-8")
    assert "skill_update.py check --json" in text
    assert "install --yes --json" in text
    assert "只有用户明确同意后" in text
