"""Whole-record samples must yield independent, correctly signed bit-field channels."""
from dataclasses import replace

import pytest

from mklink.dwarf_parser import DwarfInfo, DwarfMember, DwarfStruct, DwarfVariable, DwarfArray, DwarfCache, bitfield_layout
from mklink.symbol_catalog import SymbolCatalog, SymbolCatalogError, SymbolValueError, decode_descriptor, encode_descriptor, rebind_paths
from mklink.superwatch import SuperWatchRuntime, compile_frame_decoder, resolve_watch_items, _member_node
from mklink.mux_watch import PackedWatchSample


def record_info(modern=False):
    info = DwarfInfo(base_types={1: ('uint8_t', 1), 2: ('int32_t', 4)},
                     base_type_encodings={1: 7, 2: 5})
    def bits(name, start, width):
        return DwarfMember(name, 0, 1, 'uint8_t', 1, bit_size=width,
                           **({'data_bit_offset': start} if modern else {'bit_offset': 8-start-width, 'storage_size': 1}))
    record = DwarfStruct('State', 10, 3, [
        bits('run', 0, 1), bits('mode', 1, 2), DwarfMember('sub', 1, 1, 'uint8_t', 1),
        bits('closed', 3, 1), DwarfMember('driver', 2, 1, 'uint8_t', 1), bits('enabled', 4, 1),
    ])
    info.records_by_offset[10] = record
    info.structs['State'] = record
    info.variables['state'] = DwarfVariable('state', 20, 10, 0x20000000, 3, 'State')
    return info


def catalog_for(tmp_path, info, limit=256):
    source = tmp_path/'fixture.elf'
    source.write_bytes(b'fixture source identity')
    return SymbolCatalog.from_dwarf(info, axf_path=str(source), max_leaves_per_root=limit)


@pytest.mark.parametrize('modern', [False, True])
@pytest.mark.parametrize('limit', [1, 256])
def test_complete_three_byte_record_decodes_six_channels(tmp_path, modern, limit):
    info = record_info(modern)
    catalog = catalog_for(tmp_path, info, limit)
    leaves = catalog.search('state', limit=50)
    assert len(leaves) == len(catalog.browse_children('state')) == 6
    assert catalog.browse_roots()[0].child_count == 6
    assert len(catalog.search('state.enabled')) == 1
    runtime = SuperWatchRuntime(items=[], dwarf_info=info, symbol_catalog=catalog)
    for descriptor in leaves:
        assert 'error' not in runtime.add(descriptor.path)
    assert len(runtime.blocks) == 1  # one whole record read, shared by all channels
    block = runtime.blocks[0]
    assert block.address == 0x20000000 and block.size >= 3
    decoder = compile_frame_decoder(runtime.items, runtime.blocks)
    for raw in range(256):
        record = bytes([raw, raw ^ 0x5a, 255 - raw])
        payload = record + bytes(block.size-3)
        expected = {'state.run': raw & 1, 'state.mode': (raw >> 1) & 3,
                    'state.closed': (raw >> 3) & 1, 'state.enabled': (raw >> 4) & 1,
                    'state.sub': raw ^ 0x5a, 'state.driver': 255 - raw}
        for frame in ({'regions': [(0, payload)]}, PackedWatchSample(raw, b'prefix'+payload, 6)):
            assert dict(zip(decoder.channel_names, decoder.decode(frame))) == expected
        for descriptor in leaves:
            offset = descriptor.address - block.address
            assert decode_descriptor(descriptor, payload[offset:]) == expected[descriptor.path]
            if descriptor.bit_size is not None:
                assert not descriptor.writable
                with pytest.raises(SymbolValueError):
                    encode_descriptor(descriptor, 1)
                with pytest.raises(SymbolCatalogError):
                    catalog.require(descriptor.path, catalog.generation)
    assert decoder.decode({'regions': [(0, b'\x00')]}) is None
    legacy_items = resolve_watch_items(['state.mode'], dwarf_info=info)
    assert legacy_items[0].metadata['bit_offset'] == 1
    assert _member_node(info.structs['State'].members[1], b'\x06\x00\x00', info, depth=0)['value'] == 3


