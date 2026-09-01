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
import subprocess
import time
from typing import Callable, Mapping, Sequence
import zlib


SUPPORTED_SOURCE_SHA256 = "419e1a830fb66ccb5db5c748e6085dd1778e2289c0b211ea92a84ec214656c33"
RELEASE_SOURCE_SHA256 = "a452cf5aee6a5dd1e43d0b77ff1d8b57d7c1a0fa64aa8c7d8b98a7c9abc777b9"
SUPPORTED_SOURCES = {
    SUPPORTED_SOURCE_SHA256: ("0.0.6", "static"),
    RELEASE_SOURCE_SHA256: ("0.0.21", "runtime"),
}
_CATALOG_RESOURCE_PATHS = {
    "resources/chips.json",
    "resources/algorithms/chips.json",
    "resources/algorithms/chips_cn.json",
}
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
    source_version: str = "0.0.6",
    metadata_parser: Callable[[bytes], Mapping[str, object] | None] = _flm_metadata,
) -> dict[str, object]:
    digest = str(source_sha256).casefold()
    if _SHA256.fullmatch(digest) is None:
        raise ValueError("source SHA-256 is invalid")
    chips_paths = [
        path for path in resources
        if str(path).replace("\\", "/").casefold() in _CATALOG_RESOURCE_PATHS
    ]
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
    missing_references: set[str] = set()
    skipped_targets = 0
    targets = []

    def algorithm_record(raw_name: object, start: int | None = None, size: int | None = None):
        requested = _safe_algorithm_name(raw_name)
        key = requested.casefold()
        if key not in available:
            missing_references.add(requested)
            return None
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
                missing_program_algorithm = False
                for raw_region in raw_regions:
                    if not isinstance(raw_region, Mapping):
                        raise ValueError("target algorithm region must be an object")
                    algorithm = algorithm_record(
                        raw_region.get("algorithm", raw_region.get("algo")),
                        _address(raw_region.get("flashbase", raw_region.get("addr")), "flash start"),
                        _address(raw_region.get("flashsize", raw_region.get("size")), "flash size"),
                    )
                    if algorithm is None:
                        missing_program_algorithm = True
                    else:
                        regions.append(algorithm)
                if missing_program_algorithm or not regions:
                    skipped_targets += 1
                    continue
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
            "version": _text(source_version, "source version"),
            "sha256": digest,
        },
        "manufacturer_count": len({str(item["manufacturer"]) for item in targets}),
        "series_count": len({(str(item["manufacturer"]), str(item["series"])) for item in targets}),
        "target_count": len(targets),
        "region_count": sum(len(item["algorithms"]) for item in targets),
        "referenced_algorithm_count": len(referenced),
        "unreferenced_algorithm_count": len(available) - len(referenced),
        "missing_reference_count": len(missing_references),
        "missing_references": sorted(missing_references, key=str.casefold),
        "skipped_target_count": skipped_targets,
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


def _runtime_arrays_from_regions(regions: Sequence[bytes]) -> tuple[bytes, bytes, bytes]:
    """Locate decrypted Qt resource arrays in pinned process-memory regions."""

    root_pattern = struct.pack(">IHII", 0, _FLAG_DIRECTORY, 1, 1)
    resources_name = "resources".encode("utf-16-be")
    for raw_region in regions:
        region = bytes(raw_region)
        root_offset = region.find(root_pattern)
        while root_offset >= 0:
            encoded_offset = region.find(resources_name, root_offset + len(root_pattern))
            while encoded_offset >= 6:
                names_offset = encoded_offset - 6
                if struct.unpack_from(">H", region, names_offset)[0] != len("resources"):
                    encoded_offset = region.find(resources_name, encoded_offset + 1)
                    continue
                cursor = names_offset
                last_name_end = names_offset
                names_seen = set()
                for _ in range(10000):
                    if cursor + 6 > len(region):
                        break
                    length = struct.unpack_from(">H", region, cursor)[0]
                    end = cursor + 6 + length * 2
                    if length > 1024 or end > len(region):
                        break
                    try:
                        name = region[cursor + 6:end].decode("utf-16-be")
                    except UnicodeDecodeError:
                        break
                    if name and (
                        any(ord(character) < 0x20 for character in name)
                        or "/" in name
                        or "\\" in name
                    ):
                        break
                    if name:
                        names_seen.add(name.casefold())
                        last_name_end = end
                    cursor = end
                if (
                    "resources" not in names_seen
                    or not names_seen.intersection({"chips.json", "chips_cn.json"})
                    or not any(name.endswith(".flm") for name in names_seen)
                ):
                    encoded_offset = region.find(resources_name, encoded_offset + 1)
                    continue
                search_end = min(last_name_end + 256, len(region) - 4)
                for data_offset in range(last_name_end, search_end + 1):
                    size = struct.unpack_from(">I", region, data_offset)[0]
                    if (
                        size <= 0
                        or data_offset + 4 + size > len(region)
                        or region[data_offset + 4:data_offset + 5] not in (b"{", b"[")
                    ):
                        continue
                    tree = region[root_offset:names_offset]
                    names = region[names_offset:data_offset]
                    data = region[data_offset:]
                    try:
                        files = QtResourceReader(tree, names, data).files()
                    except ValueError:
                        continue
                    normalized = {
                        path.replace("\\", "/").casefold() for path in files
                    }
                    if (
                        normalized.intersection(_CATALOG_RESOURCE_PATHS)
                        and any(
                            path.startswith("resources/algorithms/")
                            and path.endswith(".flm")
                            for path in normalized
                        )
                    ):
                        return tree, names, data
                encoded_offset = region.find(resources_name, encoded_offset + 1)
            root_offset = region.find(root_pattern, root_offset + 1)
    raise ValueError("decrypted DAPLinkUtility Qt resources are unavailable")


