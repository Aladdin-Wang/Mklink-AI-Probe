"""Prepare sanitized, checksummed MKLink release assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


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


def _validate_evidence(paths: Iterable[Path | str]) -> list[Path]:
    artifact_root = (REPO_ROOT / "docs" / "verification" / "artifacts").resolve()
    result = []
    for value in paths:
        path = _require_file(value)
        if not path.is_relative_to(artifact_root):
            raise ValueError(
                "release evidence must be inside docs/verification/artifacts"
            )
        result.append(path)
    return result


def prepare_release(
    *,
    version: str,
    source_commit: str,
    output_dir: Path | str,
    msi: Path | str,
    nsis: Path | str,
    report: Path | str,
    evidence: Sequence[Path | str],
) -> dict[str, object]:
    if not version or any(separator in version for separator in ("/", "\\")):
        raise ValueError("release version must be a path-safe value")
    if len(source_commit) != 40 or any(
        character not in "0123456789abcdefABCDEF" for character in source_commit
    ):
        raise ValueError("source commit must be a 40-character hexadecimal SHA")

    sources = [
        (_require_file(msi), f"Mklink-AI-Probe-{version}-x64.msi", False),
        (_require_file(nsis), f"Mklink-AI-Probe-{version}-x64-Setup.exe", False),
        (_require_file(report), "TEST-REPORT.md", False),
    ]
    sources.extend((path, path.name, True) for path in _validate_evidence(evidence))

    names: set[str] = set()
    for _source, name, _is_evidence in sources:
        folded = name.casefold()
        if folded in names:
            raise ValueError(f"duplicate release asset name: {name}")
        names.add(folded)

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    assets = []
    evidence_names = []
    for source, name, is_evidence in sorted(sources, key=lambda item: item[1].casefold()):
        destination = output / name
        shutil.copy2(source, destination)
        assets.append(
            {
                "name": name,
                "size": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )
        if is_evidence:
            evidence_names.append(name)

    manifest: dict[str, object] = {
        "schema_version": 1,
        "release_version": version,
        "source_commit": source_commit.lower(),
        "build_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "versions": _source_versions(),
        "assets": assets,
        "evidence": sorted(evidence_names, key=str.casefold),
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
    parser.add_argument("--msi", required=True, type=Path)
    parser.add_argument("--nsis", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--evidence", action="append", default=[], type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = prepare_release(
        version=args.version,
        source_commit=args.source_commit,
        output_dir=args.output,
        msi=args.msi,
        nsis=args.nsis,
        report=args.report,
        evidence=args.evidence,
    )
    print(json.dumps({
        "release_version": manifest["release_version"],
        "asset_count": len(manifest["assets"]),
        "output": str(args.output.resolve()),
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
