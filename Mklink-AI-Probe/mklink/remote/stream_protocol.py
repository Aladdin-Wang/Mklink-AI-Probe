"""Versioned binary frames for high-throughput remote streams."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum


MAGIC = b"MKST"
VERSION = 1
HEADER = struct.Struct("<4sBBBBIQQII")
HEADER_SIZE = HEADER.size
MAX_PAYLOAD_SIZE = 4 * 1024 * 1024


class StreamType(IntEnum):
    SYSTEMVIEW = 1
    WAVEFORM = 2
    RTT_RAW = 3
    SUPERWATCH = 4
    CONTROL = 255


@dataclass(frozen=True)
class Frame:
    stream_type: StreamType
    flags: int
    stream_id: int
    sequence: int
    timestamp_ns: int
    item_count: int
    payload: bytes


def encode_frame(frame: Frame) -> bytes:
    """Encode a frame using the v1 little-endian wire format."""
    try:
        stream_type = StreamType(frame.stream_type)
    except ValueError as exc:
        raise ValueError(f"unknown stream type: {frame.stream_type}") from exc
    payload = bytes(frame.payload)
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ValueError("payload exceeds 4 MiB limit")
    header = HEADER.pack(
        MAGIC,
        VERSION,
        stream_type,
        frame.flags,
        HEADER_SIZE,
        frame.stream_id,
        frame.sequence,
        frame.timestamp_ns,
        frame.item_count,
        len(payload),
    )
    return header + payload


def decode_frame(encoded: bytes) -> Frame:
    """Decode a v1 frame, rejecting malformed or unsupported input."""
    if len(encoded) < HEADER_SIZE:
        raise ValueError("frame is shorter than the 36-byte header size")
    (
        magic,
        version,
        stream_type_value,
        flags,
        header_size,
        stream_id,
        sequence,
        timestamp_ns,
        item_count,
        payload_length,
    ) = HEADER.unpack_from(encoded)
    if magic != MAGIC:
        raise ValueError("invalid stream frame magic")
    if version != VERSION:
        raise ValueError(f"unsupported stream frame version: {version}")
    if header_size != HEADER_SIZE:
        raise ValueError(f"invalid header size: {header_size}")
    try:
        stream_type = StreamType(stream_type_value)
    except ValueError as exc:
        raise ValueError(f"unknown stream type: {stream_type_value}") from exc
    if payload_length > MAX_PAYLOAD_SIZE:
        raise ValueError("payload exceeds 4 MiB limit")
    if len(encoded) - HEADER_SIZE != payload_length:
        raise ValueError("payload length does not match frame size")
    return Frame(
        stream_type,
        flags,
        stream_id,
        sequence,
        timestamp_ns,
        item_count,
        bytes(encoded[HEADER_SIZE:]),
    )
