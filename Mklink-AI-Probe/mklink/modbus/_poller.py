"""寄存器轮询 — ANSI 实时表格显示。"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

from mklink.modbus._format import RegisterSpec, format_value
from mklink.modbus._registers import read_register_values, validate_register_specs, validate_poll_interval


def validate_poll(specs: list[RegisterSpec], interval: float, count: int | None) -> None:
    validate_register_specs(specs)
    if not specs:
        raise ValueError('Select at least one poll register')
    validate_poll_interval(interval)
    if count is not None and (type(count) is not int or count < 1):
        raise ValueError('Poll count must be a positive integer or omitted')


def _move_up(n: int) -> str:
    """ANSI 转义：光标上移 n 行。"""
    return f"\033[{n}A"


def poll_registers(
    read: Callable[[int, int, int], list[int]],
    slave: int,
    specs: list[RegisterSpec],
    interval: float = 1.0,
    fmt: str = "dec",
    count: int | None = None,
) -> None:
    """轮询寄存器并显示实时 ANSI 表格。

    Args:
        read: 单次读取回调 (fc, address, quantity)，由传输层串行化
        slave: 从站地址
        specs: 寄存器规格列表
        interval: 轮询间隔（秒）
        fmt: 显示格式 (dec/hex/bin/float)
        count: 轮询次数，None 为无限
    """
    validate_poll(specs, interval, count)

    # 计算每个 spec 的显示宽度
    name_col = max((len(s.name or f"REG_{s.addr}") for s in specs), default=10)
    type_col = max((len(s.type) for s in specs), default=6)

    # 打印表头
    header = (
        f"{'Address':>8}  "
        f"{'Type':<{type_col}}  "
        f"{'Name':<{name_col}}  "
        f"{'Value':<16}"
    )
    separator = "-" * len(header)

    print(f"从站: {slave}  |  间隔: {interval}s  |  按 Ctrl+C 停止")
    print(separator)
    print(header)
    print(separator)

    poll_count = 0
    table_lines = len(specs) + 2  # separator + value rows + footer
    first = True

    try:
        while count is None or poll_count < count:
            values_map = read_register_values(read, specs)

            # 清除旧表格行
            if not first:
                sys.stdout.write(_move_up(table_lines))
            first = False

            print(separator)
            for spec in specs:
                val = values_map[spec.addr]
                bit_width = 32 if spec.type in ("uint32", "int32") else 16
                display = format_value(val, fmt, bit_width)
                label = spec.name or f"REG_{spec.addr}"
                print(
                    f"{spec.addr:>8}  "
                    f"{spec.type:<{type_col}}  "
                    f"{label:<{name_col}}  "
                    f"{display:<16}"
                )
            print(f"{separator}  轮询: {poll_count + 1}")

            sys.stdout.flush()
            poll_count += 1

            if count is not None and poll_count >= count:
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n[*] 轮询已停止，共 {poll_count} 次")
