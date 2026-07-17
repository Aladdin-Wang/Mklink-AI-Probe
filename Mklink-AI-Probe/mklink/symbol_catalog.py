"""Versioned, runtime-safe AXF symbol catalog for dashboard consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
import math
from pathlib import Path
import struct
import time
from typing import Iterable, Sequence

from mklink.dwarf_parser import DwarfInfo


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


@dataclass(frozen=True)
class SymbolCatalog:
    generation: int
    axf_path: str
    fingerprint: AxfFingerprint
    parsed_at: float
    items: tuple[SymbolDescriptor, ...]

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
            "parsed_at": self.parsed_at,
            "fingerprint": self.fingerprint.to_dict(),
            "stale": self.is_stale(),
            "total": len(filtered),
            "items": [item.to_dict() for item in filtered[start : start + count]],
        }

    @classmethod
    def from_dwarf(
        cls,
        info: DwarfInfo,
        *,
        axf_path: str,
        generation: int = 1,
        ram_ranges: Iterable[tuple[int, int]] = ((0x20000000, 0x40000000),),
    ) -> "SymbolCatalog":
        ranges = tuple((int(start), int(end)) for start, end in ram_ranges)
        descriptors: list[SymbolDescriptor] = []

        def in_ram(address: int, size: int) -> bool:
            return any(start <= address and address + max(1, size) <= end for start, end in ranges)

        def append_scalar(
            *,
            path: str,
            address: int,
            type_name: str,
            type_offset: int | None,
            size: int,
            parent_path: str | None,
        ) -> bool:
            spec = _resolve_scalar_spec(info, type_offset, type_name=type_name, size=size)
            if spec is None or not in_ram(address, spec.size):
                return False
            descriptors.append(
                SymbolDescriptor(
                    path=path,
                    address=address,
                    type_name=type_name,
                    scalar_kind=spec.kind,
                    size=spec.size,
                    enum_values=spec.enum_values,
                    parent_path=parent_path,
                )
            )
            return True

        def expand_struct(
            *,
            root_path: str,
            address: int,
            struct_name: str,
            parent_path: str | None,
            depth: int,
            visited: frozenset[str],
        ) -> None:
            if depth > 8 or struct_name in visited:
                return
            struct_def = info.structs.get(struct_name)
            if struct_def is None:
                return
            next_visited = visited | {struct_name}
            for member in struct_def.members:
                if not member.name or member.bit_size is not None:
                    continue
                member_path = f"{root_path}.{member.name}"
                member_address = address + member.offset
                if append_scalar(
                    path=member_path,
                    address=member_address,
                    type_name=member.type_name,
                    type_offset=member.type_offset,
                    size=member.size,
                    parent_path=root_path,
                ):
                    continue
                nested_name = _resolve_struct_name(info, member.type_offset, member.type_name)
                if nested_name:
                    expand_struct(
                        root_path=member_path,
                        address=member_address,
                        struct_name=nested_name,
                        parent_path=parent_path or root_path,
                        depth=depth + 1,
                        visited=next_visited,
                    )

        for name, variable in info.variables.items():
            if variable.address is None:
                continue
            address = int(variable.address)
            if append_scalar(
                path=name,
                address=address,
                type_name=variable.type_name,
                type_offset=variable.type_offset,
                size=variable.size,
                parent_path=None,
            ):
                continue
            struct_name = _resolve_struct_name(info, variable.type_offset, variable.type_name)
            if struct_name and in_ram(address, max(1, variable.size)):
                expand_struct(
                    root_path=name,
                    address=address,
                    struct_name=struct_name,
                    parent_path=None,
                    depth=0,
                    visited=frozenset(),
                )

        return cls(
            generation=max(1, int(generation)),
            axf_path=str(axf_path),
            fingerprint=AxfFingerprint.from_path(axf_path),
            parsed_at=time.time(),
            items=tuple(sorted(descriptors, key=lambda item: item.path.casefold())),
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


def _resolve_struct_name(info: DwarfInfo, type_offset: int | None, type_name: str) -> str | None:
    resolved = _follow_type(info, type_offset)
    for name, struct_def in info.structs.items():
        if struct_def.offset == resolved:
            return name
    return type_name if type_name in info.structs else None


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
    for enum_def in info.enums.values():
        if enum_def.offset == resolved:
            return _ScalarSpec(
                "enum",
                enum_def.size or size or 4,
                {label: value for value, label in enum_def.values.items()},
            )
    if resolved in info.base_types:
        base_name, base_size = info.base_types[resolved]
        return _classify_scalar(base_name, base_size or size)
    if resolved is not None:
        return None
    return _classify_scalar(type_name, size)


def _classify_scalar(type_name: str, size: int) -> _ScalarSpec | None:
    key = " ".join(type_name.strip().lower().replace("__", "").split())
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
    if (
        key.startswith("int")
        or key in {"char", "signed char", "short", "long", "long long", "signed int"}
    ):
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
        return int(number).to_bytes(size, "little", signed=False)
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
    if descriptor.scalar_kind in {"unsigned", "enum"}:
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
        ) != (
            after.address,
            after.type_name,
            after.scalar_kind,
            after.size,
            after.enum_values,
        ):
            updated.append(path)
        else:
            preserved.append(path)
    return RebindSummary(tuple(preserved), tuple(updated), tuple(removed))
