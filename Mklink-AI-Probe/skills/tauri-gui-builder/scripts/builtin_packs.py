#!/usr/bin/env python3
"""Build deterministic slim CMSIS-Pack archives for the bundled sidecar."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Dict, Iterable, List, Mapping, Sequence
from urllib.parse import urlsplit
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


def _source_archive(pack_roots: Sequence[Path], value: object) -> Path:
    relative = _relative_path(value, "archive file")
    for root in pack_roots:
        candidate = Path(root).joinpath(*relative.parts)
        if candidate.is_file() and candidate.suffix.casefold() == ".pack":
            return candidate.resolve()
    raise FileNotFoundError("required builtin Pack archive {} is unavailable".format(relative))


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


def _archive_descriptor(archive: ZipFile) -> PurePosixPath:
    descriptors = [
        PurePosixPath(name.replace("\\", "/"))
        for name in archive.namelist()
        if name.casefold().endswith(".pdsc")
    ]
    if len(descriptors) != 1:
        raise ValueError("builtin Pack archive must contain exactly one PDSC")
    return descriptors[0]


def _archive_metadata(
    source: Path,
    metadata: Mapping[str, object],
) -> tuple[str, str, List[PurePosixPath], Dict[str, object]]:
    if metadata.get("redistribution_authorized") is not True:
        raise ValueError("builtin Pack archive requires explicit redistribution_authorized=true")
    source_url = _text(metadata.get("source_url"), "archive source_url")
    parsed_url = urlsplit(source_url)
    if parsed_url.scheme.casefold() != "https" or not parsed_url.netloc:
        raise ValueError("archive source_url must use HTTPS")
    redistribution_basis = _text(
        metadata.get("redistribution_basis"), "archive redistribution basis"
    )
    raw_license_files = metadata.get("license_files")
    if not isinstance(raw_license_files, list) or not raw_license_files:
        raise ValueError("archive license_files must be a non-empty list")
    configured_licenses = {}
    for raw_license in raw_license_files:
        if not isinstance(raw_license, Mapping):
            raise ValueError("archive license_files entries must be objects")
        relative = _relative_path(raw_license.get("path"), "archive license path")
        digest = _text(raw_license.get("sha256"), "archive license SHA-256").casefold()
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("archive license SHA-256 must contain 64 hexadecimal characters")
        if relative.as_posix() in configured_licenses:
            raise ValueError("archive license paths must be unique")
        configured_licenses[relative.as_posix()] = digest
    with ZipFile(source) as archive:
        descriptor = _archive_descriptor(archive)
        try:
            root = ElementTree.fromstring(archive.read(descriptor.as_posix()))
        except (KeyError, ElementTree.ParseError) as error:
            raise ValueError("builtin Pack archive descriptor is invalid: {}".format(error))
        vendor = _text(root.findtext("vendor"), "archive vendor")
        name = _text(root.findtext("name"), "archive name")
        release = root.find("./releases/release")
        version = _text(
            release.attrib.get("version") if release is not None else None,
            "archive version",
        )
        files = {descriptor}
        archive_names = {name.replace("\\", "/") for name in archive.namelist()}
        descriptor_licenses = []
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == "license" and element.text:
                descriptor_licenses.append(
                    descriptor.parent / _relative_path(
                        element.text, "archive descriptor license path"
                    )
                )
        if not descriptor_licenses:
            raise ValueError("builtin Pack archive descriptor must declare a license file")
        files.update(descriptor_licenses)
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "algorithm":
                continue
            algorithm = element.attrib.get("name")
            if algorithm:
                relative = descriptor.parent / _relative_path(
                    algorithm,
                    "archive algorithm path",
                )
                if relative.as_posix() in archive_names:
                    files.add(relative)
        declared_names = {relative.as_posix() for relative in descriptor_licenses}
        if not declared_names.issubset(configured_licenses):
            raise ValueError("every descriptor license must be pinned in archive license_files")
        for relative_name, expected_digest in configured_licenses.items():
            relative = descriptor.parent / PurePosixPath(relative_name)
            files.add(relative)
            if relative.as_posix() not in archive_names:
                raise FileNotFoundError(
                    "required builtin Pack archive file is missing: {}".format(relative)
                )
            actual_digest = hashlib.sha256(archive.read(relative.as_posix())).hexdigest()
            if actual_digest != expected_digest:
                raise ValueError("archive license SHA-256 does not match the allowlist")
        for relative in files:
            if relative.as_posix() not in archive_names:
                raise FileNotFoundError(
                    "required builtin Pack archive file is missing: {}".format(relative)
                )
    license_records = [
        {"path": path, "sha256": digest}
        for path, digest in sorted(configured_licenses.items(), key=lambda item: item[0].casefold())
    ]
    return (
        "{}.{}".format(vendor, name),
        version,
        sorted(files, key=lambda value: value.as_posix().casefold()),
        {
            "source_url": source_url,
            "redistribution_basis": redistribution_basis,
            "licenses": license_records,
        },
    )


def _write_slim_archive(
    source: Path,
    files: Iterable[PurePosixPath],
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(source) as input_archive, ZipFile(output, "w") as output_archive:
        for relative in files:
            data = input_archive.read(relative.as_posix())
            output_archive.writestr(_zip_entry(relative.as_posix(), data), data)


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
    archives = config.get("archives", [])
    if not isinstance(archives, list):
        raise ValueError("builtin Pack configuration archives must be a list")
    archive_sets = config.get("archive_sets", [])
    if archive_sets not in (None, []):
        raise ValueError("builtin Pack archive_sets are unsupported; use explicit digest-pinned archives")
    archives = list(archives)
    archives.sort(
        key=lambda value: str(value.get("file", "")).casefold()
        if isinstance(value, Mapping) else "",
        reverse=True,
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest_packs = []  # type: List[Dict[str, object]]
    target_count = 0
    seen_pack_ids = set()
    for raw_pack in packs:
        if not isinstance(raw_pack, Mapping):
            raise ValueError("builtin Pack configuration entry must be an object")
        pack_id = _text(raw_pack.get("pack_id"), "pack_id")
        if pack_id.casefold() in seen_pack_ids:
            raise ValueError("builtin Pack ids must be unique")
        seen_pack_ids.add(pack_id.casefold())
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
    for raw_archive in archives:
        if not isinstance(raw_archive, Mapping):
            raise ValueError("builtin Pack archive entry must be an object")
        provenance = _text(raw_archive.get("provenance"), "archive provenance")
        source = _source_archive(pack_roots, raw_archive.get("file"))
        expected_digest = _text(raw_archive.get("sha256"), "archive SHA-256").casefold()
        if re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
            raise ValueError("archive SHA-256 must contain 64 hexadecimal characters")
        if _sha256(source) != expected_digest:
            raise ValueError("archive SHA-256 does not match the allowlist")
        pack_id, version, files, public_metadata = _archive_metadata(source, raw_archive)
        if not any(path.suffix.casefold() == ".flm" for path in files):
            continue
        if pack_id.casefold() in seen_pack_ids:
            continue
        seen_pack_ids.add(pack_id.casefold())
        file_name = "{}.{}.pack".format(pack_id, version)
        relative_output = PurePosixPath("packs") / file_name
        slim_pack = output.joinpath(*relative_output.parts)
        _write_slim_archive(source, files, slim_pack)
        targets = _read_targets(slim_pack)
        if not targets:
            raise ValueError("builtin Pack {} has no devices".format(pack_id))
        target_count += len(targets)
        manifest_packs.append({
            "pack_id": pack_id,
            "version": version,
            "file": relative_output.as_posix(),
            "sha256": _sha256(slim_pack),
            "source_sha256": expected_digest,
            "targets": targets,
            "provenance": provenance,
            **public_metadata,
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
