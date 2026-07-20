"""Built-in ELF/DWARF backend powered by the bundled pyelftools package."""

from __future__ import annotations

from contextlib import contextmanager
from importlib.metadata import version
from typing import Callable, Iterable, Iterator

from elftools.common.exceptions import DWARFError, ELFError
from elftools.dwarf.dwarf_expr import DWARFExprParser
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


def _symbols_from_elf(elf) -> list[ElfSymbol]:
    symtab = elf.get_section_by_name(".symtab")
    if symtab is None:
        return []
    symbols = []
    for symbol in symtab.iter_symbols():
        normalized = _normalize_symbol(symbol)
        if normalized is not None:
            symbols.append(normalized)
    return symbols


def _decode_value(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _attribute_name(attributes: dict, *keys: str) -> str:
    for key in keys:
        attribute = attributes.get(key)
        if attribute is not None:
            return _decode_value(attribute.value)
    return ""


def _attribute_int(attributes: dict, key: str, default: int = 0) -> int:
    attribute = attributes.get(key)
    if attribute is None or not isinstance(attribute.value, int):
        return default
    return int(attribute.value)


def _type_offset(die, key: str = "DW_AT_type") -> int | None:
    if key not in die.attributes:
        return None
    try:
        target = die.get_DIE_from_attribute(key)
    except (KeyError, TypeError, ValueError, DWARFError):
        return None
    return int(target.offset) if target is not None else None


def _expression_operations(attribute, structs):
    if attribute is None or not str(attribute.form).startswith("DW_FORM_block") \
            and attribute.form != "DW_FORM_exprloc":
        return []
    try:
        return DWARFExprParser(structs).parse_expr(attribute.value)
    except (KeyError, TypeError, ValueError, DWARFError):
        return []


def _fixed_address(attribute, structs) -> int | None:
    operations = _expression_operations(attribute, structs)
    if len(operations) != 1 or operations[0].op_name != "DW_OP_addr":
        return None
    return int(operations[0].args[0])


def _member_offset(attribute, structs) -> int:
    if attribute is None:
        return 0
    if isinstance(attribute.value, int):
        return int(attribute.value)
    operations = _expression_operations(attribute, structs)
    if len(operations) == 1 and operations[0].op_name in {
        "DW_OP_plus_uconst",
        "DW_OP_constu",
        "DW_OP_consts",
    }:
        return int(operations[0].args[0])
    return 0


def _walk_dies(die, parent_tags: tuple[str, ...] = ()):
    yield die, parent_tags
    child_parents = parent_tags + (die.tag,)
    for child in die.iter_children():
        yield from _walk_dies(child, child_parents)


def _unique_object_addresses(symbols: Iterable[ElfSymbol]) -> dict[str, int]:
    addresses: dict[str, set[int]] = {}
    for symbol in symbols:
        if symbol.kind != "object":
            continue
        addresses.setdefault(symbol.name, set()).add(symbol.address)
    return {
        name: next(iter(values))
        for name, values in addresses.items()
        if len(values) == 1
    }


def _is_global_scope(parent_tags: tuple[str, ...]) -> bool:
    local_tags = {
        "DW_TAG_subprogram",
        "DW_TAG_lexical_block",
        "DW_TAG_inlined_subroutine",
    }
    return not any(tag in local_tags for tag in parent_tags)


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
                except (
                    DWARFError,
                    ELFError,
                    IndexError,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as exc:
                    raise ElfParseError(f"Invalid ELF/AXF file {source}: {exc}") from exc
        except ElfParseError:
            raise
        except OSError as exc:
            raise ElfParseError(f"Cannot open ELF/AXF file {source}: {exc}") from exc

    def symbols(self, source: str) -> list[ElfSymbol]:
        with self._open_elf(source) as elf:
            return _symbols_from_elf(elf)

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
        from mklink.dwarf_parser import (
            DwarfArray,
            DwarfEnum,
            DwarfInfo,
            DwarfMember,
            DwarfStruct,
            DwarfVariable,
            _finalize_array_size,
            get_array_type,
            resolve_type_name,
        )

        with self._open_elf(source) as elf:
            if not elf.has_dwarf_info():
                raise ElfParseError(f"No DWARF info found in {source}")
            dwarf = elf.get_dwarf_info()
            info = DwarfInfo()
            object_addresses = _unique_object_addresses(_symbols_from_elf(elf))

            entries = []
            for cu in dwarf.iter_CUs():
                entries.extend(_walk_dies(cu.get_top_DIE()))

            for die, parent_tags in entries:
                attrs = die.attributes
                tag = die.tag
                offset = int(die.offset)
                name = _attribute_name(attrs, "DW_AT_name")
                size = _attribute_int(attrs, "DW_AT_byte_size")
                type_offset = _type_offset(die)

                if tag == "DW_TAG_base_type" and name:
                    info.base_types[offset] = (name, size)
                    if "DW_AT_encoding" in attrs:
                        info.base_type_encodings[offset] = _attribute_int(
                            attrs, "DW_AT_encoding"
                        )
                elif tag == "DW_TAG_typedef" and name:
                    info.typedefs[offset] = (name, type_offset)
                elif tag == "DW_TAG_pointer_type":
                    info.pointers[offset] = (type_offset, size or 4)
                elif tag == "DW_TAG_array_type":
                    dimensions = []
                    for child in die.iter_children():
                        if child.tag != "DW_TAG_subrange_type":
                            continue
                        child_attrs = child.attributes
                        count_attr = child_attrs.get("DW_AT_count")
                        upper_attr = child_attrs.get("DW_AT_upper_bound")
                        if count_attr is not None and isinstance(count_attr.value, int):
                            count = int(count_attr.value)
                        elif upper_attr is not None and isinstance(upper_attr.value, int):
                            lower = _attribute_int(child_attrs, "DW_AT_lower_bound")
                            count = int(upper_attr.value) - lower + 1
                        else:
                            count = 0
                        if count > 0:
                            dimensions.append(count)
                    info.arrays[offset] = DwarfArray(
                        offset=offset,
                        element_type_offset=type_offset,
                        dimensions=tuple(dimensions),
                        size=size,
                    )
                elif tag in {
                    "DW_TAG_atomic_type",
                    "DW_TAG_const_type",
                    "DW_TAG_restrict_type",
                    "DW_TAG_volatile_type",
                }:
                    info.qualifiers[offset] = type_offset
                elif tag in {"DW_TAG_structure_type", "DW_TAG_union_type"}:
                    record_name = name or f"<anonymous@0x{offset:x}>"
                    record = DwarfStruct(
                        name=record_name,
                        offset=offset,
                        size=size,
                        kind=(
                            "union" if tag == "DW_TAG_union_type" else "struct"
                        ),
                    )
                    for child in die.iter_children():
                        if child.tag != "DW_TAG_member":
                            continue
                        child_attrs = child.attributes
                        member = DwarfMember(
                            name=_attribute_name(child_attrs, "DW_AT_name"),
                            offset=_member_offset(
                                child_attrs.get("DW_AT_data_member_location"),
                                dwarf.structs,
                            ),
                            type_offset=_type_offset(child),
                            bit_offset=(
                                _attribute_int(child_attrs, "DW_AT_bit_offset")
                                if "DW_AT_bit_offset" in child_attrs
                                else (
                                    _attribute_int(
                                        child_attrs, "DW_AT_data_bit_offset"
                                    )
                                    if "DW_AT_data_bit_offset" in child_attrs
                                    else None
                                )
                            ),
                            bit_size=(
                                _attribute_int(child_attrs, "DW_AT_bit_size")
                                if "DW_AT_bit_size" in child_attrs
                                else None
                            ),
                        )
                        record.members.append(member)
                    info.records_by_offset[offset] = record
                    if name:
                        info.structs.setdefault(name, record)
                elif tag == "DW_TAG_enumeration_type":
                    enum_name = name or f"<anonymous@0x{offset:x}>"
                    enum = DwarfEnum(
                        name=enum_name, offset=offset, size=size or 4
                    )
                    for child in die.iter_children():
                        if child.tag != "DW_TAG_enumerator":
                            continue
                        value = child.attributes.get("DW_AT_const_value")
                        if value is None or not isinstance(value.value, int):
                            continue
                        enum.values[int(value.value)] = _attribute_name(
                            child.attributes, "DW_AT_name"
                        )
                    info.enums_by_offset[offset] = enum
                    info.enums.setdefault(enum_name, enum)
                elif tag == "DW_TAG_variable" and name:
                    location = attrs.get("DW_AT_location")
                    address = _fixed_address(location, dwarf.structs)
                    if address is None and _is_global_scope(parent_tags):
                        linkage_name = _attribute_name(
                            attrs,
                            "DW_AT_linkage_name",
                            "DW_AT_MIPS_linkage_name",
                        )
                        address = object_addresses.get(
                            linkage_name or name, object_addresses.get(name)
                        )
                    variable = DwarfVariable(
                        name=name,
                        offset=offset,
                        type_offset=type_offset,
                        address=address,
                    )
                    existing = info.variables.get(name)
                    if existing is None or (
                        existing.address is None and variable.address is not None
                    ):
                        info.variables[name] = variable

            for record in info.records_by_offset.values():
                for member in record.members:
                    member.type_name, member.size = resolve_type_name(
                        info, member.type_offset
                    )
            for array_offset in tuple(info.arrays):
                array = get_array_type(info, array_offset)
                if array is not None:
                    _finalize_array_size(info, array)
            for variable in info.variables.values():
                variable.type_name, variable.size = resolve_type_name(
                    info, variable.type_offset
                )
            return info

    def source_locations(
        self, source: str, addresses: Iterable[int]
    ) -> dict[int, str]:
        raise ElfParseError("Built-in source-line parsing is not available yet")
