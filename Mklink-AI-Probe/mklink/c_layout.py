"""Parse pasted C aggregate definitions into bounded scalar layouts."""

from __future__ import annotations

from dataclasses import dataclass
import re

from pycparser import c_ast, c_parser


class CLayoutError(ValueError):
    """A pasted C definition cannot be converted into a safe layout."""


@dataclass(frozen=True)
class CLayoutLeaf:
    suffix: str
    offset: int
    type_name: str
    scalar_kind: str
    size: int
    overlapping: bool = False
    enum_values: dict[str, int] | None = None
    enum_signed: bool = False


@dataclass(frozen=True)
class CLayout:
    type_name: str
    size: int
    alignment: int
    pack: int | None
    leaves: tuple[CLayoutLeaf, ...]

    def to_dict(self) -> dict:
        return {
            "type_name": self.type_name,
            "size": self.size,
            "alignment": self.alignment,
            "pack": self.pack,
            "leaf_count": len(self.leaves),
        }


@dataclass(frozen=True)
class _NodeLayout:
    size: int
    alignment: int
    leaves: tuple[CLayoutLeaf, ...]


_MAX_SOURCE_LENGTH = 64 * 1024
_MAX_LEAVES = 512
_PACK_VALUES = {1, 2, 4, 8}
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_ATTRIBUTE = re.compile(r"__attribute__\s*\(\s*\([^;]*?\)\s*\)", re.DOTALL)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//[^\r\n]*")
_PRAGMA_PACK = re.compile(
    r"^\s*#\s*pragma\s+pack\s*\(\s*(?:push\s*,\s*)?(1|2|4|8)\s*\)",
    re.IGNORECASE | re.MULTILINE,
)

_PRELUDE = """
typedef signed char int8_t;
typedef unsigned char uint8_t;
typedef signed short int16_t;
typedef unsigned short uint16_t;
typedef signed int int32_t;
typedef unsigned int uint32_t;
typedef signed long long int64_t;
typedef unsigned long long uint64_t;
typedef unsigned char bool;
"""

_SCALARS: dict[str, tuple[str, int, int]] = {
    "_Bool": ("bool", 1, 1),
    "bool": ("bool", 1, 1),
    "char": ("signed", 1, 1),
    "signed char": ("signed", 1, 1),
    "unsigned char": ("unsigned", 1, 1),
    "short": ("signed", 2, 2),
    "short int": ("signed", 2, 2),
    "signed short": ("signed", 2, 2),
    "signed short int": ("signed", 2, 2),
    "unsigned short": ("unsigned", 2, 2),
    "unsigned short int": ("unsigned", 2, 2),
    "int": ("signed", 4, 4),
    "signed": ("signed", 4, 4),
    "signed int": ("signed", 4, 4),
    "unsigned": ("unsigned", 4, 4),
    "unsigned int": ("unsigned", 4, 4),
    "long": ("signed", 4, 4),
    "long int": ("signed", 4, 4),
    "signed long": ("signed", 4, 4),
    "signed long int": ("signed", 4, 4),
    "unsigned long": ("unsigned", 4, 4),
    "unsigned long int": ("unsigned", 4, 4),
    "long long": ("signed", 8, 8),
    "long long int": ("signed", 8, 8),
    "signed long long": ("signed", 8, 8),
    "signed long long int": ("signed", 8, 8),
    "unsigned long long": ("unsigned", 8, 8),
    "unsigned long long int": ("unsigned", 8, 8),
    "float": ("float", 4, 4),
    "double": ("float", 8, 8),
}


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _constant_int(node: c_ast.Node | None) -> int:
    if isinstance(node, c_ast.Constant) and node.type in {"int", "unsigned int"}:
        try:
            return int(node.value.rstrip("uUlL"), 0)
        except ValueError as exc:
            raise CLayoutError(f"unsupported array bound: {node.value}") from exc
    raise CLayoutError("array bounds must be positive integer constants")


