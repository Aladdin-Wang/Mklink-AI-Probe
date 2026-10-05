from unittest.mock import Mock

import pytest

from mklink import debug_control as debug


@pytest.fixture
def registers(monkeypatch):
    values = {debug.FP_CTRL: 6 << 4}
    # Comparator count is read-only; writing KEY/ENABLE cannot erase it.
    read = Mock(side_effect=lambda _, addr: ((6 << 4) | (values[addr] & 1))
                if addr == debug.FP_CTRL else values.get(addr, 0))
    write = Mock(side_effect=lambda _, addr, value: values.__setitem__(addr, value))
    monkeypatch.setattr(debug, '_read_u32', read)
    monkeypatch.setattr(debug, '_write_u32', write)
    return values, read, write


@pytest.mark.parametrize('address', [-1, 0x20000000, 0x100000000, True, '0x08005000', 1.5])
def test_invalid_address_never_accesses_registers(registers, address):
    _, read, write = registers
    with pytest.raises(ValueError):
        debug.set_breakpoint(None, address)
    read.assert_not_called()
    write.assert_not_called()


@pytest.mark.parametrize('slot', [-1, True, 1.5, '0'])
@pytest.mark.parametrize('operation', ['set', 'clear'])
def test_invalid_slot_never_accesses_registers(registers, slot, operation):
    _, read, write = registers
    with pytest.raises(ValueError):
        if operation == 'set':
            debug.set_breakpoint(None, 0x08005000, slot)
        else:
            debug.clear_breakpoint(None, slot)
    read.assert_not_called()
    write.assert_not_called()


@pytest.mark.parametrize('operation', ['set', 'clear'])
def test_out_of_range_slot_does_not_enable_or_write_fpb(registers, operation):
    _, _, write = registers
    with pytest.raises(ValueError):
        if operation == 'set':
            debug.set_breakpoint(None, 0x08005000, 6)
        else:
            debug.clear_breakpoint(None, 6)
    write.assert_not_called()


def test_exhausted_comparators_do_not_enable_fpb(registers):
    values, _, write = registers
    values.update({debug.FP_COMP_BASE + i * 4: 1 for i in range(6)})
    with pytest.raises(ValueError, match='All 6'):
        debug.set_breakpoint(None, 0x08005000)
    write.assert_not_called()


@pytest.mark.parametrize('address,expected', [(0x08005000, 0x48005001), (0x08005002, 0x88005001)])
def test_valid_last_slot_and_halfword_encoding(registers, address, expected):
    values, _, _ = registers
    assert debug.set_breakpoint(None, address, 5) == 5
    assert values[debug.FP_COMP_BASE + 20] == expected
    assert values[debug.FP_CTRL] == debug.FP_CTRL_KEY | debug.FP_CTRL_ENABLE
    debug.clear_breakpoint(None, 5)
    assert values[debug.FP_COMP_BASE + 20] == 0
