"""Typed one-shot and periodic variable reads."""

from __future__ import annotations

import json
import re
import struct
import os
import hashlib
from dataclasses import dataclass
from pathlib import Path

from mklink.dwarf_parser import DwarfInfo


TYPE_FORMATS = {
    "uint8_t": ("<B", 1), "uint8": ("<B", 1), "uchar": ("<B", 1), "bool": ("<?", 1),
    "int8_t": ("<b", 1), "int8": ("<b", 1), "char": ("<b", 1),
    "uint16_t": ("<H", 2), "uint16": ("<H", 2), "ushort": ("<H", 2),
    "int16_t": ("<h", 2), "int16": ("<h", 2), "short": ("<h", 2),
    "uint32_t": ("<I", 4), "uint32": ("<I", 4), "uint": ("<I", 4),
    "int32_t": ("<i", 4), "int32": ("<i", 4), "int": ("<i", 4),
    "float": ("<f", 4), "fp32": ("<f", 4),
    "uint64_t": ("<Q", 8), "uint64": ("<Q", 8),
    "int64_t": ("<q", 8), "int64": ("<q", 8),
    "double": ("<d", 8), "fp64": ("<d", 8),
}

_C_TYPE_ALIASES = {
    "float": "float",
    "uint8_t": "uint8_t",
    "int8_t": "int8_t",
    "uint16_t": "uint16_t",
    "int16_t": "int16_t",
    "uint32_t": "uint32_t",
    "int32_t": "int32_t",
    "unsigned char": "uint8_t",
    "signed char": "int8_t",
    "char": "char",
    "unsigned short": "uint16_t",
    "short": "int16_t",
    "unsigned int": "uint32_t",
    "int": "int32_t",
    "bool": "bool",
}


def decode_value(
    data: bytes,
    type_name: str,
    enum_values: dict[int, str] | None = None,
    *,
    known_size: int = 0,
    scalar_kind: str | None = None,
):
    """Decode raw bytes into a value based on type name.

    Args:
        known_size: When set (> 0), overrides the format-derived size for
            types not in TYPE_FORMATS (e.g. typedefs / enums).
    """
    if scalar_kind:
        size = int(known_size or len(data))
        if len(data) < size:
            raise ValueError(f"not enough bytes for {type_name}: need {size}, got {len(data)}")
        payload = data[:size]
        if scalar_kind == "float":
            if size not in (4, 8):
                raise ValueError(f"unsupported floating-point size: {size}")
            return struct.unpack("<f" if size == 4 else "<d", payload)[0]
        if scalar_kind == "bool":
            return bool(int.from_bytes(payload, "little", signed=False))
        if scalar_kind in {"signed", "unsigned", "enum"}:
            value = int.from_bytes(payload, "little", signed=scalar_kind == "signed")
            if enum_values and value in enum_values:
                return f"{value} ({enum_values[value]})"
            return value

    key = type_name.strip().lower()
    fmt_size = TYPE_FORMATS.get(key)
    if fmt_size:
        fmt, size = fmt_size
    elif known_size > 0:
        # typedef / enum: use known_size to pick the right unsigned format
        fmt = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}.get(known_size, "<I")
        size = known_size
    else:
        fmt, size = "<I", min(4, max(1, len(data)))
    if len(data) < size:
        raise ValueError(f"not enough bytes for {type_name}: need {size}, got {len(data)}")
    value = struct.unpack(fmt, data[:size])[0]
    if enum_values and isinstance(value, int) and value in enum_values:
        return f"{value} ({enum_values[value]})"
    return value


def _candidate_map_paths(source: str) -> list[Path]:
    p = Path(source)
    candidates = []
    if p.suffix:
        candidates.append(p.with_suffix(".map"))
    candidates.append(p.parent / "demo.map")
    return [c for i, c in enumerate(candidates) if c not in candidates[:i]]


