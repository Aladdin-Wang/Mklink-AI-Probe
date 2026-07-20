"""Backend selection and normalized contracts for ELF/DWARF operations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Protocol

if TYPE_CHECKING:
    from mklink.dwarf_parser import DwarfInfo


ELF_BACKENDS = frozenset({"builtin", "external"})
ENV_ELF_BACKEND = "MKLINK_ELF_BACKEND"


class ElfBackendConfigError(ValueError):
    """Raised when an ELF backend selection is invalid."""


class ElfParseError(RuntimeError):
    """Raised when an ELF/DWARF file cannot be parsed safely."""


@dataclass(frozen=True)
class ElfSymbol:
    name: str
    address: int
    size: int
    kind: str
    binding: str
    visibility: str
    section: int | str


@dataclass(frozen=True)
class ElfSection:
    name: str
    address: int
    size: int
    flags: int
    section_type: str


class ElfBackend(Protocol):
    name: str
    parser_version: str

    def symbols(self, source: str) -> list[ElfSymbol]: ...

    def sections(self, source: str) -> list[ElfSection]: ...

    def dwarf_info(self, source: str) -> DwarfInfo: ...

    def source_locations(
        self, source: str, addresses: Iterable[int]
    ) -> dict[int, str]: ...


def _normalize_backend(value: object, *, source: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in ELF_BACKENDS:
        choices = ", ".join(sorted(ELF_BACKENDS))
        raise ElfBackendConfigError(
            f"Invalid ELF backend {value!r} from {source}; expected one of: {choices}"
        )
    return normalized


def _project_backend(project_root: str | os.PathLike[str] | None) -> object | None:
    if project_root is not None:
        from mklink.project_config import load_toolchain_config

        config = load_toolchain_config(str(project_root)) or {}
    else:
        from mklink.toolchain import load_toolchain_overrides

        config = load_toolchain_overrides()
    return config.get("elf_backend") if isinstance(config, dict) else None


def resolve_elf_backend(
    explicit: str | None = None,
    *,
    project_root: str | os.PathLike[str] | None = None,
) -> str:
    """Resolve the requested backend without probing or launching host tools."""
    if explicit is not None:
        return _normalize_backend(explicit, source="explicit selection")
    environment = os.environ.get(ENV_ELF_BACKEND)
    if environment is not None:
        return _normalize_backend(environment, source=ENV_ELF_BACKEND)
    configured = _project_backend(project_root)
    if configured is not None:
        return _normalize_backend(configured, source=".mklink/toolchain.json")
    return "builtin"


def get_elf_backend(
    backend: str | None = None,
    *,
    project_root: str | os.PathLike[str] | None = None,
) -> ElfBackend:
    effective = resolve_elf_backend(backend, project_root=project_root)
    if effective == "builtin":
        from mklink.elf_builtin import BuiltinElfBackend

        return BuiltinElfBackend()
    from mklink.elf_external import ExternalElfBackend

    return ExternalElfBackend()


def _builtin_version() -> str | None:
    try:
        return version("pyelftools")
    except PackageNotFoundError:
        return None


def elf_status(
    backend: str | None = None,
    *,
    project_root: str | os.PathLike[str] | None = None,
) -> dict[str, object]:
    """Return built-in and optional external ELF capability diagnostics."""
    from mklink.toolchain import resolve_addr2line, resolve_readelf

    effective = resolve_elf_backend(backend, project_root=project_root)
    builtin_version = _builtin_version()
    readelf = resolve_readelf()
    addr2line = resolve_addr2line()
    builtin_available = builtin_version is not None
    external_available = readelf is not None
    return {
        "elf_backend": effective,
        "elf_available": (
            builtin_available if effective == "builtin" else external_available
        ),
        "builtin_elf_available": builtin_available,
        "builtin_elf_version": builtin_version,
        "external_elf_available": external_available,
        "external_source_lookup_available": addr2line is not None,
        # Backward-compatible diagnostics for the optional GNU backend.
        "readelf_available": external_available,
        "readelf_path": readelf,
        "addr2line_available": addr2line is not None,
        "addr2line_path": addr2line,
    }


def list_elf_symbols(
    source: str,
    *,
    backend: str | None = None,
    project_root: str | os.PathLike[str] | None = None,
) -> list[ElfSymbol]:
    return get_elf_backend(backend, project_root=project_root).symbols(source)


def list_elf_sections(
    source: str,
    *,
    backend: str | None = None,
    project_root: str | os.PathLike[str] | None = None,
) -> list[ElfSection]:
    return get_elf_backend(backend, project_root=project_root).sections(source)


def lookup_source_locations(
    source: str,
    addresses: Iterable[int],
    *,
    backend: str | None = None,
    project_root: str | os.PathLike[str] | None = None,
) -> dict[int, str]:
    return get_elf_backend(backend, project_root=project_root).source_locations(
        source, addresses
    )


def resolve_function_symbol(
    source: str,
    name: str,
    *,
    backend: str | None = None,
    project_root: str | os.PathLike[str] | None = None,
) -> int | None:
    for symbol in list_elf_symbols(
        source, backend=backend, project_root=project_root
    ):
        if symbol.kind == "function" and symbol.name == name:
            return symbol.address
    return None


def search_function_symbols(
    source: str,
    pattern: str,
    *,
    max_results: int = 20,
    backend: str | None = None,
    project_root: str | os.PathLike[str] | None = None,
) -> list[dict[str, object]]:
    import re

    regex = re.compile(pattern, re.IGNORECASE)
    matches = []
    for symbol in list_elf_symbols(
        source, backend=backend, project_root=project_root
    ):
        if symbol.kind != "function" or not regex.search(symbol.name):
            continue
        matches.append(
            {"name": symbol.name, "address": symbol.address, "size": symbol.size}
        )
        if len(matches) >= max_results:
            break
    return matches
