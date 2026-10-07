"""Word batching must preserve the address, width and signedness of each value."""
import struct
from types import SimpleNamespace

import pytest

from mklink.superwatch import WatchItem, SuperWatchRuntime, build_read_blocks, compile_frame_decoder
from mklink.mux_watch import PackedWatchSample


RAM = 0x20000000
RANGES = ((RAM, RAM + 256),)


@pytest.mark.parametrize('offset', range(4))
@pytest.mark.parametrize('code,kind,value', [
    ('B', 'unsigned', 0xE7), ('b', 'signed', -105),
    ('H', 'unsigned', 0xC3A5), ('h', 'signed', -12345),
    ('I', 'unsigned', 0xEDCBA987), ('i', 'signed', -123456789),
    ('f', 'float', -123.25), ('B', 'bool', 1),
])
def test_word_padding_preserves_subword_and_cross_word_values(offset, code, kind, value):
    raw = bytearray(b'\x5a' * 16)
    struct.pack_into('<' + code, raw, offset, value)
    item = WatchItem('packed', RAM + offset, 'custom', struct.calcsize(code), scalar_kind=kind)
    blocks = build_read_blocks([item], max_gap=0, ram_ranges=RANGES)
    assert len(blocks) == 1
    block = blocks[0]
    assert block.address == RAM
    assert block.size == ((offset + item.size + 3) & ~3)
    decoder = compile_frame_decoder([item], blocks)
    assert decoder.decode({'regions': [(0, bytes(raw[:block.size]))]}) == [value]
    payload = b'header' + bytes(raw[:block.size])
    assert decoder.decode(PackedWatchSample(123, payload, 6)) == [value]
    assert decoder.decode(PackedWatchSample(123, payload[:-1], 6)) is None
    # A truncated second word cannot silently retain an earlier value.
    assert decoder.decode({'regions': [(0, bytes(raw[:offset + item.size - 1]))]}) is None


def test_overlapping_padded_values_share_one_word_without_changing_channel_order():
    items = [WatchItem('half', RAM + 1, 'uint16_t', 2),
             WatchItem('last', RAM + 3, 'uint8_t', 1),
             WatchItem('first', RAM, 'uint8_t', 1)]
    blocks = build_read_blocks(items, max_gap=0, ram_ranges=RANGES)
    assert [(b.address, b.size) for b in blocks] == [(RAM, 4)]
    assert compile_frame_decoder(items, blocks).decode({'regions': [(0, b'\x12\x34\x56\x78')]}) == [0x5634, 0x78, 0x12]


def test_packed_regions_preserve_layout_bitfields_and_reject_missing_channels():
    items = [WatchItem('half', RAM + 1, 'uint16_t', 2),
             WatchItem('bits', RAM + 32, 'uint32_t', 4, scalar_kind='unsigned',
                       metadata={'bit_offset': 4, 'bit_width': 3})]
    blocks = build_read_blocks(items, max_gap=0, ram_ranges=RANGES)
    decoder = compile_frame_decoder(items, blocks)
    frame = PackedWatchSample(99, b'\x12\x34\x56\x78\x50\x00\x00\x00', 0)
    assert decoder.decode(frame) == [0x5634, 5]
    assert compile_frame_decoder(items, blocks[:1]).decode(frame) is None


@pytest.mark.parametrize('address,size,source,ranges', [
    (RAM + 1, 1, 'ram', ()),                    # unknown memory map
    (RAM + 1, 2, 'ram', ((RAM + 1, RAM + 4),)), # left boundary
    (RAM + 3, 2, 'ram', ((RAM, RAM + 5),)),     # right boundary
    (RAM + 1, 1, 'svd', RANGES),               # peripheral source even in RAM range
    (0x40000001, 2, 'svd', RANGES),
    (0x40000001, 2, 'ram', RANGES),             # address outside confirmed RAM
])
def test_unsafe_padding_keeps_exact_read_width(address, size, source, ranges):
    item = WatchItem('value', address, 'custom', size, source=source, scalar_kind='unsigned')
    block, = build_read_blocks([item], ram_ranges=ranges)
    assert (block.address, block.size) == (address, size)


def test_runtime_passes_catalog_bounds_to_sampling_layout():
    item = WatchItem('byte', RAM + 3, 'uint8_t', 1)
    runtime = SuperWatchRuntime(items=[item], symbol_catalog=SimpleNamespace(_ram_ranges=RANGES))
    assert [(b.address, b.size) for b in runtime.blocks] == [(RAM, 4)]
