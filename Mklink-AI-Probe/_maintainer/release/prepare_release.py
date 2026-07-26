"""Prepare sanitized, checksummed MKLink release assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_versions() -> dict[str, str]:
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python 3.9/3.10 fallback
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            tomllib = None  # type: ignore[assignment]

    python_package = "unknown"
    if tomllib is not None:
        with (REPO_ROOT / "pyproject.toml").open("rb") as stream:
            python_package = str(tomllib.load(stream)["project"]["version"])
    tauri_config = json.loads(
        (REPO_ROOT / "gui" / "src-tauri" / "tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        "python_package": python_package,
        "tauri": str(tauri_config["version"]),
        "build_python": platform.python_version(),
    }


def _require_file(value: Path | str) -> Path:
    path = Path(value).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"release input does not exist: {path.name}")
    return path


def _validate_skill_archive(path: Path, version: str) -> None:
    with zipfile.ZipFile(path) as archive:
        files = {
            PurePosixPath(info.filename)
            for info in archive.infolist()
            if not info.is_dir()
        }
        if not files or any(
            member.is_absolute() or ".." in member.parts for member in files
        ):
            raise ValueError("Skill archive contains an unsafe or empty layout")
        roots = {member.parts[0] for member in files if member.parts}
        if len(roots) != 1:
            raise ValueError("Skill archive must contain exactly one root directory")
        root = next(iter(roots))
        required = {
            PurePosixPath(root, "pyproject.toml"),
            PurePosixPath(root, "SKILL.md"),
            PurePosixPath(root, ".claude-plugin", "plugin.json"),
            PurePosixPath(root, "scripts", "skill_update.py"),
        }
        if not required <= files:
            raise ValueError(
                "Skill archive root must directly contain the installable project"
            )
        plugin_path = PurePosixPath(root, ".claude-plugin", "plugin.json")
        plugin = json.loads(archive.read(str(plugin_path)))
        if str(plugin.get("version")) != version:
            raise ValueError("Skill archive plugin version does not match the release")


def prepare_release(
    *,
    version: str,
    source_commit: str,
    output_dir: Path | str,
    nsis: Path | str,
    updater_signature: Path | str,
    skill_archive: Path | str,
) -> dict[str, object]:
    if not version or any(separator in version for separator in ("/", "\\")):
        raise ValueError("release version must be a path-safe value")
    if len(source_commit) != 40 or any(
        character not in "0123456789abcdefABCDEF" for character in source_commit
    ):
        raise ValueError("source commit must be a 40-character hexadecimal SHA")

    skill_source = _require_file(skill_archive)
    _validate_skill_archive(skill_source, version)
    sources = [
        (_require_file(nsis), f"Mklink-AI-Probe-v{version}-x64-Setup.exe"),
        (
            _require_file(updater_signature),
            f"Mklink-AI-Probe-v{version}-x64-Setup.exe.sig",
        ),
        (
            skill_source,
            f"Mklink-AI-Probe-v{version}-Skill.zip",
        ),
    ]

    names: set[str] = set()
    for _source, name in sources:
        folded = name.casefold()
        if folded in names:
            raise ValueError(f"duplicate release asset name: {name}")
        names.add(folded)

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    assets = []
    for source, name in sorted(sources, key=lambda item: item[1].casefold()):
        destination = output / name
        shutil.copy2(source, destination)
        assets.append(
            {
                "name": name,
                "size": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )

    manifest: dict[str, object] = {
        "schema_version": 1,
        "release_version": version,
        "source_commit": source_commit.lower(),
        "build_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "versions": _source_versions(),
        "assets": assets,
    }
    (output / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    checksum_lines = [
        f'{asset["sha256"]}  {asset["name"]}'
        for asset in sorted(assets, key=lambda item: str(item["name"]).casefold())
    ]
    (output / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n", encoding="ascii"
    )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--nsis", required=True, type=Path)
    parser.add_argument("--updater-signature", required=True, type=Path)
    parser.add_argument("--skill-archive", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = prepare_release(
        version=args.version,
        source_commit=args.source_commit,
        output_dir=args.output,
        nsis=args.nsis,
        updater_signature=args.updater_signature,
        skill_archive=args.skill_archive,
    )
    print(json.dumps({
        "release_version": manifest["release_version"],
        "asset_count": len(manifest["assets"]),
        "output": str(args.output.resolve()),
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
