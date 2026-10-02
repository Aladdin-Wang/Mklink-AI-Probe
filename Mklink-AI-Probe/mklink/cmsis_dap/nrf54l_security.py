"""Pinned nRF54L15 CTRL-AP and UICR operations for online security jobs."""

from __future__ import annotations

import time
from typing import Any


CTRL_AP = 2 << 24
TARGET_ID = 0x001C0289
CTRL_AP_IDR = 0x32880000
PART_ID = 0x00054B15
APPROTECT_VALUE = 0x50FA50FA
APPROTECT_ADDRESSES = (0x00FFD000, 0x00FFD01C, 0x00FFD020, 0x00FFD03C)
ERASEPROTECT_ADDRESSES = (0x00FFD060, 0x00FFD07C)
FLASH_END = 0x0017D000


def _read(dp: Any, offset: int) -> int:
    return int(dp.read_ap(CTRL_AP | offset))


def _write(dp: Any, offset: int, value: int) -> None:
    dp.write_ap(CTRL_AP | offset, value)
    dp.flush()


def require_identity(dp: Any) -> None:
    if int(dp.read_dp(0x24)) & 0x0FFFFFFF != TARGET_ID:
        raise RuntimeError("nRF54L15 TARGETID mismatch; security operation stopped")
    if _read(dp, 0xFC) != CTRL_AP_IDR:
        raise RuntimeError("nRF54L15 CTRL-AP IDR mismatch; security operation stopped")


def require_erase_allowed(dp: Any) -> None:
    if _read(dp, 0x0C) != 0:
        raise RuntimeError("nRF54L15 ERASEPROTECT is active; no erase attempted")


def ctrl_ap_reset(dp: Any) -> None:
    _write(dp, 0x00, 2)
    _write(dp, 0x00, 0)
    time.sleep(0.2)


def recover(dp: Any) -> bool:
    """Trigger ERASEALL once, with no retry if the target reports an error."""

    require_identity(dp)
    require_erase_allowed(dp)
    protection = _read(dp, 0x14)
    if protection not in {0, 1, 2, 3}:
        raise RuntimeError("nRF54L15 protection state is invalid")
    if protection == 0:
        return False
    if _read(dp, 0x08) != 0:
        raise RuntimeError("nRF54L15 CTRL-AP erase engine is not idle")
    if int(dp.read_ap(0)) & 0x40:
        raise RuntimeError("nRF54L15 AHB remains accessible despite protection")
    _write(dp, 0x04, 1)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        status = _read(dp, 0x08)
        if status == 1:
            break
        if status == 3:
            raise RuntimeError("nRF54L15 CTRL-AP ERASEALL failed; no retry")
        time.sleep(0.05)
    else:
        raise TimeoutError("nRF54L15 CTRL-AP ERASEALL timed out; no retry")
    time.sleep(0.01)
    ctrl_ap_reset(dp)
    if _read(dp, 0x14) != 0 or _read(dp, 0x0C) != 0:
        raise RuntimeError("nRF54L15 protection remains active after recovery")
    return True


def verify_blank(target: Any) -> None:
    if int(target.read32(0x00FFC31C)) != PART_ID:
        raise RuntimeError("nRF54L15 PARTID mismatch after recovery")
    for address in range(0, FLASH_END, 4096):
        if bytes(target.read_memory_block8(address, 4096)) != b"\xFF" * 4096:
            raise RuntimeError(f"nRF54L15 recovery blank check failed at 0x{address:08X}")
    if any(int(target.read32(address)) != 0xFFFFFFFF for address in
           (*APPROTECT_ADDRESSES, *ERASEPROTECT_ADDRESSES)):
        raise RuntimeError("nRF54L15 UICR was not erased by recovery")


def write_approtect(target: Any) -> bool:
    dp = target.dp
    require_identity(dp)
    require_erase_allowed(dp)
    if _read(dp, 0x14) != 0:
        raise RuntimeError("nRF54L15 is already protected; lock requires readable verification")
    if int(target.read32(0x00FFC31C)) != PART_ID:
        raise RuntimeError("nRF54L15 PARTID mismatch; no UICR write attempted")
    values = tuple(int(target.read32(address)) for address in APPROTECT_ADDRESSES)
    if any(int(target.read32(address)) != 0xFFFFFFFF for address in ERASEPROTECT_ADDRESSES):
        raise RuntimeError("nRF54L15 ERASEPROTECT UICR is not blank")
    if values == (APPROTECT_VALUE,) * len(APPROTECT_ADDRESSES):
        return False
    if values != (0xFFFFFFFF,) * len(APPROTECT_ADDRESSES):
        raise RuntimeError("nRF54L15 APPROTECT UICR has unexpected values")
    target.reset_and_halt()
    flash = target.memory_map.get_region_for_address(APPROTECT_ADDRESSES[0]).flash
    flash.init(flash.Operation.PROGRAM, reset=False)
    try:
        for address in APPROTECT_ADDRESSES:
            flash.program_page(address, APPROTECT_VALUE.to_bytes(4, "little"))
    finally:
        flash.cleanup()
    if any(int(target.read32(address)) != APPROTECT_VALUE for address in APPROTECT_ADDRESSES):
        raise RuntimeError("nRF54L15 APPROTECT UICR write verification failed")
    if any(int(target.read32(address)) != 0xFFFFFFFF for address in ERASEPROTECT_ADDRESSES):
        raise RuntimeError("nRF54L15 ERASEPROTECT UICR changed unexpectedly")
    return True


def activate_and_verify_lock(dp: Any) -> None:
    require_identity(dp)
    ctrl_ap_reset(dp)
    if _read(dp, 0x14) != 3 or _read(dp, 0x0C) != 0 or int(dp.read_ap(0)) & 0x40:
        raise RuntimeError("nRF54L15 APPROTECT was not active after CTRL-AP reset")
