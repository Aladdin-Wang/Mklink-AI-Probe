from __future__ import annotations

import math
import struct

import pytest

from mklink.dwarf_parser import (
    DwarfEnum,
    DwarfInfo,
    DwarfMember,
    DwarfStruct,
    DwarfVariable,
)
from mklink.symbol_catalog import (
    SymbolCatalog,
    SymbolValueError,
    decode_descriptor,
    encode_descriptor,
    rebind_paths,
)


def _dwarf_fixture() -> DwarfInfo:
    info = DwarfInfo()
    info.base_types = {
        1: ("float", 4),
        2: ("int16_t", 2),
        3: ("uint32_t", 4),
        4: ("bool", 1),
    }
    info.typedefs = {10: ("gain_t", 1)}
    info.pointers = {20: (3, 4)}
    info.arrays = {21: (2, 16)}
    info.structs = {
        "Controller": DwarfStruct(
            name="Controller",
            offset=30,
            size=12,
            members=[
                DwarfMember("target", offset=0, type_offset=1, type_name="float", size=4),
                DwarfMember("enabled", offset=4, type_offset=4, type_name="bool", size=1),
                DwarfMember("samples", offset=6, type_offset=21, type_name="int16_t[]", size=16),
                DwarfMember("next", offset=8, type_offset=20, type_name="uint32_t*", size=4),
            ],
        )
    }
    info.enums = {
        "Mode": DwarfEnum("Mode", offset=40, size=4, values={0: "OFF", 1: "RUN"})
    }
    info.variables = {
        "gain": DwarfVariable("gain", 100, type_offset=10, address=0x20000010, size=4, type_name="gain_t"),
        "controller": DwarfVariable("controller", 101, type_offset=30, address=0x20000020, size=12, type_name="Controller"),
        "mode": DwarfVariable("mode", 102, type_offset=40, address=0x20000040, size=4, type_name="Mode"),
        "flash_constant": DwarfVariable("flash_constant", 103, type_offset=3, address=0x08001000, size=4, type_name="uint32_t"),
        "local_temp": DwarfVariable("local_temp", 104, type_offset=2, address=0x00000120, size=2, type_name="int16_t"),
        "unresolved": DwarfVariable("unresolved", 105, type_offset=3, address=None, size=4, type_name="uint32_t"),
        "buffer": DwarfVariable("buffer", 106, type_offset=21, address=0x20000060, size=16, type_name="int16_t[]"),
        "next": DwarfVariable("next", 107, type_offset=20, address=0x20000080, size=4, type_name="uint32_t*"),
    }
    return info


def test_catalog_keeps_ram_scalars_and_expands_struct_members(tmp_path):
    axf = tmp_path / "app.axf"
    axf.write_bytes(b"axf")

    catalog = SymbolCatalog.from_dwarf(
        _dwarf_fixture(),
        axf_path=str(axf),
        generation=3,
        ram_ranges=[(0x20000000, 0x20010000)],
    )

    assert [item.path for item in catalog.items] == [
        "controller.enabled",
        "controller.target",
        "gain",
        "mode",
    ]
    assert catalog.by_path("gain").type_name == "gain_t"
    assert catalog.by_path("gain").scalar_kind == "float"
    assert catalog.by_path("controller.target").address == 0x20000020
    assert catalog.by_path("controller.enabled").parent_path == "controller"
    assert catalog.by_path("mode").enum_values == {"OFF": 0, "RUN": 1}
    assert catalog.generation == 3


def test_catalog_rejects_flash_locals_unresolved_arrays_and_pointers(tmp_path):
    axf = tmp_path / "app.axf"
    axf.write_bytes(b"axf")
    catalog = SymbolCatalog.from_dwarf(
        _dwarf_fixture(),
        axf_path=str(axf),
        ram_ranges=[(0x20000000, 0x20010000)],
    )

    for path in ("flash_constant", "local_temp", "unresolved", "buffer", "next"):
        assert catalog.by_path(path) is None
    assert catalog.by_path("controller.samples") is None
    assert catalog.by_path("controller.next") is None


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        ("gain", 1.5, struct.pack("<f", 1.5)),
        ("controller.enabled", True, b"\x01"),
        ("mode", "RUN", b"\x01\x00\x00\x00"),
    ],
)
def test_descriptor_encoding_and_decoding_is_little_endian(tmp_path, path, value, expected):
    axf = tmp_path / "app.axf"
    axf.write_bytes(b"axf")
    catalog = SymbolCatalog.from_dwarf(
        _dwarf_fixture(), axf_path=str(axf), ram_ranges=[(0x20000000, 0x20010000)]
    )
    descriptor = catalog.require(path, catalog.generation)

    encoded = encode_descriptor(descriptor, value)

    assert encoded == expected
    decoded = decode_descriptor(descriptor, encoded)
    if isinstance(value, float):
        assert decoded == pytest.approx(value)
    elif path == "mode":
        assert decoded == 1
    else:
        assert decoded is value


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_float_encoding_rejects_non_finite_values(tmp_path, value):
    axf = tmp_path / "app.axf"
    axf.write_bytes(b"axf")
    descriptor = SymbolCatalog.from_dwarf(
        _dwarf_fixture(), axf_path=str(axf), ram_ranges=[(0x20000000, 0x20010000)]
    ).by_path("gain")

    with pytest.raises(SymbolValueError, match="finite"):
        encode_descriptor(descriptor, value)


def test_enum_encoding_rejects_unknown_name(tmp_path):
    axf = tmp_path / "app.axf"
    axf.write_bytes(b"axf")
    descriptor = SymbolCatalog.from_dwarf(
        _dwarf_fixture(), axf_path=str(axf), ram_ranges=[(0x20000000, 0x20010000)]
    ).by_path("mode")

    with pytest.raises(SymbolValueError, match="enum"):
        encode_descriptor(descriptor, "INVALID")


def test_rebind_paths_reports_preserved_updated_and_removed(tmp_path):
    first_axf = tmp_path / "first.axf"
    second_axf = tmp_path / "second.axf"
    first_axf.write_bytes(b"first")
    second_axf.write_bytes(b"second")
    old = SymbolCatalog.from_dwarf(
        _dwarf_fixture(), axf_path=str(first_axf), generation=1, ram_ranges=[(0x20000000, 0x20010000)]
    )
    new_info = _dwarf_fixture()
    new_info.variables["gain"].address = 0x20000100
    del new_info.variables["mode"]
    new = SymbolCatalog.from_dwarf(
        new_info, axf_path=str(second_axf), generation=2, ram_ranges=[(0x20000000, 0x20010000)]
    )

    summary = rebind_paths(old, new, ["gain", "controller.target", "mode"])

    assert summary.preserved == ("controller.target",)
    assert summary.updated == ("gain",)
    assert summary.removed == ("mode",)
