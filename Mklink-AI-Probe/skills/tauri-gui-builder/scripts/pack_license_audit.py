#!/usr/bin/env python3
"""Audit CMSIS-Pack license evidence without modifying source archives."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Mapping, Sequence, Tuple
from xml.etree import ElementTree
from zipfile import ZipFile


@dataclass(frozen=True)
class PackAudit:
    file_name: str
    pack_id: str
    version: str
    source_url: str
    sha256: str
    classification: str
    license_files: Tuple[str, ...]
    missing_license_files: Tuple[str, ...]
    referenced_algorithms: Tuple[str, ...]
    target_count: int
    source_bytes: int
    slim_file_count: int
    slim_uncompressed_bytes: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AuditReport:
    records: Tuple[PackAudit, ...]

    @property
    def counts(self) -> Dict[str, int]:
        return dict(sorted(Counter(record.classification for record in self.records).items()))

    def to_dict(self) -> Dict[str, object]:
        return {
            "counts": self.counts,
            "records": [record.to_dict() for record in self.records],
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _local_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _element_text(root: ElementTree.Element, name: str) -> str:
    for element in root.iter():
        if _local_name(element) == name and element.text and element.text.strip():
            return element.text.strip()
    return ""


def _safe_relative(value: object, description: str) -> PurePosixPath:
    text = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts or ":" in text:
        raise ValueError("{} must be a safe relative path".format(description))
    return path


def _descriptor_name(names: Iterable[str]) -> PurePosixPath:
    descriptors = [PurePosixPath(name) for name in names if name.casefold().endswith(".pdsc")]
    if len(descriptors) != 1:
        raise ValueError("Pack archive must contain exactly one PDSC")
    return descriptors[0]


def _version(root: ElementTree.Element) -> str:
    for element in root.iter():
        if _local_name(element) == "release" and element.attrib.get("version"):
            return str(element.attrib["version"]).strip()
    raise ValueError("Pack descriptor has no release version")


def _target_count(path: Path) -> int:
    from pyocd.target.pack.cmsis_pack import CmsisPack

    pack = CmsisPack(str(path))
    try:
        return len({str(device.part_number).casefold() for device in pack.devices})
    finally:
        pack_file = getattr(pack, "_pack_file", None)
        if hasattr(pack_file, "close"):
            pack_file.close()


def audit_pack(path: Path) -> PackAudit:
    source = Path(path)
    if not source.is_file() or source.suffix.casefold() != ".pack":
        raise ValueError("audit source must be an existing .pack archive")
    with ZipFile(source) as archive:
        infos = {info.filename.replace("\\", "/"): info for info in archive.infolist()}
        descriptor = _descriptor_name(infos)
        try:
            root = ElementTree.fromstring(archive.read(descriptor.as_posix()))
        except (KeyError, ElementTree.ParseError) as error:
            raise ValueError("Pack descriptor is invalid: {}".format(error)) from error

        vendor = _element_text(root, "vendor")
        name = _element_text(root, "name")
        if not vendor or not name:
            raise ValueError("Pack descriptor must declare vendor and name")

        present_licenses = []
        missing_licenses = []
        algorithms = []
        descriptor_parent = descriptor.parent
        for element in root.iter():
            local_name = _local_name(element)
            if local_name == "license" and element.text and element.text.strip():
                relative = descriptor_parent / _safe_relative(
                    element.text, "descriptor license path"
                )
                if relative.as_posix() in infos:
                    present_licenses.append(relative.as_posix())
                else:
                    missing_licenses.append(relative.as_posix())
            elif local_name == "algorithm" and element.attrib.get("name"):
                relative = descriptor_parent / _safe_relative(
                    element.attrib["name"], "algorithm path"
                )
                if relative.as_posix() in infos:
                    algorithms.append(relative.as_posix())

        present = tuple(sorted(set(present_licenses), key=str.casefold))
        missing = tuple(sorted(set(missing_licenses), key=str.casefold))
        algorithm_files = tuple(sorted(set(algorithms), key=str.casefold))
        if present and not missing:
            classification = "declared-present"
        elif present or missing:
            classification = "declared-missing"
        else:
            classification = "no-license-evidence"
        selected = {descriptor.as_posix(), *present, *algorithm_files}
        slim_bytes = sum(infos[file_name].file_size for file_name in selected)

    return PackAudit(
        file_name=source.name,
        pack_id="{}.{}".format(vendor, name),
        version=_version(root),
        source_url=_element_text(root, "url"),
        sha256=_sha256(source),
        classification=classification,
        license_files=present,
        missing_license_files=missing,
        referenced_algorithms=algorithm_files,
        target_count=_target_count(source),
        source_bytes=source.stat().st_size,
        slim_file_count=len(selected),
        slim_uncompressed_bytes=slim_bytes,
    )


def audit_root(root: Path) -> AuditReport:
    directory = Path(root)
    if not directory.is_dir():
        raise ValueError("audit root must be an existing directory")
    records = tuple(
        audit_pack(path)
        for path in sorted(directory.glob("*.pack"), key=lambda value: value.name.casefold())
    )
    return AuditReport(records)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = json.dumps(audit_root(args.root).to_dict(), indent=2, sort_keys=True) + "\n"
    if args.json_out is None:
        print(payload, end="")
    else:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
