"""Shared target memory access helpers for MKLink debug commands."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from mklink.bridge import MKLinkSerialBridge


BATCH_READ_MAX_REGIONS = 16
BATCH_READ_MAX_TOTAL_BYTES = 4096


def validate_memory_regions(regions):
    """Validate a bounded public batch before any target access."""
    if not isinstance(regions, list) or not regions:
        raise ValueError("regions must be a non-empty list")
    if len(regions) > BATCH_READ_MAX_REGIONS:
        raise ValueError(f"regions must contain at most {BATCH_READ_MAX_REGIONS} entries")
    pairs = []
    for index, region in enumerate(regions):
        if not isinstance(region, dict) or set(region) != {"address", "size"}:
            raise ValueError(f"regions[{index}] must contain exactly address and size")
        address, size = region["address"], region["size"]
        if (type(address) is not int or type(size) is not int
                or not 1 <= size <= BATCH_READ_MAX_TOTAL_BYTES
                or not 0 <= address <= 0x100000000 - size):
            raise ValueError(f"regions[{index}] requires a 32-bit integer address and size between 1 and 4096")
        pairs.append((address, size))
    if sum(size for _, size in pairs) > BATCH_READ_MAX_TOTAL_BYTES:
        raise ValueError(f"total requested bytes must not exceed {BATCH_READ_MAX_TOTAL_BYTES}")
    return pairs


def read_memory_regions(device, regions):
    """Use Device's existing range merging; reject incomplete results without replay.

    Adjacent/overlapping ranges may share one read. Gaps are never read and
    output preserves request order. Separate reads are not an atomic snapshot.
    """
    pairs = validate_memory_regions(regions)
    payloads = device.read_memory_regions(pairs)
    if (len(payloads) != len(pairs)
            or any(not isinstance(payload, bytes) or len(payload) != size
                   for (_, size), payload in zip(pairs, payloads))):
        raise RuntimeError("Incomplete batch memory response; command was not retried")
    return {"region_count": len(pairs), "total_bytes": sum(size for _, size in pairs),
            "regions": [{"address": f"0x{address:08X}", "size": size, "hex": payload.hex()}
                        for (address, size), payload in zip(pairs, payloads)]}


_HEX_DUMP_HEADER_RE = re.compile(
    r"^\s*([0-9a-fA-F]{8})\s+00\s+01\s+02\s+03\s+04\s+05\s+06\s+07\s+08\s+09\s+0A\s+0B\s+0C\s+0D\s+0E\s+0F\s*$",
    re.IGNORECASE,
)
_HEX_DUMP_RE = re.compile(r"^\s*([0-9a-fA-F]{8})\s+((?:[0-9a-fA-F]{2}\s+){0,15}[0-9a-fA-F]{2})\b")


def parse_read_ram_response(response: str) -> bytes:
    """Extract bytes from the hex dump text returned by ``cmd.read_ram``.

    Returns an empty bytes object when the response does not contain a
    parseable dump. Callers should retain and display the raw response.
    """
    data = bytearray()
    header_seen = False
    for line in response.splitlines():
        # Only the leading timestamp row is a header. RAM can contain 00..0F.
        if not header_seen and not data and _HEX_DUMP_HEADER_RE.match(line):
            header_seen = True
            continue
        m = _HEX_DUMP_RE.match(line)
        if not m:
            continue
        for token in m.group(2).split():
            data.append(int(token, 16))
    return bytes(data)


def read_memory(
    port: str | None,
    address: int | str,
    size: int,
    *,
    save: str | None = None,
    timeout: float = 10.0,
    bridge: "MKLinkSerialBridge | None" = None,
    project_root: str = ".",
) -> tuple[bytes, str]:
    """Read target memory via MKLink ``cmd.read_ram``.

    Returns ``(parsed_bytes, raw_response)``. The parsed bytes may be empty if
    the device firmware returned a format this parser does not understand.

    Args:
        bridge: Optional pre-connected bridge instance. If provided, the
            port parameter is ignored and no new connection is created (and no
            target init is performed — the persistent session is expected to be
            already initialized, e.g. via a Device).
        project_root: Used only when opening a fresh bridge, for MCU profile
            matching during SWD DP init.
    """
    from mklink.bridge import MKLinkSerialBridge

    addr_s = f"0x{address:08X}" if isinstance(address, int) else address

    if bridge is not None:
        if save:
            cmd = f'cmd.read_ram({addr_s}, {size}, "{save}")'
        else:
            cmd = f"cmd.read_ram({addr_s}, {size})"
        raw = bridge.send_command(cmd, timeout=timeout)
        return parse_read_ram_response(raw), raw

    from mklink.cli import _resolve_port
    port = _resolve_port(port)
    bridge = MKLinkSerialBridge(port)
    if not bridge.connect():
        raise ConnectionError("MKLink connection failed")
    # SWD DP init + IDCODE for this fresh per-op session. Previously this
    # path relied entirely on the probe firmware re-running cmd.get_idcode()
    # when the serial port reopened; make it explicit and set _ctx.idcode so
    # callers that read it get a real value. Tolerant (no target → idcode 0).
    from mklink.flash import MKLinkFlash
    from mklink.device import initialize_target
    initialize_target(bridge, MKLinkFlash(bridge), project_root=project_root)
    try:
        if save:
            cmd = f'cmd.read_ram({addr_s}, {size}, "{save}")'
        else:
            cmd = f"cmd.read_ram({addr_s}, {size})"
        raw = bridge.send_command(cmd, timeout=timeout)
        return parse_read_ram_response(raw), raw
    finally:
        bridge.close()