def _parse_map_symbol(text: str, name: str) -> tuple[int, int, str | None] | None:
    name_re = re.escape(name)
    by_name = re.compile(
        rf"^\s*{name_re}\s+0x(?P<addr>[0-9a-fA-F]+)\s+\S+\s+(?P<size>\d+)\s+\d+\s+.*?(?P<object>\S+\.o)?\s*$"
    )
    by_range = re.compile(
        rf"^\s*(?P<start>[0-9a-fA-F]{{8}})-(?P<end>[0-9a-fA-F]{{8}})\s+{name_re}\s+(?P<size>\d+)\s+\d+.*?(?P<object>\S+\.o)?\s*$"
    )
    gcc_alloc = re.compile(
        r"^\s*0x(?P<addr>[0-9a-fA-F]+)\s+0x(?P<size>[0-9a-fA-F]+)\s+(?P<object>\S+\.(?:o|obj))\s*$"
    )
    gcc_symbol = re.compile(
        rf"^\s*0x(?P<addr>[0-9a-fA-F]+)\s+{name_re}\s*$"
    )
    lines = text.splitlines()
    matches = []
    previous_alloc: tuple[int, int, str | None] | None = None
    for line in lines:
        m = by_name.match(line)
        if m:
            matches.append((int(m.group("addr"), 16), int(m.group("size")), m.group("object")))
            continue
        m = by_range.match(line)
        if m:
            matches.append((int(m.group("start"), 16), int(m.group("size")), m.group("object")))
            continue
        m = gcc_alloc.match(line)
        if m:
            previous_alloc = (
                int(m.group("addr"), 16),
                int(m.group("size"), 16),
                m.group("object"),
            )
            continue
        m = gcc_symbol.match(line)
        if m:
            address = int(m.group("addr"), 16)
            if previous_alloc:
                alloc_addr, alloc_size, object_name = previous_alloc
                if alloc_addr <= address < alloc_addr + max(alloc_size, 1):
                    matches.append((address, alloc_size - (address - alloc_addr), object_name))
                    continue
            matches.append((address, 0, None))
    if len({(address, size) for address, size, _ in matches}) > 1:
        raise ValueError("Ambiguous MAP symbol: " + name)
    return matches[0] if matches else None


# These limits bound fallback work even when a project root was chosen too broadly.
_MAX_SOURCE_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_FILES = 4096
_MAX_ENTRIES = 20000


def _source_snapshot(path: Path, remaining: int):
    from mklink.file_content import source_fingerprint
    if path.stat().st_size > remaining:
        raise ValueError("MAP/C fallback exceeds source byte limit")
    fingerprint = source_fingerprint(path)
    with path.open('rb') as stream:
        data = stream.read(remaining + 1)
    if len(data) > remaining or hashlib.sha256(data).hexdigest() != fingerprint['sha256']:
        raise ValueError("MAP/C source changed while loading or exceeds byte limit")
    return data.decode('utf-8', errors='replace'), fingerprint


def _global_source(text):
    # Only basic top-level declarations are supported; never infer from locals,
    # comments, strings, struct members, pointer/array declarators or typedefs.
    text = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', ' ', text, flags=re.S)
    depth, result = 0, []
    for char in text:
        if char == '{':
            depth += 1
        if not depth:
            result.append(char)
        if char == '}':
            depth = max(0, depth - 1)
            if not depth:
                result.append(';')
    return ''.join(result)


@dataclass(frozen=True)
class MapSourceSnapshot:
    """Bounded source evidence captured when a catalog is explicitly loaded.

    New files/declarations become visible on the next explicit load. Resolved
    MAP and declaration files are content-checked before and after each read.
    An unavailable fallback never prevents using valid DWARF descriptors.
    """
    maps: tuple = ()
    sources: tuple = ()
    error: str | None = None

    @classmethod
    def load(cls, source: str, project_root: str | None = None):
        maps, sources = [], []
        remaining = _MAX_SOURCE_BYTES
        try:
            for path in _candidate_map_paths(source):
                if path.is_file():
                    text, fp = _source_snapshot(path, remaining)
                    remaining -= fp['size']
                    maps.append((path.resolve(), text, fp))
            if not maps:
                return cls()
            root = Path(project_root).resolve() if project_root else Path(source).resolve().parent
            if not root.is_dir() or root == Path(root.anchor):
                raise ValueError('MAP/C fallback requires a project directory, not a drive root')
            entries = 0
            def fail(error):
                raise error
            for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail):
                entries += len(dirs) + len(files)
                if entries > _MAX_ENTRIES:
                    raise ValueError('MAP/C fallback exceeds directory entry limit')
                dirs[:] = sorted(d for d in dirs if d not in {'.git', '.build', 'node_modules', '.venv'}
                                 and not Path(directory, d).is_symlink()
                                 and not getattr(Path(directory, d), 'is_junction', lambda: False)())
                for filename in sorted(files):
                    path = Path(directory, filename)
                    if path.suffix.lower() not in {'.c', '.h'}:
                        continue
                    if path.is_symlink() or not path.resolve().is_relative_to(root):
                        raise ValueError('MAP/C source links are unsupported')
                    if len(sources) >= _MAX_SOURCE_FILES:
                        raise ValueError('MAP/C fallback exceeds source file limit')
                    text, fp = _source_snapshot(path, remaining)
                    remaining -= fp['size']
                    sources.append((path.resolve(), _global_source(text), fp))
            return cls(tuple(maps), tuple(sources))
        except (OSError, ValueError) as error:
            return cls(error=str(error))

    def resolve(self, name: str):
        if not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*', name):
            return None
        if self.error:
            raise ValueError(self.error)
        from mklink.file_content import source_fingerprint
        from mklink.symbol_catalog import SymbolSourceChangedError
        def fresh(path, fp):
            try:
                if source_fingerprint(path) == fp:
                    return
            except OSError:
                pass
            raise SymbolSourceChangedError('MAP/C source changed; explicitly reparse symbols before variable access')
        symbols = []
        for path, text, fp in self.maps:
            fresh(path, fp)
            symbol = _parse_map_symbol(text, name)
            if symbol:
                symbols.append(symbol)
        if not symbols:
            return None
        if len({row[:2] for row in symbols}) != 1:
            raise ValueError('Ambiguous MAP sources for: ' + name)
        words = '|'.join(sorted(map(re.escape, _C_TYPE_ALIASES), key=len, reverse=True))
        declaration = re.compile(
            rf'(?:^|(?<=;))\s*(?P<qualifiers>(?:static\s+|extern\s+|volatile\s+|const\s+)*)'
            rf'(?P<type>{words})\s+(?P<declarator>[^;]*\b{re.escape(name)}\b[^;]*);', re.M)
        types, definitions = [], 0
        for path, text, fp in self.sources:
            for match in declaration.finditer(text):
                fresh(path, fp)
                if re.search(r'^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif|define|undef)\b', text, re.M):
                    raise ValueError('MAP fallback cannot evaluate C preprocessor declarations: ' + name)
                tail = match['declarator'].strip()
                if not re.fullmatch(rf'{re.escape(name)}\s*(?:=[^,;]*)?', tail):
                    raise ValueError('MAP fallback requires an unambiguous basic scalar: ' + name)
                types.append(_C_TYPE_ALIASES[match['type']])
                definitions += 'extern' not in match['qualifiers'].split()
        if not types or len(set(types)) != 1 or definitions != 1:
            raise ValueError('Missing or ambiguous C scalar type for: ' + name)
        address, map_size, _ = symbols[0]
        type_name = types[0]
        size = TYPE_FORMATS[type_name][1]
        if (map_size and size > map_size) or not 0 <= address <= 0x100000000 - size:
            raise ValueError('MAP scalar exceeds symbol range: ' + name)
        return address, type_name, size


