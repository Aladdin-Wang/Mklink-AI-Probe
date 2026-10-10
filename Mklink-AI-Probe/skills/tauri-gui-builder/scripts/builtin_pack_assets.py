"""One verified SVD/Pack payload for desktop and public Skill packaging."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import urllib.request
from zipfile import ZipFile


def download_sources(project_root: Path, output: Path) -> Path:
    """Fetch only the existing authorized, SHA-256-pinned release inputs."""
    config = json.loads((Path(project_root) / "skills/tauri-gui-builder/builtin-packs.json").read_text(encoding="utf-8"))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)

    def fetch(item):
        name = item["file"]
        if Path(name).name != name or not item["source_url"].startswith("https://"):
            raise ValueError("unsafe built-in Pack source")
        path = output / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]:
            return
        temporary = path.with_suffix(".download")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(item["source_url"], timeout=120) as source, temporary.open("wb") as destination:
                    while data := source.read(1024 * 1024):
                        destination.write(data)
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != item["sha256"]:
                    raise ValueError(f"Pack SHA-256 mismatch: {name}")
                temporary.replace(path)
                return
            except (OSError, ValueError):
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch, config["archives"]))
    return output


def validate_bundle(root: Path) -> dict:
    # Direct builder/release script execution does not put the source root on
    # sys.path. Validate with this checkout's runtime reader, not an installed copy.
    source_root = str(Path(__file__).resolve().parents[3])
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    from mklink.cmsis_dap.builtin_pack_bundle import load_builtin_pack_records
    from mklink.peripheral_watch import pdsc_targets

    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    records = load_builtin_pack_records(root)  # Includes every Pack SHA-256 check.
    if not records:
        raise ValueError("built-in peripheral Pack bundle is empty")
    targets = set()
    for source in sorted({Path(record.pack_path) for record in records}):
        with ZipFile(source) as archive:
            members = set(archive.namelist())
            for name in sorted(members):
                if not name.lower().endswith('.pdsc'):
                    continue
                for target in pdsc_targets(archive.read(name), source, archive=True):
                    # Runtime uses this exact member, so do not merely count PDSC entries.
                    if target.svd not in members:
                        raise ValueError(f"missing SVD for {target.target}: {target.svd}")
                    if not archive.getinfo(target.svd).file_size:
                        raise ValueError(f"empty SVD: {target.svd}")
                    targets.add(target.target)
    if not any(name.upper().startswith("STM32F407VE") for name in targets):
        raise ValueError("built-in peripherals must include STM32F407VE")
    return {**manifest, "svd_target_count": len(targets)}


def prepare_bundle(project_root: Path) -> Path:
    """Require an existing checked payload or build from explicitly configured sources."""
    override = os.environ.get("MKLINK_BUILTIN_PACK_BUNDLE", "").strip()
    existing = Path(override) if override else Path(project_root) / "_maintainer/local/builtin_packs"
    if override or (existing / "manifest.json").is_file():
        validate_bundle(existing)
        return existing
    roots = [Path(item) for item in os.environ.get("MKLINK_BUILTIN_PACK_ROOTS", "").split(os.pathsep) if item]
    if not roots:
        raise RuntimeError(
            "Built-in SVD Packs are required. Set MKLINK_BUILTIN_PACK_BUNDLE to a validated bundle "
            "or MKLINK_BUILTIN_PACK_ROOTS to the checksum-pinned sources in builtin-packs.json."
        )
    script = Path(__file__).with_name("builtin_packs.py")
    spec = importlib.util.spec_from_file_location("mklink_pack_builder", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = Path(os.environ["MKLINK_BUILD_WORK_DIR"]) / "builtin_packs"
    module.build_bundle(Path(project_root) / "skills/tauri-gui-builder/builtin-packs.json", roots, output)
    validate_bundle(output)
    return output
