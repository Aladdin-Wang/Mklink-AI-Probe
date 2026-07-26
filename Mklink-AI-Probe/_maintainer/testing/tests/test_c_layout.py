from __future__ import annotations

import pytest

from mklink.c_layout import CLayoutError, parse_c_layout


DATA_SAVE_DEFINITION = """
typedef struct {
    union {
        uint64_t odo;
        struct {
            float mileage_odo;
            uint32_t zero1;
        };
    };
    uint16_t samples[2];
} DATASAVE_TYPEDEF;
"""


def test_parse_c_layout_expands_anonymous_union_and_arrays():
    layout = parse_c_layout(DATA_SAVE_DEFINITION, preferred_type="DATASAVE_TYPEDEF")

    assert layout.size == 16
    assert [(leaf.suffix, leaf.offset) for leaf in layout.leaves] == [
        (".odo", 0),
        (".mileage_odo", 0),
        (".zero1", 4),
        (".samples[0]", 8),
        (".samples[1]", 10),
    ]
    assert [leaf.overlapping for leaf in layout.leaves] == [True, True, True, False, False]


def test_parse_c_layout_honors_explicit_and_pragma_pack():
    source = "typedef struct { uint8_t flag; uint32_t value; } Packed;"

    assert parse_c_layout(source, preferred_type="Packed").size == 8
    explicit = parse_c_layout(source, preferred_type="Packed", pack=1)
    pragma = parse_c_layout("#pragma pack(push, 1)\n" + source)
    assert explicit.size == pragma.size == 5
    assert explicit.leaves[1].offset == pragma.leaves[1].offset == 1


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("typedef struct { uint32_t *next; } Bad;", "pointer"),
        ("typedef struct { uint32_t bits:3; } Bad;", "bit-field"),
        ("typedef struct { uint32_t values[600]; } Bad;", "512"),
        ("not a definition", "parse failed"),
    ],
)
def test_parse_c_layout_rejects_unsafe_or_invalid_definitions(source, message):
    with pytest.raises(CLayoutError, match=message):
        parse_c_layout(source)
