#!/usr/bin/env python3
"""Extract the pinned DAPLinkUtility Qt resources into a compact FLM bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
from typing import Callable, Mapping, Sequence
import zlib


SUPPORTED_SOURCE_SHA256 = "419e1a830fb66ccb5db5c748e6085dd1778e2289c0b211ea92a84ec214656c33"
_TREE_ENTRY_SIZE = 22
_FLAG_COMPRESSED = 0x01
_FLAG_DIRECTORY = 0x02
_FLAG_COMPRESSED_ZSTD = 0x04
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class QtResourceReader:
    """Read the tree/name/data arrays passed to qRegisterResourceData v3."""

    def __init__(self, tree: bytes, names: bytes, data: bytes) -> None:
        self._tree = bytes(tree)
        self._names = bytes(names)
        self._data = bytes(data)

    def _entry(self, index: int) -> tuple[int, int, int, int]:
        offset = index * _TREE_ENTRY_SIZE
        if index < 0 or offset + _TREE_ENTRY_SIZE > len(self._tree):
            raise ValueError("Qt resource tree entry is out of bounds")
        name_offset, flags = struct.unpack_from(">IH", self._tree, offset)
        first, second = struct.unpack_from(">II", self._tree, offset + 6)
        return name_offset, flags, first, second

    def _name(self, offset: int) -> str:
        if offset < 0 or offset + 6 > len(self._names):
            raise ValueError("Qt resource name is out of bounds")
        length = struct.unpack_from(">H", self._names, offset)[0]
        end = offset + 6 + length * 2
        if end > len(self._names):
            raise ValueError("Qt resource name is truncated")
        try:
            value = self._names[offset + 6:end].decode("utf-16-be")
        except UnicodeDecodeError as error:
            raise ValueError("Qt resource name is invalid") from error
        if not value or "/" in value or "\\" in value or value in (".", ".."):
            raise ValueError("Qt resource name is unsafe")
        return value

    def _payload(self, offset: int, flags: int) -> bytes:
        if offset < 0 or offset + 4 > len(self._data):
            raise ValueError("Qt resource data offset is out of bounds")
        size = struct.unpack_from(">I", self._data, offset)[0]
        start = offset + 4
        end = start + size
        if end > len(self._data):
            raise ValueError("Qt resource data is truncated")
        payload = self._data[start:end]
        if flags & _FLAG_COMPRESSED_ZSTD:
            raise ValueError("Qt zstd resources are unsupported")
        if flags & _FLAG_COMPRESSED:
            if len(payload) < 5:
                raise ValueError("Qt compressed resource is truncated")
            expected_size = struct.unpack_from(">I", payload, 0)[0]
            try:
                payload = zlib.decompress(payload[4:])
            except zlib.error as error:
                raise ValueError("Qt compressed resource is invalid") from error
            if len(payload) != expected_size:
                raise ValueError("Qt compressed resource size does not match")
        return payload

    def files(self) -> dict[str, bytes]:
        result: dict[str, bytes] = {}
        active: set[int] = set()

        def walk(index: int, parents: tuple[str, ...], *, root: bool = False) -> None:
            if index in active:
                raise ValueError("Qt resource tree contains a cycle")
            active.add(index)
            name_offset, flags, first, second = self._entry(index)
            try:
                if flags & _FLAG_DIRECTORY:
                    current = parents if root else parents + (self._name(name_offset),)
                    child_count, child_offset = first, second
                    if child_count > len(self._tree) // _TREE_ENTRY_SIZE:
                        raise ValueError("Qt resource tree child count is invalid")
                    for child in range(child_offset, child_offset + child_count):
                        walk(child, current)
                else:
                    name = self._name(name_offset)
                    path = "/".join(parents + (name,))
                    if path in result:
                        raise ValueError("Qt resource tree contains a duplicate path")
                    result[path] = self._payload(second, flags)
            finally:
                active.remove(index)

        walk(0, (), root=True)
        return dict(sorted(result.items(), key=lambda item: item[0].casefold()))


def _safe_algorithm_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("algorithm must be a non-empty safe resource name")
    text = value.strip().replace("\\", "/")
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or len(path.parts) != 1
        or path.name != text
        or path.suffix.casefold() != ".flm"
        or ":" in text
        or text in (".", "..")
    ):
        raise ValueError("algorithm must be a safe resource name")
    return text


def _text(value: object, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be a non-empty string".format(description))
    return value.strip()


def _address(value: object, description: str) -> int:
    if isinstance(value, bool):
        raise ValueError("{} must be an integer".format(description))
    try:
        result = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("{} must be an integer".format(description)) from error
    if not 0 <= result <= 0xFFFFFFFF:
        raise ValueError("{} must fit in 32 bits".format(description))
    return result


def _resource_algorithms(resources: Mapping[str, bytes]) -> dict[str, tuple[str, bytes]]:
    algorithms: dict[str, tuple[str, bytes]] = {}
    for path, payload in resources.items():
        normalized = str(path).replace("\\", "/")
        if not normalized.casefold().startswith("resources/algorithms/"):
            continue
        if PurePosixPath(normalized).suffix.casefold() != ".flm":
            continue
        name = _safe_algorithm_name(PurePosixPath(normalized).name)
        key = name.casefold()
        previous = algorithms.get(key)
        if previous is not None and previous[1] != payload:
            raise ValueError("conflicting DAPLinkUtility FLM resource names")
        algorithms[key] = (name, bytes(payload))
    return algorithms


def _flm_metadata(payload: bytes) -> dict[str, object] | None:
    from pyocd.target.pack.flash_algo import PackFlashAlgo

    try:
        parsed = PackFlashAlgo(io.BytesIO(payload))
        start = int(parsed.flash_start)
        size = int(parsed.flash_size)
        if start < 0 or size <= 0 or start + size > 0x1_0000_0000:
            return None
        return {
            "flash_start": start,
            "flash_size": size,
            "page_size": int(parsed.page_size),
            "sector_sizes": [
                [int(offset), int(sector_size)]
                for offset, sector_size in parsed.sector_sizes
            ],
        }
    except Exception:
        return None


def build_bundle_from_resources(
    resources: Mapping[str, bytes],
    output: Path,
    *,
    source_sha256: str,
    metadata_parser: Callable[[bytes], Mapping[str, object] | None] = _flm_metadata,
) -> dict[str, object]:
    digest = str(source_sha256).casefold()
    if _SHA256.fullmatch(digest) is None:
        raise ValueError("source SHA-256 is invalid")
    chips_paths = [path for path in resources if str(path).replace("\\", "/").casefold() in (
        "resources/chips.json", "resources/algorithms/chips.json",
    )]
    if len(chips_paths) != 1:
        raise ValueError("DAPLinkUtility chips.json resource is unavailable")
    try:
        catalog = json.loads(bytes(resources[chips_paths[0]]).decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("DAPLinkUtility chips.json is invalid") from error
    if not isinstance(catalog, Mapping):
        raise ValueError("DAPLinkUtility chips.json must be an object")

    available = _resource_algorithms(resources)
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("builtin FLM bundle output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    blobs_root = output / "blobs"
    referenced: set[str] = set()
    written_blobs: dict[str, dict[str, object]] = {}
    parsed_metadata: dict[str, Mapping[str, object] | None] = {}
    targets = []

    def algorithm_record(raw_name: object, start: int | None = None, size: int | None = None):
        requested = _safe_algorithm_name(raw_name)
        key = requested.casefold()
        if key not in available:
            raise ValueError("referenced FLM resource is missing: {}".format(requested))
        stored_name, payload = available[key]
        referenced.add(key)
        payload_digest = _sha256_bytes(payload)
        relative = "blobs/{}/{}.flm".format(payload_digest[:2], payload_digest)
        if payload_digest not in written_blobs:
            destination = output / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            written_blobs[payload_digest] = {
                "file": relative,
                "sha256": payload_digest,
                "size": len(payload),
            }
        record: dict[str, object] = {
            "file_name": stored_name,
            "sha256": payload_digest,
            "blob": relative,
        }
        if start is not None and size is not None:
            if payload_digest not in parsed_metadata:
                parsed_metadata[payload_digest] = metadata_parser(payload)
            metadata = parsed_metadata[payload_digest]
            usable = size > 0 and start + size <= 0x1_0000_0000
            if not usable:
                if metadata is not None:
                    start = _address(metadata.get("flash_start"), "FLM flash start")
                    size = _address(metadata.get("flash_size"), "FLM flash size")
                    usable = True
            record.update({
                "flash_start": start if usable else 0,
                "flash_size": size if usable else 0,
                "automatic": usable,
                "page_size": _address(metadata.get("page_size"), "FLM page size")
                if metadata is not None else 0,
                "sector_sizes": metadata.get("sector_sizes", [])
                if metadata is not None else [],
            })
        return record

    for raw_manufacturer, raw_series in catalog.items():
        manufacturer = _text(raw_manufacturer, "manufacturer")
        if not isinstance(raw_series, Mapping):
            raise ValueError("manufacturer series must be an object")
        for raw_series_name, raw_models in raw_series.items():
            series = _text(raw_series_name, "series")
            if not isinstance(raw_models, Mapping):
                raise ValueError("series models must be an object")
            for raw_part, raw_target in raw_models.items():
                part_number = _text(raw_part, "part number")
                if not isinstance(raw_target, Mapping):
                    raise ValueError("target metadata must be an object")
                raw_regions = raw_target.get("algoprog")
                if not isinstance(raw_regions, list) or not raw_regions:
                    raise ValueError("target algoprog must be a non-empty list")
                regions = []
                for raw_region in raw_regions:
                    if not isinstance(raw_region, Mapping):
                        raise ValueError("target algorithm region must be an object")
                    regions.append(algorithm_record(
                        raw_region.get("algorithm", raw_region.get("algo")),
                        _address(raw_region.get("flashbase", raw_region.get("addr")), "flash start"),
                        _address(raw_region.get("flashsize", raw_region.get("size")), "flash size"),
                    ))
                raw_option = str(raw_target.get("algooptb") or "").strip()
                targets.append({
                    "manufacturer": manufacturer,
                    "series": series,
                    "part_number": part_number,
                    "ram_start": _address(raw_target.get("rambase"), "RAM start"),
                    "ram_size": _address(raw_target.get("ramsize"), "RAM size"),
                    "algorithms": regions,
                    "option_algorithm": algorithm_record(raw_option) if raw_option else None,
                })

    targets.sort(key=lambda item: (
        str(item["manufacturer"]).casefold(),
        str(item["series"]).casefold(),
        str(item["part_number"]).casefold(),
    ))
    manifest: dict[str, object] = {
        "schema": 1,
        "source": {
            "product": "DAPLinkUtility",
            "version": "0.0.6",
            "sha256": digest,
        },
        "manufacturer_count": len({str(item["manufacturer"]) for item in targets}),
        "series_count": len({(str(item["manufacturer"]), str(item["series"])) for item in targets}),
        "target_count": len(targets),
        "region_count": sum(len(item["algorithms"]) for item in targets),
        "referenced_algorithm_count": len(referenced),
        "unreferenced_algorithm_count": len(available) - len(referenced),
        "blob_count": len(written_blobs),
        "blob_bytes": sum(int(item["size"]) for item in written_blobs.values()),
        "blobs": [written_blobs[key] for key in sorted(written_blobs)],
        "targets": targets,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return manifest


def _registration_arrays(executable: Path) -> tuple[bytes, bytes, bytes]:
    try:
        import pefile
    except ImportError as error:
        raise RuntimeError("pefile is required to extract DAPLinkUtility resources") from error

    pe = pefile.PE(str(executable), fast_load=False)
    try:
        image_base = int(pe.OPTIONAL_HEADER.ImageBase)
        iat = None
        for entry in pe.DIRECTORY_ENTRY_IMPORT:
            for imported in entry.imports:
                if imported.name and b"qRegisterResourceData" in imported.name:
                    iat = int(imported.address)
                    break
        if iat is None:
            raise ValueError("qRegisterResourceData import is unavailable")
        code_sections = [section for section in pe.sections if int(section.Characteristics) & 0x20000000]
        trampoline = None
        needle = b"\xff\x25" + struct.pack("<I", iat)
        for section in code_sections:
            offset = section.get_data().find(needle)
            if offset >= 0:
                trampoline = image_base + int(section.VirtualAddress) + offset
                break
        if trampoline is None:
            raise ValueError("qRegisterResourceData trampoline is unavailable")

        pattern = re.compile(
            re.escape(b"\xc7\x44\x24\x0c") + b"(.{4})"
            + re.escape(b"\xc7\x44\x24\x08") + b"(.{4})"
            + re.escape(b"\xc7\x44\x24\x04") + b"(.{4})"
            + re.escape(b"\xc7\x04\x24\x03\x00\x00\x00\xe8") + b"(.{4})",
            re.DOTALL,
        )
        registrations = []
        for section in code_sections:
            code = section.get_data()
            section_va = image_base + int(section.VirtualAddress)
            for match in pattern.finditer(code):
                call_va = section_va + match.start() + 31
                displacement = struct.unpack("<i", match.group(4))[0]
                if call_va + 5 + displacement != trampoline:
                    continue
                data_va = struct.unpack("<I", match.group(1))[0]
                names_va = struct.unpack("<I", match.group(2))[0]
                tree_va = struct.unpack("<I", match.group(3))[0]
                if tree_va < names_va < data_va:
                    registrations.append((tree_va, names_va, data_va))
        registrations = sorted(set(registrations))
        if not registrations:
            raise ValueError("Qt resource registrations are unavailable")

        for index, (tree_va, names_va, data_va) in enumerate(registrations):
            candidates = [entry[0] for entry in registrations[index + 1:] if entry[0] > data_va]
            if candidates:
                data_end = min(candidates)
            else:
                rva = data_va - image_base
                section = pe.get_section_by_rva(rva)
                if section is None:
                    continue
                data_end = image_base + int(section.VirtualAddress) + int(section.SizeOfRawData)

            def read_va(start: int, end: int) -> bytes:
                if end <= start:
                    raise ValueError("Qt resource array range is invalid")
                offset = pe.get_offset_from_rva(start - image_base)
                return bytes(pe.__data__[offset:offset + end - start])

            tree = read_va(tree_va, names_va)
            names = read_va(names_va, data_va)
            data = read_va(data_va, data_end)
            try:
                files = QtResourceReader(tree, names, data).files()
            except ValueError:
                continue
            if any(path.casefold() in (
                "resources/chips.json", "resources/algorithms/chips.json",
            ) for path in files) and any(
                path.casefold().startswith("resources/algorithms/") for path in files
            ):
                return tree, names, data
        raise ValueError("DAPLinkUtility algorithm resources are unavailable")
    finally:
        pe.close()


def build_bundle(executable: Path, output: Path) -> dict[str, object]:
    executable = Path(executable)
    if not executable.is_file():
        raise ValueError("DAPLinkUtility executable is unavailable")
    source_digest = _sha256_file(executable)
    if source_digest != SUPPORTED_SOURCE_SHA256:
        raise ValueError("DAPLinkUtility executable SHA-256 is unsupported")
    tree, names, data = _registration_arrays(executable)
    resources = QtResourceReader(tree, names, data).files()
    return build_bundle_from_resources(resources, output, source_sha256=source_digest)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = build_bundle(args.exe, args.output)
    print(json.dumps({
        key: manifest[key]
        for key in (
            "manufacturer_count", "series_count", "target_count", "region_count",
            "referenced_algorithm_count", "unreferenced_algorithm_count", "blob_count", "blob_bytes",
        )
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
