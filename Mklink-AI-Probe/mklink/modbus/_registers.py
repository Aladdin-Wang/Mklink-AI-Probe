"""Register validation, bounded grouping and typed reads shared by all callers."""
from __future__ import annotations

from collections.abc import Callable
import math

from mklink.modbus._format import RegisterSpec, registers_to_values


def validate_register_specs(specs: list[RegisterSpec]) -> None:
    if not isinstance(specs, list) or len(specs) > 1024:
        raise ValueError('Select at most 1024 poll registers')
    for spec in specs:
        if not isinstance(spec, RegisterSpec) or type(spec.addr) is not int:
            raise ValueError('Each poll register requires an integer addr')
        if spec.type not in ('uint16', 'int16', 'uint32', 'int32', 'float'):
            raise ValueError('Unsupported poll register type')
        if spec.register_type not in ('holding', 'input'):
            raise ValueError('Register type must be holding or input')
        if not 0 <= spec.addr < 65536 or spec.addr + spec.reg_count > 65536:
            raise ValueError('Poll register range exceeds 0..65535')
    if len({spec.addr for spec in specs}) != len(specs):
        raise ValueError('Poll register addresses must be distinct')


def validate_poll_interval(interval: float) -> float:
    value = float(interval)
    if isinstance(interval, bool) or not math.isfinite(value) or not .02 <= value <= 3600:
        raise ValueError('Polling interval must be in the range 0.02..3600 seconds')
    return value


def group_registers(specs: list[RegisterSpec]) -> list[list[RegisterSpec]]:
    """Keep input order and whole values, at most 125 registers per request."""
    validate_register_specs(specs)
    groups: list[list[RegisterSpec]] = []
    for spec in specs:
        if (groups and spec.addr == groups[-1][-1].addr + groups[-1][-1].reg_count
                and spec.register_type == groups[-1][-1].register_type
                and spec.addr + spec.reg_count - groups[-1][0].addr <= 125):
            groups[-1].append(spec)
        else:
            groups.append([spec])
    return groups


def read_register_values(
    read: Callable[[int, int, int], list[int]], specs: list[RegisterSpec],
) -> dict[int, int | float]:
    """Read complete groups before publishing values; transport owns I/O locking."""
    result: dict[int, int | float] = {}
    for group in group_registers(specs):
        start = group[0].addr
        count = group[-1].addr + group[-1].reg_count - start
        registers = read(4 if group[0].register_type == 'input' else 3, start, count)
        if len(registers) != count:
            raise OSError('Modbus read returned an incomplete register group')
        for spec in group:
            offset = spec.addr - start
            result[spec.addr] = registers_to_values(registers[offset:offset + spec.reg_count], spec.type)[0]
    return result
