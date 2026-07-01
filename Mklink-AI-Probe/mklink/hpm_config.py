"""Shared HPMicro board configuration."""

from __future__ import annotations

HPM_BOARD_FLASH_CFG: dict[str, tuple[str, str, str, str]] = {
    "hpm5e00evk": ("0xfcf90002U", "0x00000005U", "0x00001000U", "0xf3000000U"),
    "hpm6e00evk": ("0xfcf90001U", "0x00000007U", "0x00000000U", "0xf3000000U"),
    "hpm6p00evk": ("0xfcf90002U", "0x00000005U", "0x00001000U", "0xf3000000U"),
    "hpm5300evk": ("0xfcf90002U", "0x00000005U", "0x00001000U", "0xf3000000U"),
    "hpm5301evklite": ("0xfcf90002U", "0x00000005U", "0x00001000U", "0xf3000000U"),
    "hpm6200evk": ("0xfcf90001U", "0x00000007U", "0x00000000U", "0xf3040000U"),
    "hpm6300evk": ("0xfcf90001U", "0x00000007U", "0x00000000U", "0xf3040000U"),
    "hpm6750evk2": ("0xfcf90002U", "0x00000007U", "0x0000000EU", "0xf3040000U"),
    "hpm6750evkmini": ("0xfcf90002U", "0x00000007U", "0x0000000EU", "0xf3040000U"),
    "hpm6800evk": ("0xfcf90001U", "0x00000007U", "0x00000000U", "0xf3000000U"),
}