def resolve_variable_path(info: DwarfInfo, path: str) -> tuple[int, str, int, dict[int, str] | None]:
    parts = path.split(".")
    var = info.variables.get(parts[0])
    if not var or var.address is None:
        raise KeyError(f"variable '{parts[0]}' not found or has no address")
    address = var.address
    type_name = var.type_name
    size = var.size
    enum_values = None
    for field_name in parts[1:]:
        st = info.structs.get(type_name)
        if not st:
            raise KeyError(f"'{type_name}' is not a known struct")
        member = next((m for m in st.members if m.name == field_name), None)
        if not member:
            raise KeyError(f"field '{field_name}' not found in {type_name}")
        address += member.offset
        type_name = member.type_name
        size = member.size
    if type_name in info.enums:
        enum_values = info.enums[type_name].values
        size = info.enums[type_name].size
    return address, type_name, size, enum_values


def validate_watch_names(names):
    if (not isinstance(names, list) or not 1 <= len(names) <= 16
            or any(not isinstance(name, str) or not name.strip() or len(name) > 256 for name in names)):
        raise ValueError('Watch requires 1..16 scalar variable paths')
    names = [name.strip() for name in names]
    if len(set(names)) != len(names):
        raise ValueError('Watch variable paths must be unique')
    return names


def read_watch_values(device, names: list[str]) -> list[dict]:
    from mklink.symbol_catalog import SymbolCatalogError, decode_descriptor
    names = validate_watch_names(names)
    catalog = device.symbol_catalog
    if catalog is None:
        raise SymbolCatalogError('Load an AXF/ELF catalog in the shared backend first')
    catalog.require_fresh_source()
    descriptors = [catalog.read_descriptor(name) for name in names]
    payloads = device.read_memory_regions([(d.address, d.size) for d in descriptors])
    if len(payloads) != len(descriptors) or any(not isinstance(data, bytes) or len(data) != d.size
                                               for d, data in zip(descriptors, payloads)):
        raise RuntimeError('Incomplete watch snapshot')
    catalog.require_fresh_source()
    # Do not publish values decoded against MAP/C evidence changed during I/O.
    for d in descriptors:
        if d.source == 'map':
            catalog.read_descriptor(d.path)
    rows = []
    for descriptor, data in zip(descriptors, payloads):
        value = decode_descriptor(descriptor, data)
        if descriptor.scalar_kind == 'enum':
            labels = {number: label for label, number in descriptor.enum_values.items()}
            if value in labels:
                value = f'{value} ({labels[value]})'
        rows.append({'name': descriptor.path, 'address': f'0x{descriptor.address:08X}',
                     'type': descriptor.type_name, 'size': descriptor.size, 'value': value})
    return rows


def format_watch_rows(rows: list[dict], *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(rows, ensure_ascii=False, indent=2)
    if not rows:
        return "No variables"
    name_w = max(len(r["name"]) for r in rows)
    lines = []
    for r in rows:
        lines.append(f"{r['name']:<{name_w}} = {r['value']}  {r['type']} @ {r['address']}")
    return "\n".join(lines)
