from pathlib import Path

import pytest

from mklink.cmsis_dap.errors import FlashError
from mklink.cmsis_dap.images import ImageInspector
from mklink.hpm_image import prepare_hpm_hex


def record(kind, address, data=b''):
    body = bytes([len(data), address >> 8, address & 255, kind]) + data
    return ':' + (body + bytes([-sum(body) & 255])).hex() + '\n'


def test_canonical_hex_preserves_sparse_unordered_same_sector_and_64k_crossing(tmp_path):
    source, output = tmp_path / 'input.hex', tmp_path / 'output.hex'
    source.write_text(record(4, 0, b'\x80\x00') + record(0, 0x480, b'late')
                      + record(0, 0x400, b'early') + record(0, 0xfff0, bytes(range(32)))
                      + record(4, 0, b'\x8f\xff') + record(0, 0xffff, b'Z') + record(1, 0))
    expected = ImageInspector.decode_hex(source)
    assert prepare_hpm_hex(source, output) == expected[0]
    assert ImageInspector.decode_hex(output) == expected
    assert output.stat().st_size < 1024  # The 256 MiB address span is never filled.
    assert max(len(line) for line in output.read_bytes().splitlines()) <= 267


@pytest.mark.parametrize('content', [
    record(4, 0, b'\x90\x00') + record(0, 0, b'x') + record(1, 0),
    record(4, 0, b'\x8f\xff') + record(0, 0xffff, b'xx') + record(1, 0),
    record(4, 0, b'\x80\x00') + record(0, 0, b'xx') + record(0, 1, b'y') + record(1, 0),
    record(4, 0, b'\x80\x00') + record(0, 0, b'x'),
    ':010000007F81\n' + record(1, 0),  # Invalid checksum.
    record(1, 0),
])
def test_invalid_hex_never_replaces_staged_output(tmp_path, content):
    source, output = tmp_path / 'input.hex', tmp_path / 'output.hex'
    source.write_text(content)
    output.write_bytes(b'previous artifact')
    with pytest.raises(FlashError):
        prepare_hpm_hex(source, output)
    assert output.read_bytes() == b'previous artifact'
    assert not list(tmp_path.glob('.hpm-*'))


def test_source_is_not_replaced(tmp_path):
    source = tmp_path / 'input.hex'
    source.write_bytes(b'original')
    with pytest.raises(ValueError, match='source'):
        prepare_hpm_hex(source, source)
    assert source.read_bytes() == b'original'
