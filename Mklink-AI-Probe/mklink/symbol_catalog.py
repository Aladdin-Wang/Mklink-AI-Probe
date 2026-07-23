"""Versioned, runtime-safe AXF symbol catalog for dashboard consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
import math
from pathlib import Path
import re
import struct
import time
from typing import Iterable, Sequence

from mklink.dwarf_parser import (
    DwarfInfo,
    get_array_type,
    get_enum_type,
    get_record_type,
    resolve_type_name,
)


class SymbolCatalogError(ValueError):
    """Base error for catalog lookup and generation failures."""


class SymbolValueError(SymbolCatalogError):
    """A user value cannot be represented by the selected symbol type."""


@dataclass(frozen=True)
class AxfFingerprint:
    size: int
    mtime_ns: int

    @classmethod
    def from_path(cls, path: str) -> "AxfFingerprint":
        stat = Path(path).stat()
        return cls(size=stat.st_size, mtime_ns=stat.st_mtime_ns)

    def to_dict(self) -> dict[str, int]:
        return {"size": self.size, "mtime_ns": self.mtime_ns}


@dataclass(frozen=True)
class SymbolDescriptor:
    path: str
    address: int
    type_name: str
    scalar_kind: str
    size: int
    writable: bool = True
    enum_values: dict[str, int] = field(default_factory=dict)
    enum_signed: bool = False
    parent_path: str | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "address": self.address,
            "type_name": self.type_name,
            "scalar_kind": self.scalar_kind,
            "size": self.size,
            "writable": self.writable,
            "enum_values": dict(self.enum_values),
            "enum_signed": self.enum_signed,
            "parent_path": self.parent_path,
        }


@dataclass(frozen=True)
class RebindSummary:
    preserved: tuple[str, ...]
    updated: tuple[str, ...]
    removed: tuple[str, ...]

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "preserved": list(self.preserved),
            "updated": list(self.updated),
            "removed": list(self.removed),
        }


@dataclass(frozen=True)
class _ScalarSpec:
    kind: str
    size: int
    enum_values: dict[str, int] = field(default_factory=dict)
    enum_signed: bool = False


@dataclass(frozen=True)
class SymbolCatalog:
    generation: int
    axf_path: str
    fingerprint: AxfFingerprint
    parsed_at: float
    items: tuple[SymbolDescriptor, ...]
    truncated_roots: tuple[str, ...] = ()

    @cached_property
    def index(self) -> dict[str, SymbolDescriptor]:
        return {item.path: item for item in self.items}

    def by_path(self, path: str) -> SymbolDescriptor | None:
        return self.index.get(path)

    def require(self, path: str, generation: int) -> SymbolDescriptor:
        if generation != self.generation:
            raise SymbolCatalogError(
                f"symbol generation is stale: expected {self.generation}, got {generation}"
            )
        descriptor = self.by_path(path)
        if descriptor is None:
            raise SymbolCatalogError(f"symbol is unavailable: {path}")
        return descriptor

    def is_stale(self) -> bool:
        try:
            return AxfFingerprint.from_path(self.axf_path) != self.fingerprint
        except OSError:
            return True

    def to_page(
        self,
        *,
        query: str = "",
        writable: bool = False,
        offset: int = 0,
        limit: int = 200,
    ) -> dict:
        query_key = query.strip().casefold()
        filtered = [
            item
            for item in self.items
            if (not query_key or query_key in item.path.casefold() or query_key in item.type_name.casefold())
            and (not writable or item.writable)
        ]
        start = max(0, int(offset))
        count = max(1, min(int(limit), 500))
        return {
            "generation": self.generation,
            "axf_path": self.axf_path,
            "parsed_at": self.parsed_at,
            "fingerprint": self.fingerprint.to_dict(),
            "stale": self.is_stale(),
            "total": len(filtered),
            "items": [item.to_dict() for item in filtered[start : start + count]],
            "truncated_roots": list(self.truncated_roots),
        }

    @classmethod
    def from_dwarf(
        cls,
        info: DwarfInfo,
        *,
        axf_path: str,
        generation: int = 1,
        ram_ranges: Iterable[tuple[int, int]] = ((0x20000000, 0x40000000),),
        max_leaves_per_root: int = 256,
    ) -> "SymbolCatalog":
        ranges = tuple((int(start), int(end)) for start, end in ram_ranges)
        descriptors: list[SymbolDescriptor] = []
        truncated_roots: set[str] = set()
        leaf_limit = max(1, int(max_leaves_per_root))

        def in_ram(address: int, size: int) -> bool:
            return any(start <= address and address + max(1, size) <= end for start, end in ranges)

        def append_scalar(
            *,
            root_path: str,
            path: str,
            address: int,
            type_name: str,
            type_offset: int | None,
            size: int,
            parent_path: str | None,
            leaf_count: list[int],
        ) -> bool:
            spec = _resolve_scalar_spec(info, type_offset, type_name=type_name, size=size)
            if spec is None or not in_ram(address, spec.size):
                return False
            if leaf_count[0] >= leaf_limit:
                truncated_roots.add(root_path)
                return True
            descriptors.append(
                SymbolDescriptor(
                    path=path,
                    address=address,
                    type_name=type_name,
                    scalar_kind=spec.kind,
                    size=spec.size,
                    enum_values=spec.enum_values,
                    enum_signed=spec.enum_signed,
                    parent_path=parent_path,
                )
            )
            leaf_count[0] += 1
            return True

        def expand_type(
            *,
            root_path: str,
            path: str,
            address: int,
            type_name: str,
            type_offset: int | None,
            size: int,
            depth: int,
            visited: frozenset[int],
            leaf_count: list[int],
        ) -> None:
            if root_path in truncated_roots:
                return
            if depth > 16:
                return
            if append_scalar(
                root_path=root_path,
                path=path,
                address=address,
                type_name=type_name,
                type_offset=type_offset,
                size=size,
                parent_path=None if path == root_path else root_path,
                leaf_count=leaf_count,
            ):
                return

            resolved = _follow_type(info, type_offset)
            array = get_array_type(info, resolved)
            if array is not None:
                element_name, element_size = resolve_type_name(
                    info, array.element_type_offset,
                )
                if element_size <= 0 or not array.dimensions:
                    return
                if array.size > 0 and not in_ram(address, array.size):
                    return
                element_count = math.prod(array.dimensions)
                for linear_index in range(element_count):
                    if root_path in truncated_roots:
                        return
                    remainder = linear_index
                    indexes: list[int] = []
                    for dimension in reversed(array.dimensions):
                        indexes.append(remainder % dimension)
                        remainder //= dimension
                    indexes.reverse()
                    element_path = path + "".join(f"[{index}]" for index in indexes)
                    expand_type(
                        root_path=root_path,
                        path=element_path,
                        address=address + linear_index * element_size,
                        type_name=element_name,
                        type_offset=array.element_type_offset,
                        size=element_size,
                        depth=depth + 1,
                        visited=visited,
                        leaf_count=leaf_count,
                    )
                return

            record = get_record_type(info, resolved)
            if record is None and type_name in info.structs:
                record = info.structs[type_name]
            if record is None or record.kind == "union" or record.offset in visited:
                return
            if record.size > 0 and not in_ram(address, record.size):
                return
            next_visited = visited | {record.offset}
            for member in record.members:
                if not member.name or member.bit_size is not None:
                    continue
                expand_type(
                    root_path=root_path,
                    path=f"{path}.{member.name}",
                    address=address + member.offset,
                    type_name=member.type_name,
                    type_offset=member.type_offset,
                    size=member.size,
                    depth=depth + 1,
                    visited=next_visited,
                    leaf_count=leaf_count,
                )

        for name, variable in info.variables.items():
            if variable.address is None:
                continue
            address = int(variable.address)
            expand_type(
                root_path=name,
                path=name,
                address=address,
                type_name=variable.type_name,
                type_offset=variable.type_offset,
                size=variable.size,
                depth=0,
                visited=frozenset(),
                leaf_count=[0],
            )

        return cls(
            generation=max(1, int(generation)),
            axf_path=str(axf_path),
            fingerprint=AxfFingerprint.from_path(axf_path),
            parsed_at=time.time(),
            items=tuple(sorted(descriptors, key=lambda item: _natural_path_key(item.path))),
            truncated_roots=tuple(sorted(truncated_roots, key=str.casefold)),
        )


_PATH_NUMBER_RE = re.compile(r"(\d+)")


def _natural_path_key(path: str) -> tuple[str | int, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in _PATH_NUMBER_RE.split(path)
    )


def _follow_type(info: DwarfInfo, type_offset: int | None) -> int | None:
    seen: set[int] = set()
    current = type_offset
    while current is not None and current not in seen:
        seen.add(current)
        if current in info.typedefs:
            current = info.typedefs[current][1]
            continue
        if current in info.qualifiers:
            current = info.qualifiers[current]
            continue
        return current
    return current


def _resolve_scalar_spec(
    info: DwarfInfo,
    type_offset: int | None,
    *,
    type_name: str,
    size: int,
) -> _ScalarSpec | None:
    resolved = _follow_type(info, type_offset)
    if resolved in info.pointers or resolved in info.arrays:
        return None
    enum_def = get_enum_type(info, resolved)
    if enum_def is not None:
        return _ScalarSpec(
            "enum",
            enum_def.size or size or 4,
            {label: value for value, label in enum_def.values.items()},
            any(value < 0 for value in enum_def.values),
        )
    if resolved in info.base_types:
        base_name, base_size = info.base_types[resolved]
        return _classify_scalar(
            base_name,
            base_size or size,
            encoding=info.base_type_encodings.get(resolved),
        )
    if resolved is not None:
        return None
    return _classify_scalar(type_name, size)


def _classify_scalar(
    type_name: str,
    size: int,
    *,
    encoding: int | None = None,
) -> _ScalarSpec | None:
    if encoding == 0x02:
        return _ScalarSpec("bool", size or 1)
    if encoding == 0x04:
        return _ScalarSpec("float", size) if size in (4, 8) else None
    if encoding in {0x05, 0x06}:
        return _ScalarSpec("signed", size or 4)
    if encoding in {0x07, 0x08}:
        return _ScalarSpec("unsigned", size or 4)
    if encoding is not None:
        return None
    key = " ".join(type_name.strip().lower().replace("__", "").split())
    tokens = key.split()
    if not key or key == "unknown" or key.endswith("*") or key.endswith("[]"):
        return None
    if key in {"bool", "boolean", "_bool"}:
        return _ScalarSpec("bool", size or 1)
    if key in {"float", "fp32"}:
        return _ScalarSpec("float", 4)
    if key in {"double", "fp64"}:
        return _ScalarSpec("float", 8)
    if "unsigned" in key or key.startswith("uint") or key in {"uchar", "ushort", "ulong"}:
        return _ScalarSpec("unsigned", size or _integer_size_from_name(key))
    if key.startswith("int") or "int" in tokens or key.startswith("signed") or key in {
        "char", "short", "long", "long long",
    }:
        return _ScalarSpec("signed", size or _integer_size_from_name(key))
    return None


def _integer_size_from_name(type_name: str) -> int:
    for bits in (8, 16, 32, 64):
        if str(bits) in type_name:
            return bits // 8
    return 4


def encode_descriptor(descriptor: SymbolDescriptor, value: object) -> bytes:
    kind = descriptor.scalar_kind
    size = descriptor.size
    if kind == "float":
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise SymbolValueError("value must be a floating-point number") from exc
        if not math.isfinite(number):
            raise SymbolValueError("floating-point value must be finite")
        if size not in (4, 8):
            raise SymbolValueError(f"unsupported floating-point size: {size}")
        return struct.pack("<f" if size == 4 else "<d", number)
    if kind == "bool":
        if not isinstance(value, bool):
            raise SymbolValueError("boolean value must be true or false")
        return int(value).to_bytes(size, "little", signed=False)
    if kind == "enum":
        if isinstance(value, str):
            if value not in descriptor.enum_values:
                raise SymbolValueError(f"unknown enum value: {value}")
            number = descriptor.enum_values[value]
        else:
            number = _coerce_integer(value)
            if number not in descriptor.enum_values.values():
                raise SymbolValueError(f"unknown enum value: {number}")
        try:
            return int(number).to_bytes(size, "little", signed=descriptor.enum_signed)
        except OverflowError as exc:
            raise SymbolValueError("enum value does not fit the selected type") from exc
    if kind in {"signed", "unsigned"}:
        number = _coerce_integer(value)
        minimum = -(1 << (size * 8 - 1)) if kind == "signed" else 0
        maximum = (1 << (size * 8 - (1 if kind == "signed" else 0))) - 1
        if not minimum <= number <= maximum:
            raise SymbolValueError(f"integer value is outside [{minimum}, {maximum}]")
        return number.to_bytes(size, "little", signed=kind == "signed")
    raise SymbolValueError(f"unsupported scalar kind: {kind}")


def decode_descriptor(descriptor: SymbolDescriptor, data: bytes):
    if len(data) < descriptor.size:
        raise SymbolValueError(
            f"not enough bytes for {descriptor.path}: need {descriptor.size}, got {len(data)}"
        )
    payload = data[: descriptor.size]
    if descriptor.scalar_kind == "float":
        return struct.unpack("<f" if descriptor.size == 4 else "<d", payload)[0]
    if descriptor.scalar_kind == "bool":
        return bool(int.from_bytes(payload, "little", signed=False))
    if descriptor.scalar_kind == "signed":
        return int.from_bytes(payload, "little", signed=True)
    if descriptor.scalar_kind == "enum":
        return int.from_bytes(payload, "little", signed=descriptor.enum_signed)
    if descriptor.scalar_kind == "unsigned":
        return int.from_bytes(payload, "little", signed=False)
    raise SymbolValueError(f"unsupported scalar kind: {descriptor.scalar_kind}")


def _coerce_integer(value: object) -> int:
    if isinstance(value, bool):
        raise SymbolValueError("boolean is not accepted as an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip(), 0)
        except ValueError as exc:
            raise SymbolValueError("value must be an integer") from exc
    raise SymbolValueError("value must be an integer")


def rebind_paths(
    old: SymbolCatalog,
    new: SymbolCatalog,
    paths: Sequence[str],
) -> RebindSummary:
    preserved: list[str] = []
    updated: list[str] = []
    removed: list[str] = []
    for path in paths:
        before = old.by_path(path)
        after = new.by_path(path)
        if after is None:
            removed.append(path)
        elif before is not None and (
            before.address,
            before.type_name,
            before.scalar_kind,
            before.size,
            before.enum_values,
            before.enum_signed,
        ) != (
            after.address,
            after.type_name,
            after.scalar_kind,
            after.size,
            after.enum_values,
            after.enum_signed,
        ):
            updated.append(path)
        else:
            preserved.append(path)
    return RebindSummary(tuple(preserved), tuple(updated), tuple(removed))
