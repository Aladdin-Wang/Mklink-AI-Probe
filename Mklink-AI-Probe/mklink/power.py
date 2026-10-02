"""Read-only probe VCC telemetry; no target debug or power control commands."""

from __future__ import annotations

import json

from mklink._types import DeviceState


def parse_power_response(response: str) -> dict:
    records = [line.strip()[len("MKLINK_POWER "):]
               for line in response.splitlines()
               if line.strip().startswith("MKLINK_POWER ")]
    if not records:
        raise ValueError(
            "No VCC telemetry response. Firmware must support cmd.get_power(); "
            "upgrade the matching V3/V4 firmware. Missing data is not zero."
        )
    if len(records) != 1:
        raise ValueError("Ambiguous VCC telemetry response")
    try:
        data = json.loads(records[0])
    except (ValueError, TypeError) as exc:
        raise ValueError("Malformed VCC telemetry JSON") from exc
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
        raise ValueError("Unsupported VCC telemetry schema")
    if type(data.get("current_supported")) is not bool:
        raise ValueError("Missing VCC current capability")
    for key in ("voltage_mv", "current_ua", "power_uw", "sample_age_ms"):
        if key not in data:
            raise ValueError(f"Missing VCC telemetry field: {key}")
        value = data[key]
        if value is None and key != "sample_age_ms":
            continue
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"Invalid VCC telemetry field: {key}")
    voltage, current, power = (data[key] for key in ("voltage_mv", "current_ua", "power_uw"))
    if not data["current_supported"] and (current is not None or power is not None):
        raise ValueError("Unsupported current measurement must be null")
    if voltage is None or current is None:
        if power is not None:
            raise ValueError("Power requires valid voltage and current")
    elif power != (voltage * current + 500) // 1000:
        raise ValueError("Inconsistent VCC power calculation")
    if data["sample_age_ms"] > 1000:
        raise ValueError("Stale VCC telemetry sample (older than 1000 ms)")
    return {
        "voltage_mv": voltage,
        "current_ma": None if current is None else current / 1000.0,
        "power_mw": None if power is None else power / 1000.0,
        "current_supported": data["current_supported"],
        "sample_age_ms": data["sample_age_ms"],
    }


def read_power(bridge) -> dict:
    if bridge.state != DeviceState.READY:
        raise RuntimeError("VCC telemetry requires an idle command session; stop the active stream first")
    return parse_power_response(bridge.send_command("cmd.get_power()", timeout=5.0))