def _sanitize_source(source: str) -> tuple[str, int | None]:
    if not isinstance(source, str) or not source.strip():
        raise CLayoutError("C definition is empty")
    if len(source) > _MAX_SOURCE_LENGTH:
        raise CLayoutError(f"C definition exceeds {_MAX_SOURCE_LENGTH} characters")
    detected_pack = None
    match = _PRAGMA_PACK.search(source)
    if match:
        detected_pack = int(match.group(1))
    elif re.search(r"\bpacked\b", source):
        detected_pack = 1
    cleaned = _BLOCK_COMMENT.sub(" ", source)
    cleaned = _LINE_COMMENT.sub("", cleaned)
    cleaned = _ATTRIBUTE.sub(" ", cleaned)
    cleaned = re.sub(r"\b__(?:packed|PACKED)\b", " ", cleaned)
    cleaned = "\n".join(
        line for line in cleaned.splitlines() if not line.lstrip().startswith("#")
    )
    return cleaned, detected_pack


class _LayoutBuilder:
    def __init__(self, ast: c_ast.FileAST, pack: int | None):
        self.pack = pack
        self.typedefs: dict[str, c_ast.Node] = {}
        self.structs: dict[tuple[str, str], c_ast.Node] = {}
        for item in ast.ext:
            if isinstance(item, c_ast.Typedef):
                self.typedefs[item.name] = item.type
            self._register_records(item)

    def _register_records(self, node: c_ast.Node) -> None:
        if isinstance(node, (c_ast.Struct, c_ast.Union)) and node.name and node.decls:
            kind = "struct" if isinstance(node, c_ast.Struct) else "union"
            self.structs[(kind, node.name)] = node
        for _name, child in node.children():
            self._register_records(child)

    def select_type(self, preferred: str | None) -> tuple[str, c_ast.Node]:
        if preferred and preferred in self.typedefs:
            return preferred, self.typedefs[preferred]
        aggregate_typedefs = [
            (name, node)
            for name, node in self.typedefs.items()
            if self._contains_aggregate(node, set())
            and name not in {"int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t", "bool"}
        ]
        if len(aggregate_typedefs) == 1:
            return aggregate_typedefs[0]
        named_records = [
            (name, node) for (kind, name), node in self.structs.items()
            if kind in {"struct", "union"}
        ]
        if len(named_records) == 1:
            return named_records[0]
        if preferred:
            raise CLayoutError(f"type '{preferred}' was not found in the pasted definition")
        raise CLayoutError("paste exactly one aggregate type or specify its typedef name")

    def _contains_aggregate(self, node: c_ast.Node, seen: set[str]) -> bool:
        node = self._unwrap(node)
        if isinstance(node, (c_ast.Struct, c_ast.Union)):
            return True
        if isinstance(node, c_ast.IdentifierType):
            name = " ".join(node.names)
            if name in seen or name not in self.typedefs:
                return False
            return self._contains_aggregate(self.typedefs[name], seen | {name})
        return False

    @staticmethod
    def _unwrap(node: c_ast.Node) -> c_ast.Node:
        while isinstance(node, c_ast.TypeDecl):
            node = node.type
        return node

    def build(self, node: c_ast.Node, *, stack: frozenset[str] = frozenset()) -> _NodeLayout:
        node = self._unwrap(node)
        if isinstance(node, c_ast.IdentifierType):
            name = " ".join(node.names)
            scalar = _SCALARS.get(name)
            if scalar:
                kind, size, alignment = scalar
                return _NodeLayout(
                    size,
                    alignment,
                    (CLayoutLeaf("", 0, name, kind, size),),
                )
            if name in stack:
                raise CLayoutError(f"recursive type is unsupported: {name}")
            target = self.typedefs.get(name)
            if target is None:
                raise CLayoutError(f"unsupported C type: {name}")
            return self.build(target, stack=stack | {name})
        if isinstance(node, c_ast.Enum):
            values: dict[str, int] = {}
            current = -1
            if node.values:
                for enumerator in node.values.enumerators:
                    current = _constant_int(enumerator.value) if enumerator.value else current + 1
                    values[enumerator.name] = current
            return _NodeLayout(
                4,
                4,
                (CLayoutLeaf("", 0, node.name or "enum", "enum", 4, enum_values=values,
                             enum_signed=any(value < 0 for value in values.values())),),
            )
        if isinstance(node, c_ast.ArrayDecl):
            count = _constant_int(node.dim)
            if count <= 0:
                raise CLayoutError("array bounds must be positive")
            element = self.build(node.type, stack=stack)
            leaves: list[CLayoutLeaf] = []
            for index in range(count):
                base = index * element.size
                leaves.extend(
                    CLayoutLeaf(
                        f"[{index}]{leaf.suffix}",
                        base + leaf.offset,
                        leaf.type_name,
                        leaf.scalar_kind,
                        leaf.size,
                        leaf.overlapping,
                        leaf.enum_values,
                        leaf.enum_signed,
                    )
                    for leaf in element.leaves
                )
                if len(leaves) > _MAX_LEAVES:
                    raise CLayoutError(f"C definition expands beyond {_MAX_LEAVES} scalar leaves")
            return _NodeLayout(element.size * count, element.alignment, tuple(leaves))
        if isinstance(node, c_ast.PtrDecl):
            raise CLayoutError("pointer members are not directly watchable")
        if isinstance(node, (c_ast.Struct, c_ast.Union)):
            kind = "struct" if isinstance(node, c_ast.Struct) else "union"
            record = node
            if record.decls is None and record.name:
                record = self.structs.get((kind, record.name))
            if record is None or record.decls is None:
                raise CLayoutError(f"incomplete {kind} definition")
            return self._build_record(record, stack=stack, is_union=kind == "union")
        raise CLayoutError(f"unsupported C declaration: {type(node).__name__}")

    def _build_record(
        self,
        record: c_ast.Struct | c_ast.Union,
        *,
        stack: frozenset[str],
        is_union: bool,
    ) -> _NodeLayout:
        offset = 0
        extent = 0
        record_alignment = 1
        leaves: list[CLayoutLeaf] = []
        for declaration in record.decls or ():
            if declaration.bitsize is not None:
                raise CLayoutError("bit-field layout is compiler-specific and is not supported")
            child = self.build(declaration.type, stack=stack)
            alignment = min(child.alignment, self.pack) if self.pack else child.alignment
            member_offset = 0 if is_union else _align_up(offset, alignment)
            prefix = f".{declaration.name}" if declaration.name else ""
            for leaf in child.leaves:
                leaves.append(CLayoutLeaf(
                    prefix + leaf.suffix,
                    member_offset + leaf.offset,
                    leaf.type_name,
                    leaf.scalar_kind,
                    leaf.size,
                    leaf.overlapping or is_union,
                    leaf.enum_values,
                    leaf.enum_signed,
                ))
            if len(leaves) > _MAX_LEAVES:
                raise CLayoutError(f"C definition expands beyond {_MAX_LEAVES} scalar leaves")
            extent = max(extent, member_offset + child.size)
            if not is_union:
                offset = member_offset + child.size
            record_alignment = max(record_alignment, alignment)
        if not leaves:
            raise CLayoutError("aggregate contains no watchable scalar members")
        return _NodeLayout(_align_up(extent, record_alignment), record_alignment, tuple(leaves))


def parse_c_layout(
    source: str,
    *,
    preferred_type: str | None = None,
    pack: int | None = None,
) -> CLayout:
    """Parse one pasted C aggregate and return its scalar memory layout."""
    if preferred_type is not None and not _IDENTIFIER.fullmatch(preferred_type):
        raise CLayoutError("preferred type name is invalid")
    if pack is not None:
        pack = int(pack)
        if pack not in _PACK_VALUES:
            raise CLayoutError("pack must be one of 1, 2, 4, or 8")
    cleaned, detected_pack = _sanitize_source(source)
    effective_pack = pack if pack is not None else detected_pack
    try:
        ast = c_parser.CParser().parse(_PRELUDE + "\n" + cleaned)
    except c_parser.ParseError as exc:
        raise CLayoutError(f"C definition parse failed: {exc}") from exc
    builder = _LayoutBuilder(ast, effective_pack)
    type_name, node = builder.select_type(preferred_type)
    layout = builder.build(node, stack=frozenset({type_name}))
    return CLayout(type_name, layout.size, layout.alignment, effective_pack, layout.leaves)
