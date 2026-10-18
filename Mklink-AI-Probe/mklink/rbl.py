"""V2 application RBL validation for the existing 384 KiB bootloader ABI."""
from pathlib import Path
import re
import struct
import zlib

HEADER_SIZE = 96
PAYLOAD_LIMIT = 0x80070000 - 0x80010400


def validate_rbl(path: str | Path, *, version: str | None = None) -> int:
    """Reject unsupported packaging and images overlapping upgrade metadata."""
    path = Path(path)
    if not HEADER_SIZE < path.stat().st_size <= HEADER_SIZE + PAYLOAD_LIMIT:
        raise ValueError('RBL exceeds the V2 application payload boundary or is empty')
    data = path.read_bytes()
    magic, algorithm, algorithm2, _, partition, raw_version, _, crc, _, raw_size, size, head_crc = struct.unpack(
        '<4sHHI16s24s24sIIIII', data[:HEADER_SIZE])
    if magic != b'RBL\0' or algorithm or algorithm2:
        raise ValueError('Only uncompressed, unencrypted V2 RBL is supported')
    if partition != b'MicroLink'.ljust(16, b'\0'):
        raise ValueError('RBL must target the MicroLink application partition')
    try:
        parsed_version = raw_version.split(b'\0', 1)[0].decode('ascii')
    except UnicodeError as error:
        raise ValueError('Invalid RBL version') from error
    if (not re.fullmatch(r'V2\.\d+\.\d+', parsed_version)
            or raw_version != parsed_version.encode().ljust(24, b'\0')
            or (version is not None and parsed_version != version)):
        raise ValueError('RBL header version/model does not match firmware name')
    if size != raw_size or size % 4 or size != len(data) - HEADER_SIZE:
        raise ValueError('Invalid RBL payload length or alignment')
    if zlib.crc32(data[:92]) != head_crc or zlib.crc32(data[HEADER_SIZE:]) != crc:
        raise ValueError('RBL CRC32 mismatch')
    return size
