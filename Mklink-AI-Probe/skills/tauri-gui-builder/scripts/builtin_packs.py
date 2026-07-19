#!/usr/bin/env python3
"""Build deterministic slim CMSIS-Pack archives for the bundled sidecar."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Mapping, Sequence
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def _text(value: object, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be a non-empty string".format(description))
    return value.strip()


def _relative_path(value: object, description: str) -> PurePosixPath:
    text = _text(value, description).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or ":" in text:
        raise ValueError("{} must be a safe relative path".format(description))
    return path


def _source_directory(pack_roots: Sequence[Path], pack_id: str, version: str) -> Path:
    if pack_id.count(".") != 1:
        raise ValueError("pack_id must contain vendor and pack name")
    vendor, pack_name = pack_id.split(".", 1)
    for root in pack_roots:
        candidate = Path(root) / vendor / pack_name / version
        if candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError("required builtin Pack {}@{} is not installed".format(pack_id, version))


def _descriptor(source: Path) -> Path:
    descriptors = list(source.glob("*.pdsc"))
    if len(descriptors) != 1:
        raise ValueError("builtin Pack must contain exactly one root PDSC")
    return descriptors[0]


def _pack_files(source: Path, descriptor: Path, license_files: object) -> List[PurePosixPath]:
    try:
        root = ElementTree.parse(str(descriptor)).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise ValueError("builtin Pack descriptor is invalid: {}".format(error))
    files = {PurePosixPath(descriptor.name)}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "algorithm":
            continue
        name = element.attrib.get("name")
        if name:
            files.add(_relative_path(name, "algorithm path"))
    if not isinstance(license_files, list) or not license_files:
        raise ValueError("builtin Pack must declare license_files")
    for value in license_files:
        files.add(_relative_path(value, "license path"))
    ordered = sorted(files, key=lambda value: value.as_posix().casefold())
    for relative in ordered:
        candidate = source.joinpath(*relative.parts)
        if not candidate.is_file():
            raise FileNotFoundError("required builtin Pack file is missing: {}".format(relative))
    return ordered


def _zip_entry(name: str, data: bytes) -> ZipInfo:
    entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = ZIP_DEFLATED
    entry.external_attr = 0o100644 << 16
    entry.create_system = 3
    return entry


def _write_slim_pack(source: Path, files: Iterable[PurePosixPath], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w") as archive:
        for relative in files:
            data = source.joinpath(*relative.parts).read_bytes()
            archive.writestr(_zip_entry(relative.as_posix(), data), data)


def _read_targets(pack_path: Path) -> List[Dict[str, str]]:
    from pyocd.target.pack.cmsis_pack import CmsisPack

    pack = CmsisPack(str(pack_path))
    try:
        records = {
            str(device.part_number).casefold(): {
                "part_number": str(device.part_number),
                "vendor": str(device.vendor or ""),
            }
            for device in pack.devices
            if getattr(device, "part_number", None)
        }
    finally:
        pack_file = getattr(pack, "_pack_file", None)
        if hasattr(pack_file, "close"):
            pack_file.close()
    return sorted(records.values(), key=lambda value: value["part_number"].casefold())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_bundle(config_path: Path, pack_roots: Sequence[Path], output: Path) -> Dict[str, object]:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(config, Mapping) or config.get("schema") != 1:
        raise ValueError("builtin Pack configuration schema is unsupported")
    packs = config.get("packs")
    if not isinstance(packs, list):
        raise ValueError("builtin Pack configuration must contain a packs list")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest_packs = []  # type: List[Dict[str, object]]
    target_count = 0
    for raw_pack in packs:
        if not isinstance(raw_pack, Mapping):
            raise ValueError("builtin Pack configuration entry must be an object")
        pack_id = _text(raw_pack.get("pack_id"), "pack_id")
        version = _text(raw_pack.get("version"), "version")
        source = _source_directory(pack_roots, pack_id, version)
        descriptor = _descriptor(source)
        files = _pack_files(source, descriptor, raw_pack.get("license_files"))
        file_name = "{}.{}.pack".format(pack_id, version)
        relative_output = PurePosixPath("packs") / file_name
        slim_pack = output.joinpath(*relative_output.parts)
        _write_slim_pack(source, files, slim_pack)
        targets = _read_targets(slim_pack)
        if not targets:
            raise ValueError("builtin Pack {} has no devices".format(pack_id))
        target_count += len(targets)
        manifest_packs.append({
            "pack_id": pack_id,
            "version": version,
            "file": relative_output.as_posix(),
            "sha256": _sha256(slim_pack),
            "targets": targets,
        })
    manifest = {
        "schema": 1,
        "target_count": target_count,
        "packs": manifest_packs,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
