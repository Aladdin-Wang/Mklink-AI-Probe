"""Shared VOFA channel validation, catalog resolution and waveform encoding."""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct

from mklink.remote.stream_protocol import WAVEFORM_SAMPLE_MAJOR_FLOAT32

VOFA_TYPE_INFO = {
    "int8_t": {"type": "int8_t", "size": 1},
    "uint8_t": {"type": "uint8_t", "size": 1},
    "int16_t": {"type": "int16_t", "size": 2},
    "uint16_t": {"type": "uint16_t", "size": 2},
    "int32_t": {"type": "int32_t", "size": 4},
    "uint32_t": {"type": "uint32_t", "size": 4},
    "float": {"type": "float", "size": 4},
    "bool": {"type": "bool", "size": 1},
}

_VOFA_TYPE_ALIASES = {
    "char": "int8_t", "int8": "int8_t", "int8_t": "int8_t",
    "uchar": "uint8_t", "uint8": "uint8_t", "uint8_t": "uint8_t",
    "short": "int16_t", "int16": "int16_t", "int16_t": "int16_t",
    "ushort": "uint16_t", "uint16": "uint16_t", "uint16_t": "uint16_t",
    "int": "int32_t", "int32": "int32_t", "int32_t": "int32_t",
    "uint": "uint32_t", "uint32": "uint32_t", "uint32_t": "uint32_t",
    "float": "float", "fp32": "float",
    "bool": "bool", "boolean": "bool",
}


# WAVEFORM frame flag bit 0: payload is little-endian Float32 values in
# sample-major order: sample0.channel0..N, sample1.channel0..N, ... .
VOFA_SAMPLE_MAJOR_FLOAT32 = WAVEFORM_SAMPLE_MAJOR_FLOAT32
VOFA_MAX_READ_BLOCK = 2048


@dataclass(frozen=True)
class VofaChannelRead:
    channel_index: int
    offset: int
    size: int
    type_name: str


@dataclass(frozen=True)
class VofaReadGroup:
    address: int
    size: int
    channels: tuple[VofaChannelRead, ...]


def encode_vofa_samples(samples) -> bytes:
    """Encode rows of numeric channel values as sample-major Float32."""
    rows = [tuple(row) for row in samples]
    if not rows:
        return b""
    channel_count = len(rows[0])
    if channel_count <= 0 or any(len(row) != channel_count for row in rows):
        raise ValueError("VOFA samples must have one consistent channel count")
    values = []
    for row in rows:
        for value in row:
            number = float(value)
            if not math.isfinite(number):
                number = 0.0
            values.append(number)
    return struct.pack(f"<{len(values)}f", *values)


def decode_vofa_samples(payload: bytes, channel_count: int) -> list[tuple[float, ...]]:
    """Decode a sample-major Float32 payload (used by tests/clients)."""
    if channel_count <= 0:
        raise ValueError("channel_count must be positive")
    row_size = channel_count * 4
    if len(payload) % row_size:
        raise ValueError("VOFA payload is not aligned to complete samples")
    values = struct.unpack(f"<{len(payload) // 4}f", payload) if payload else ()
    return [
        tuple(values[index:index + channel_count])
        for index in range(0, len(values), channel_count)
    ]