def _read_process_regions(pid: int) -> list[bytes]:
    if os.name != "nt":
        raise RuntimeError("runtime DAPLinkUtility extraction requires Windows")
    from ctypes import (
        POINTER, Structure, WinDLL, byref, c_int, c_size_t, c_ubyte, c_ushort,
        c_ulong, c_void_p, sizeof,
    )

    class MemoryBasicInformation(Structure):
        _fields_ = [
            ("BaseAddress", c_void_p),
            ("AllocationBase", c_void_p),
            ("AllocationProtect", c_ulong),
            ("PartitionId", c_ushort),
            ("RegionSize", c_size_t),
            ("State", c_ulong),
            ("Protect", c_ulong),
            ("Type", c_ulong),
        ]

    process_query_information = 0x0400
    process_vm_read = 0x0010
    mem_commit = 0x1000
    page_guard = 0x100
    page_noaccess = 0x01
    kernel32 = WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [c_ulong, c_int, c_ulong]
    kernel32.OpenProcess.restype = c_void_p
    kernel32.VirtualQueryEx.argtypes = [
        c_void_p,
        c_void_p,
        POINTER(MemoryBasicInformation),
        c_size_t,
    ]
    kernel32.VirtualQueryEx.restype = c_size_t
    kernel32.ReadProcessMemory.argtypes = [
        c_void_p,
        c_void_p,
        c_void_p,
        c_size_t,
        POINTER(c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = c_int
    kernel32.CloseHandle.argtypes = [c_void_p]
    kernel32.CloseHandle.restype = c_int
    root_pattern = struct.pack(">IHII", 0, _FLAG_DIRECTORY, 1, 1)
    resources_name = "resources".encode("utf-16-be")
    handle = kernel32.OpenProcess(
        process_query_information | process_vm_read, False, int(pid)
    )
    if not handle:
        raise OSError("cannot open DAPLinkUtility process memory")
    regions = []
    address = 0
    try:
        while address < 0x1_0000_0000:
            info = MemoryBasicInformation()
            queried = kernel32.VirtualQueryEx(
                handle, c_void_p(address), byref(info), sizeof(info)
            )
            if not queried:
                address += 0x1000
                continue
            base = int(info.BaseAddress or 0)
            size = int(info.RegionSize)
            if (
                info.State == mem_commit
                and not info.Protect & (page_guard | page_noaccess)
                and 0 < size <= 256 * 1024 * 1024
            ):
                buffer = (c_ubyte * size)()
                read = c_size_t()
                if kernel32.ReadProcessMemory(
                    handle, c_void_p(base), buffer, size, byref(read)
                ):
                    payload = bytes(buffer)[:read.value]
                    if (
                        root_pattern in payload
                        and resources_name in payload
                    ):
                        regions.append(payload)
            next_address = base + max(size, 0x1000)
            address = next_address if next_address > address else address + 0x1000
    finally:
        kernel32.CloseHandle(handle)
    return regions


def _runtime_registration_arrays(executable: Path) -> tuple[bytes, bytes, bytes]:
    if os.name != "nt":
        raise RuntimeError("runtime DAPLinkUtility extraction requires Windows")
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.Popen(
        [str(executable)],
        cwd=str(executable.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startup,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 20.0
        last_error = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ValueError("DAPLinkUtility exited before resources were available")
            try:
                return _runtime_arrays_from_regions(_read_process_regions(process.pid))
            except (OSError, ValueError) as error:
                last_error = error
                time.sleep(0.25)
        raise ValueError("timed out reading decrypted DAPLinkUtility resources") from last_error
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def build_bundle(executable: Path, output: Path) -> dict[str, object]:
    executable = Path(executable)
    if not executable.is_file():
        raise ValueError("DAPLinkUtility executable is unavailable")
    source_digest = _sha256_file(executable)
    source = SUPPORTED_SOURCES.get(source_digest)
    if source is None:
        raise ValueError("DAPLinkUtility executable SHA-256 is unsupported")
    source_version, extraction = source
    tree, names, data = (
        _registration_arrays(executable)
        if extraction == "static"
        else _runtime_registration_arrays(executable)
    )
    resources = QtResourceReader(tree, names, data).files()
    return build_bundle_from_resources(
        resources,
        output,
        source_sha256=source_digest,
        source_version=source_version,
    )


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
            "referenced_algorithm_count", "unreferenced_algorithm_count", "blob_count",
            "blob_bytes", "missing_reference_count", "missing_references",
            "skipped_target_count",
        )
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
