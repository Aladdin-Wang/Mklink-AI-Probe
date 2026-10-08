"""Address scan orchestration shared by local and runtime clients."""
from __future__ import annotations

from typing import Callable


def validate_scan_range(start_addr: int, end_addr: int, probe_register: int = 0) -> None:
    from mklink.modbus._session import validate_slave, validate_transaction
    validate_slave(start_addr)
    validate_slave(end_addr)
    validate_transaction(3, probe_register, quantity=1)
    if end_addr < start_addr:
        raise ValueError('Scan end address must be greater than or equal to start')


def scan_slaves(
    probe: Callable[[int, int], dict],
    start_addr: int = 1,
    end_addr: int = 247,
    probe_register: int = 0,
    on_progress: Callable[[int, int, str | None], None] | None = None,
) -> list[int]:
    """Probe each address once; the transport owns serialization and timing.

    A valid exception response proves presence. Transport/session failures abort
    the scan rather than being silently converted into absent devices.
    """
    validate_scan_range(start_addr, end_addr, probe_register)
    found: list[int] = []
    total = end_addr - start_addr + 1
    for i, addr in enumerate(range(start_addr, end_addr + 1)):
        result = probe(addr, probe_register)
        msg = None
        if result['responded']:
            found.append(addr)
            msg = f"[OK] 从站 {addr} 响应"
            if result.get('exception_code') is not None:
                msg = f"[OK] 从站 {addr} 存在（返回异常码 {result['exception_code']}）"
        if on_progress:
            on_progress(i + 1, total, msg)
    return found