def build_vofa_read_groups(
    channels: list[dict], *, max_block_size: int = VOFA_MAX_READ_BLOCK,
) -> list[VofaReadGroup]:
    """Group channels into 4-byte-aligned, bounded target reads."""
    if max_block_size < 4:
        raise ValueError("max_block_size must allow one aligned word")
    channels = normalize_vofa_channels(channels)
    normalized = []
    for index, channel in enumerate(channels):
        address = channel["addr"]
        size = channel["size"]
        aligned_start = address & ~0x3
        aligned_end = (address + size + 3) & ~0x3
        if aligned_end - aligned_start > max_block_size:
            raise ValueError("VOFA channel size exceeds the safe read limit")
        normalized.append((
            aligned_start, aligned_end, address, size, index, channel["type"],
        ))
    normalized.sort(key=lambda item: (item[0], item[2]))
    groups = []
    pending = []
    group_start = group_end = None
    for aligned_start, aligned_end, address, size, index, type_name in normalized:
        can_join = (
            group_start is not None
            and aligned_start <= group_end
            and max(group_end, aligned_end) - group_start <= max_block_size
        )
        if not can_join and pending:
            groups.append(VofaReadGroup(
                group_start, group_end - group_start, tuple(pending),
            ))
            pending = []
            group_start = group_end = None
        if group_start is None:
            group_start, group_end = aligned_start, aligned_end
        else:
            group_end = max(group_end, aligned_end)
        pending.append(VofaChannelRead(index, address - group_start, size, type_name))
    if pending:
        groups.append(VofaReadGroup(
            group_start, group_end - group_start, tuple(pending),
        ))
    return groups


def normalize_vofa_type(type_token: str) -> dict[str, int | str] | None:
    """Normalize a VOFA input type alias to canonical C type metadata."""
    key = type_token.strip().lower()
    canonical = _VOFA_TYPE_ALIASES.get(key)
    if not canonical:
        return None
    info = VOFA_TYPE_INFO[canonical]
    return {"input": type_token, "type": info["type"], "size": info["size"]}


def normalize_vofa_channels(channels: list[dict]) -> list[dict]:
    """Validate and canonicalize one complete VOFA channel snapshot."""
    if not isinstance(channels, list) or not 1 <= len(channels) <= 64:
        raise ValueError("VOFA channel count must be between 1 and 64")
    normalized = []
    names = set()
    for index, channel in enumerate(channels):
        if not isinstance(channel, dict):
            raise ValueError(f"VOFA channel {index} must be an object")
        try:
            raw_address = channel["addr"]
            if type(raw_address) not in (int, str):
                raise ValueError
            address = int(raw_address, 0) if isinstance(raw_address, str) else int(raw_address)
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"VOFA channel {index} has an invalid 32-bit address") from None
        type_token = str(channel.get("type", "float"))
        type_info = normalize_vofa_type(type_token)
        if type_info is None:
            raise ValueError(f"VOFA channel {index} uses unsupported type {type_token!r}")
        canonical_size = int(type_info["size"])
        try:
            size = channel.get("size", canonical_size)
            if type(size) is not int:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"VOFA channel {index} has an invalid size") from None
        if size != canonical_size:
            raise ValueError(
                f"VOFA channel {index} size {size} does not match "
                f"{type_info['type']} size {canonical_size}"
            )
        if address < 0 or address > 0xFFFFFFFF or address + size > 0x100000000:
            raise ValueError(f"VOFA channel {index} exceeds the 32-bit address space")
        default_name = f"0x{address:08x}"
        name = channel.get("name", default_name)
        if not isinstance(name, str) or len(name) > 256:
            raise ValueError("VOFA channel name must be a string of at most 256 characters")
        name = name.strip()
        if not name:
            raise ValueError(f"VOFA channel {index} name must not be empty")
        if name in {"_t", "_seq", "event", "_event"}:
            raise ValueError("VOFA channel name is reserved for stream metadata")
        if name in names:
            raise ValueError("VOFA channel names must be unique")
        names.add(name)
        normalized.append({
            "name": name,
            "addr": address,
            "type": str(type_info["type"]),
            "size": canonical_size,
        })
    return normalized


