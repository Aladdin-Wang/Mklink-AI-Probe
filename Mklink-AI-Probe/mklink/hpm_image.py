"""Canonical HPM HEX staging shared by online and offline download paths.

Parsing remains owned by ImageInspector. Output is ordered, non-overlapping
Intel HEX; sparse holes are retained, never expanded into a giant BIN.
"""
from pathlib import Path
import os
import tempfile

from .cmsis_dap.images import ImageInspector
from .cmsis_dap.errors import FlashError, FlashErrorCode


def _record(kind: int, address: int, data: bytes) -> bytes:
    body = bytes([len(data), address >> 8, address & 255, kind]) + data
    return b":" + (body + bytes([-sum(body) & 255])).hex().upper().encode("ascii") + b"\n"


def decode_hpm_hex(source: Path):
    segments, chunks = ImageInspector.decode_hex(source, max_decoded_size=32 * 1024 * 1024)
    for segment, payload in chunks:
        if not 0x80000000 <= segment.start < segment.start + len(payload) <= 0x90000000:
            raise FlashError(FlashErrorCode.FILE_FORMAT_ERROR, "HPM HEX data is outside mapped XPI flash")
    return segments, chunks


def prepare_hpm_hex(source: Path, destination: Path):
    """Validate all input before replacing a caller-owned staging file.

    Both bounds mirror the application reader. Callers still validate against
    the actual board flash capacity before scheduling any destructive work.
    """
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("HPM HEX staging must not overwrite its source")
    segments, chunks = decode_hpm_hex(source)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".hpm-", delete=False) as stream:
            temporary = Path(stream.name)
            upper = None
            for segment, payload in chunks:
                offset = 0
                while offset < len(payload):
                    address = segment.start + offset
                    if address >> 16 != upper:
                        upper = address >> 16
                        stream.write(_record(4, 0, upper.to_bytes(2, "big")))
                    count = min(128, len(payload) - offset, 0x10000 - (address & 0xffff))
                    stream.write(_record(0, address & 0xffff, payload[offset:offset + count]))
                    offset += count
            stream.write(_record(1, 0, b""))
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return segments