@pytest.mark.parametrize('modern', [False, True])
def test_nested_array_cross_byte_signed_fields_and_cache(tmp_path, modern):
    info = record_info(modern)
    field = DwarfMember('delta', 0, 2, 'int32_t', 4, bit_size=17,
                        **({'data_bit_offset': 11} if modern else {'bit_offset': 4, 'storage_size': 4}))
    record = DwarfStruct('Packed', 30, 4, [field])
    info.records_by_offset[30] = record
    info.arrays[40] = DwarfArray(40, 30, (2,), 8)
    info.variables = {'packets': DwarfVariable('packets', 50, 40, 0x20000020, 8, 'Packed[]')}
    catalog = catalog_for(tmp_path, info, limit=1)
    d = catalog.read_descriptor('packets[1].delta')
    assert (d.address, d.size, d.bit_offset, d.bit_size) == (0x20000025, 3, 3, 17)
    runtime = SuperWatchRuntime(items=[], dwarf_info=info, symbol_catalog=catalog)
    assert 'error' not in runtime.add(d.path)
    decoder = compile_frame_decoder(runtime.items, runtime.blocks)
    for value in (-65536, -1, 0, 1, 65535):
        payload = ((value & 0x1ffff) << 11).to_bytes(4, 'little')
        assert decode_descriptor(d, payload[1:]) == value
        assert decoder.decode(PackedWatchSample(0, payload, 0)) == [value]
    cache = DwarfCache(str(tmp_path/'cache'))
    cache.save(catalog.axf_path, info, backend='builtin', parser_version='test')
    restored = cache.load(catalog.axf_path, backend='builtin', parser_version='test')
    assert restored.records_by_offset[30].members == [field]
    field.data_bit_offset = 10
    changed = catalog_for(tmp_path, info, limit=1)
    assert rebind_paths(catalog, changed, ['packets[0].delta']).updated == ('packets[0].delta',)


@pytest.mark.parametrize('field', [
    DwarfMember('bad', size=1, bit_offset=7, bit_size=2),
    DwarfMember('bad', size=1, bit_size=1),
    DwarfMember('bad', size=1, data_bit_offset=24, bit_size=1),
    DwarfMember('bad', size=1, data_bit_offset=-1, bit_size=1),
    DwarfMember('bad', size=1, data_bit_offset=0, bit_size=0),
])
def test_invalid_bit_locations_are_not_exposed(field):
    assert bitfield_layout(field, 3) is None


def test_cache_and_big_endian_layout_do_not_reuse_legacy_bit_offsets(tmp_path):
    assert DwarfCache.CACHE_SCHEMA_VERSION > 5
    field = DwarfMember('flag', size=1, bit_offset=7, bit_size=1)
    assert bitfield_layout(field, 1, little_endian=False) is None


def test_reparse_removes_bitfield_moved_outside_ram(tmp_path):
    old = catalog_for(tmp_path, record_info())
    info = record_info()
    info.variables['state'] = replace(info.variables['state'], address=0x08000100)
    new = catalog_for(tmp_path, info)
    assert rebind_paths(old, new, ['state.mode']).removed == ('state.mode',)
    runtime = SuperWatchRuntime(items=[], dwarf_info=info, symbol_catalog=new)
    assert 'outside SRAM' in runtime.add('state.mode')['error']
    assert not runtime.items


@pytest.mark.parametrize('location', [
    'DW_AT_bit_offset : 12\n <42> DW_AT_byte_size : 2\n <43> DW_AT_data_member_location : 1',
    'DW_AT_data_bit_offset : 9',
])
def test_text_parser_normalizes_member_storage_and_record_bit_offsets(location):
    from mklink.dwarf_parser import parse_dwarf_info_output
    info = parse_dwarf_info_output('''
 <1><10>: Abbrev Number: 1 (DW_TAG_base_type)
 <11> DW_AT_name : unsigned int
 <12> DW_AT_byte_size : 4
 <13> DW_AT_encoding : 7
 <1><20>: Abbrev Number: 2 (DW_TAG_structure_type)
 <21> DW_AT_name : Packed
 <22> DW_AT_byte_size : 4
 <2><30>: Abbrev Number: 3 (DW_TAG_member)
 <31> DW_AT_name : mode
 <32> DW_AT_type : <0x10>
 <33> DW_AT_bit_size : 3
 <34> ''' + location)
    assert bitfield_layout(info.records_by_offset[0x20].members[0], 4) == (1, 1, 1)
