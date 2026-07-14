from mklink.dwarf_parser import parse_dwarf_info_output


def test_variable_type_resolves_through_volatile_and_typedefs():
    output = """
 <1><10>: Abbrev Number: 1 (DW_TAG_base_type)
    <11>   DW_AT_byte_size   : 4
    <12>   DW_AT_name        : unsigned int
 <1><20>: Abbrev Number: 2 (DW_TAG_typedef)
    <21>   DW_AT_type        : <0x10>
    <22>   DW_AT_name        : uint32_t
 <1><30>: Abbrev Number: 2 (DW_TAG_typedef)
    <31>   DW_AT_type        : <0x20>
    <32>   DW_AT_name        : rt_uint32_t
 <1><40>: Abbrev Number: 3 (DW_TAG_volatile_type)
    <41>   DW_AT_type        : <0x30>
 <1><50>: Abbrev Number: 4 (DW_TAG_variable)
    <51>   DW_AT_name        : mklink_rtt_test_arm
    <52>   DW_AT_type        : <0x40>
    <53>   DW_AT_location    : 5 byte block: 3 1c b0 0 20 (DW_OP_addr: 2000b01c)
"""

    variable = parse_dwarf_info_output(output).variables["mklink_rtt_test_arm"]

    assert variable.type_name == "rt_uint32_t"
    assert variable.size == 4
    assert variable.address == 0x2000B01C
