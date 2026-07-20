"""Built-in ELF/DWARF backend powered by the bundled pyelftools package."""

from __future__ import annotations

from contextlib import contextmanager
from importlib.metadata import version
from typing import Callable, Iterable, Iterator

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile

from mklink.elf_backend import ElfParseError, ElfSection, ElfSymbol


_SYMBOL_KINDS = {
    "STT_OBJECT": "object",
    "STT_FUNC": "function",
}


def _enum_name(value: object, prefix: str) -> str:
    text = str(value)
    if text.startswith(prefix):
        text = text[len(prefix):]
    return text.lower()


def _normalize_symbol(symbol) -> ElfSymbol | None:
    kind = _SYMBOL_KINDS.get(symbol["st_info"]["type"])
    if kind is None or symbol["st_shndx"] == "SHN_UNDEF":
        return None
    name = str(symbol.name or "")
    if not name:
        return None
    return ElfSymbol(
        name=name,
        address=int(symbol["st_value"]),
        size=int(symbol["st_size"]),
        kind=kind,
        binding=_enum_name(symbol["st_info"]["bind"], "STB_"),
        visibility=_enum_name(symbol["st_other"]["visibility"], "STV_"),
        section=symbol["st_shndx"],
    )


class BuiltinElfBackend:
    name = "builtin"
    parser_version = f"pyelftools-{version('pyelftools')}-v1"

    def __init__(self, *, elf_factory: Callable | None = None) -> None:
        self._elf_factory = elf_factory or ELFFile

    @contextmanager
    def _open_elf(self, source: str) -> Iterator:
        try:
            with open(source, "rb") as stream:
                try:
                    yield self._elf_factory(stream)
                except ElfParseError:
                    raise
                except (ELFError, KeyError, TypeError, ValueError) as exc:
                    raise ElfParseError(f"Invalid ELF/AXF file {source}: {exc}") from exc
        except ElfParseError:
            raise
        except OSError as exc:
            raise ElfParseError(f"Cannot open ELF/AXF file {source}: {exc}") from exc

    def symbols(self, source: str) -> list[ElfSymbol]:
        with self._open_elf(source) as elf:
            symtab = elf.get_section_by_name(".symtab")
            if symtab is None:
                return []
            symbols = []
            for symbol in symtab.iter_symbols():
                normalized = _normalize_symbol(symbol)
                if normalized is not None:
                    symbols.append(normalized)
            return symbols

    def sections(self, source: str) -> list[ElfSection]:
        with self._open_elf(source) as elf:
            sections = []
            for section in elf.iter_sections():
                name = str(section.name or "")
                if not name:
                    continue
                sections.append(
                    ElfSection(
                        name=name,
                        address=int(section["sh_addr"]),
                        size=int(section["sh_size"]),
                        flags=int(section["sh_flags"]),
                        section_type=str(section["sh_type"]),
                    )
                )
            return sections

    def dwarf_info(self, source: str):
        raise ElfParseError("Built-in DWARF parsing is not available yet")

    def source_locations(
        self, source: str, addresses: Iterable[int]
    ) -> dict[int, str]:
        raise ElfParseError("Built-in source-line parsing is not available yet")
