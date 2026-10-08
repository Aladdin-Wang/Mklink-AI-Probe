"""
MKLink Serial Bridge — MCU 配置加载。

零外部依赖（仅 stdlib json/pathlib），零内部依赖。
mcu_profiles.json 位于本包同目录下。
"""

from __future__ import annotations

import json
from pathlib import Path


def load_mcu_profiles(profile_path: str | None = None) -> dict:
    """加载 MCU 配置文件。"""
    if profile_path is None:
        profile_path = str(Path(__file__).parent / "mcu_profiles.json")

    with open(profile_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("mcus", {})


def match_mcu_by_idcode(idcode: int, profiles: dict) -> str | None:
    """仅返回唯一 IDCODE 匹配；同调试端口 ID 的多个器件不能按顺序猜测。"""
    idcode_str = f"0x{idcode:08X}"
    matches = [key for key, profile in profiles.items()
               if (profile.get("idcode_pattern") or "").upper() == idcode_str.upper()]
    # A debug-port IDCODE may describe multiple targets; order is not identity.
    return matches[0] if len(matches) == 1 else None


def match_mcu_by_device(device_name: str, profiles: dict) -> str | None:
    """按唯一最长设备名称前缀匹配 MCU 配置；同等具体的候选视为歧义。

    例如 "N32G435CB" 匹配 device_prefix "N32G43" → 返回 "n32g435"。
    """
    if not device_name:
        return None
    upper = device_name.upper()
    matches = []
    for key, profile in profiles.items():
        prefix = profile.get("device_prefix", "")
        if prefix and upper.startswith(prefix.upper()):
            matches.append((len(prefix), key))
    if not matches:
        return None
    longest = max(length for length, _ in matches)
    exact = [key for length, key in matches if length == longest]
    return exact[0] if len(exact) == 1 else None
