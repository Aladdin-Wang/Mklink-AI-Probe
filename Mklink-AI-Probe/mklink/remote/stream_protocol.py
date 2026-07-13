"""Versioned binary frames for high-throughput remote streams."""

from __future__ import annotations

import struct
import math
from dataclasses import dataclass
from enum import IntEnum


MAGIC = b"MKST"
VERSION = 1
HEADER = struct.Struct("<4sBBBBIQQII")
HEADER_SIZE = HEADER.size
MAX_PAYLOAD_SIZE = 4 * 1024 * 1024

# WAVEFORM payload is little-endian Float32 in sample-major order.
WAVEFORM_SAMPLE_MAJOR_FLOAT32 = 0x01

# SystemView v1 events are fixed-size so producers and browser Workers can
# process batches without JSON allocation or another serialization package.
SYSTEMVIEW_EVENT_RECORD = struct.Struct("<BBHIQdddd")
SYSTEMVIEW_EVENT_RECORD_SIZE = SYSTEMVIEW_EVENT_RECORD.size
SYSTEMVIEW_HAS_TICKS = 0x01
SYSTEMVIEW_HAS_TIME_US = 0x02
SYSTEMVIEW_HAS_DELTA_US = 0x04

SYSTEMVIEW_EVENT_KINDS = {
    "overflow": 1,
    "isr_enter": 2,
    "isr_exit": 3,
    "task_start_exec": 4,
    "task_stop_exec": 5,
    "task_start_ready": 6,
    "task_stop_ready": 7,
    "task_create": 8,
    "task_info": 9,
    "trace_start": 10,
    "trace_stop": 11,
    "systime_cycles": 12,
    "systime_us": 13,
    "sysdesc": 14,
    "user_start": 15,
    "user_stop": 16,
    "idle": 17,
    "isr_to_scheduler": 18,
    "timer_enter": 19,
    "timer_exit": 20,
    "stack_info": 21,
    "moduledesc": 22,
    "raw": 23,
    "init": 24,
    "name_resource": 25,
    "print_formatted": 26,
    "nummodules": 27,
    "end_call": 28,
    "task_terminate": 29,
}
SYSTEMVIEW_EVENT_NAMES = {value: key for key, value in SYSTEMVIEW_EVENT_KINDS.items()}


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


def _systemview_number(event: dict, *names: str) -> float:
    for name in names:
        value = event.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value):
                raise ValueError(f"SystemView field {name!r} must be finite")
            return float(value)
    return 0.0


def _systemview_context_id(event: dict) -> int:
    for name in (
        "task_id", "isr_id", "resource_id", "timer_id",
        "user_id", "module_id", "event_id",
    ):
        if name not in event or event[name] is None:
            continue
        value = event[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 0xFFFFFFFF
        ):
            raise ValueError(
                "SystemView context id must be an unsigned 32-bit integer"
            )
        return value
    return 0