def parse_vofa_inputs(variables: list[str], names: str | None = None) -> list[dict]:
    """Parse CLI input without a connection or a second symbol parser."""
    import re
    if (not isinstance(variables, list) or not variables or len(variables) > 128
            or any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in variables)):
        raise ValueError('Specify VOFA scalar paths, address/type pairs, or address/count')
    values = [value.strip() for value in variables]
    path_pattern = r'[A-Za-z_$][A-Za-z0-9_$]*(?:(?:\.[A-Za-z_$][A-Za-z0-9_$]*)|(?:\[\d+\]))*'
    def channel(token, type_name=None):
        if token.lower().startswith('0x') or token.isdecimal():
            if type_name is None:
                raise ValueError('Raw VOFA addresses require an explicit type')
            return {'addr': int(token, 0), 'type': type_name}
        if not re.fullmatch(path_pattern, token):
            raise ValueError('Invalid VOFA scalar path or address: ' + token)
        return {'path': token, **({'type': type_name} if type_name else {})}
    if len(values) == 2 and values[1].isdecimal():
        count = int(values[1])
        if not 1 <= count <= 16:
            raise ValueError('VOFA contiguous float count must be 1..16')
        base = channel(values[0], 'float')
        channels = ([{'addr': base['addr'] + i * 4, 'type': 'float'} for i in range(count)]
                    if 'addr' in base else [{'path': f"{base['path']}[{i}]", 'type': 'float'} for i in range(count)])
    elif any(value.lower().startswith('0x') or normalize_vofa_type(value) for value in values):
        if len(values) % 2:
            raise ValueError('VOFA requires complete address/type or path/type pairs')
        channels = []
        for offset in range(0, len(values), 2):
            info = normalize_vofa_type(values[offset+1])
            if info is None:
                raise ValueError('Unsupported VOFA type: ' + values[offset+1])
            channels.append(channel(values[offset], str(info['type'])))
    else:
        channels = [channel(value) for value in values]
    if names is not None:
        labels = [name.strip() for name in names.split(',')]
        if len(labels) != len(channels) or any(not name or len(name) > 256 for name in labels) or len(set(labels)) != len(labels):
            raise ValueError('VOFA names must be unique and match the channel count')
        for item, label in zip(channels, labels):
            item['name'] = label
    if len(channels) > 64:
        raise ValueError('VOFA channel count must be 1..64')
    # Raw requests can be fully checked before starting/attaching a backend.
    if all('addr' in item for item in channels):
        channels = normalize_vofa_channels(channels)
        validate_vofa_groups(channels, .001)
    return channels


def validate_vofa_groups(channels, interval):
    from mklink.dump_memory import build_dump_mem_command
    groups = build_vofa_read_groups(channels)
    build_dump_mem_command([(group.address, group.size) for group in groups], interval)
    return groups


def resolve_vofa_channels(device, channels):
    """Resolve symbols against the current backend catalog, then normalize once."""
    if not isinstance(channels, list) or not 1 <= len(channels) <= 64:
        raise ValueError('VOFA channel count must be 1..64')
    catalog = getattr(device, 'symbol_catalog', None)
    normalized = []
    for item in channels:
        if not isinstance(item, dict):
            raise ValueError('VOFA channels must be objects')
        if 'path' not in item:
            normalized.append(item)
            continue
        if (set(item) - {'path', 'name', 'type'} or not isinstance(item['path'], str)
                or not item['path'].strip() or len(item['path']) > 256):
            raise ValueError('Symbolic VOFA channels require path, optional name and type')
        if catalog is None:
            raise ValueError('Load an AXF/ELF catalog before selecting VOFA symbols')
        catalog.require_fresh_source()
        descriptor = catalog.read_descriptor(item['path'])
        kind, size = descriptor.scalar_kind, descriptor.size
        if kind == 'enum':
            kind = 'signed' if descriptor.enum_signed else 'unsigned'
        canonical = ('float' if kind == 'float' and size == 4 else 'bool' if kind == 'bool' and size == 1
                     else f"{'u' if kind == 'unsigned' else ''}int{size*8}_t"
                     if kind in {'signed', 'unsigned'} and size in (1,2,4) else None)
        requested = normalize_vofa_type(str(item['type'])) if 'type' in item else None
        if canonical is None or ('type' in item and (requested is None or requested['type'] != canonical)):
            raise ValueError('VOFA type does not match a supported catalog scalar: ' + item['path'])
        normalized.append({'name': item.get('name', descriptor.path), 'addr': descriptor.address,
                           'type': canonical, 'size': size})
    return normalize_vofa_channels(normalized)