def encode_systemview_events(events) -> bytes:
    """Encode decoded SystemView dictionaries as fixed 48-byte v1 records."""
    payload = bytearray(SYSTEMVIEW_EVENT_RECORD_SIZE * len(events))
    for index, event in enumerate(events):
        kind_name = str(event.get("kind") or "")
        kind = SYSTEMVIEW_EVENT_KINDS.get(kind_name)
        raw_event_id = None
        if kind is None and kind_name.startswith("raw_"):
            try:
                raw_event_id = int(kind_name[4:])
            except ValueError:
                raw_event_id = None
            if raw_event_id is not None and 512 <= raw_event_id <= 4096:
                kind = SYSTEMVIEW_EVENT_KINDS["raw"]
        if kind is None:
            raise ValueError(f"unknown SystemView event kind: {kind_name!r}")
        flags = 0
        ticks = event.get("t_ticks")
        if isinstance(ticks, int) and not isinstance(ticks, bool) and 0 <= ticks <= 0xFFFFFFFFFFFFFFFF:
            flags |= SYSTEMVIEW_HAS_TICKS
        elif ticks is not None:
            raise ValueError("SystemView field 't_ticks' must be an unsigned 64-bit integer")
        else:
            ticks = 0
        time_us = event.get("t_us")
        if isinstance(time_us, (int, float)) and not isinstance(time_us, bool):
            if not math.isfinite(time_us):
                raise ValueError("SystemView field 't_us' must be finite")
            flags |= SYSTEMVIEW_HAS_TIME_US
        else:
            time_us = 0.0
        delta_us = event.get("cpu_delta_us")
        if isinstance(delta_us, (int, float)) and not isinstance(delta_us, bool):
            if not math.isfinite(delta_us):
                raise ValueError("SystemView field 'cpu_delta_us' must be finite")
            flags |= SYSTEMVIEW_HAS_DELTA_US
        else:
            delta_us = 0.0
        context_id = (
            raw_event_id
            if raw_event_id is not None
            else _systemview_context_id(event)
        )
        if not 0 <= context_id <= 0xFFFFFFFF:
            raise ValueError("SystemView context id must be an unsigned 32-bit integer")
        aux0 = _systemview_number(
            event, "prio", "cause", "drop_count", "cpu_freq", "systime",
            "stack_base", "options", "num_modules",
        )
        aux1 = _systemview_number(
            event, "stack_size", "sys_freq", "ram_base", "num_args", "id_shift",
        )
        SYSTEMVIEW_EVENT_RECORD.pack_into(
            payload,
            index * SYSTEMVIEW_EVENT_RECORD_SIZE,
            kind,
            flags,
            0,
            context_id & 0xFFFFFFFF,
            ticks,
            float(time_us),
            float(delta_us),
            aux0,
            aux1,
        )
    return bytes(payload)


def decode_systemview_events(payload: bytes) -> list[dict]:
    """Decode fixed SystemView v1 records for tests and non-browser clients."""
    if len(payload) % SYSTEMVIEW_EVENT_RECORD_SIZE:
        raise ValueError("SystemView payload must be a multiple of the record size")
    events = []
    task_kinds = {4, 5, 6, 7, 8, 9, 21, 29}
    for offset in range(0, len(payload), SYSTEMVIEW_EVENT_RECORD_SIZE):
        kind, flags, reserved, context_id, ticks, time_us, delta_us, aux0, aux1 = (
            SYSTEMVIEW_EVENT_RECORD.unpack_from(payload, offset)
        )
        if not all(
            math.isfinite(value)
            for value in (time_us, delta_us, aux0, aux1)
        ):
            raise ValueError("SystemView numeric fields must be finite")
        if (flags & ~(SYSTEMVIEW_HAS_TICKS | SYSTEMVIEW_HAS_TIME_US | SYSTEMVIEW_HAS_DELTA_US)
                or reserved != 0 or kind not in SYSTEMVIEW_EVENT_NAMES):
            raise ValueError("malformed SystemView event record")
        if kind == SYSTEMVIEW_EVENT_KINDS["raw"]:
            event = {"kind": f"raw_{context_id}"}
        else:
            event = {"kind": SYSTEMVIEW_EVENT_NAMES[kind]}
        if flags & SYSTEMVIEW_HAS_TICKS:
            event["t_ticks"] = ticks
        if flags & SYSTEMVIEW_HAS_TIME_US:
            event["t_us"] = time_us
        if flags & SYSTEMVIEW_HAS_DELTA_US:
            event["cpu_delta_us"] = delta_us
        if kind == SYSTEMVIEW_EVENT_KINDS["raw"]:
            event["event_id"] = context_id
        elif kind in task_kinds:
            event["task_id"] = context_id
        elif kind == 2:
            event["isr_id"] = context_id
        elif context_id:
            event["resource_id"] = context_id
        if kind == 9:
            event["prio"] = int(aux0)
            event["stack_size"] = int(aux1)
        elif kind == 7:
            event["cause"] = int(aux0)
        events.append(event)
    return events
