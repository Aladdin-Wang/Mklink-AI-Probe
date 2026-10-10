"""Named debug clock profiles shared by SDK, CLI, MCP and Web."""
from __future__ import annotations

PROFILES = {"low": 4_000_000, "medium": 10_000_000, "high": 20_000_000, "ultra": 30_000_000}


class ClockProfileUnavailable(ValueError):
    """Requested kernel is unavailable, but 1 MHz was explicitly acknowledged."""


def validate_clock_hz(hz: int) -> int:
    """Keep legacy clocks up to 10 MHz and the two calibrated high kernels."""
    if type(hz) is not int or not (1 <= hz <= 10_000_000 or hz in (20_000_000, 30_000_000)):
        raise ValueError("clock must be an integer from 1 Hz to 10 MHz, or exactly 20 MHz / 30 MHz")
    return hz


def profile_clock(profile: str) -> int:
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ValueError("debug speed must be low (4 MHz), medium (10 MHz), high (20 MHz), or ultra (30 MHz)")
    return PROFILES[profile]


def apply_profile(device, profile: str) -> dict:
    device._require_connected()
    return apply_bridge_profile(device._bridge, profile)


def apply_bridge_profile(bridge, profile: str) -> dict:
    from mklink._types import DeviceState
    import re

    hz = profile_clock(profile)
    if bridge.state != DeviceState.READY:
        raise ValueError("Stop the active stream before changing debug speed")
    # Clock configuration belongs to the probe, not the attached MCU. V3 may
    # omit the optional profile line while its target scanner has no IDCODE.
    # Accept its exact setting acknowledgement for every supported clock;
    # retain profile_confirmed separately from the accepted setting.
    bridge._ctx.swd_clock_hz = 0
    response = bridge.send_command(f"cmd.set_swd_clock({hz})")
    lines = response.splitlines() if isinstance(response, str) else []
    match = re.search(r"(?m)^(SWD|JTAG) profile=(\d+)\b", response if isinstance(response, str) else "")
    interface = match.group(1) if match else "unknown"
    rejected = any(line.strip() == '-1' or line.strip().lower().startswith('error') for line in lines)
    confirmed = bool(match and int(match.group(2)) == hz and not rejected)
    accepted = match is None and not rejected and any(line.strip() == f"set clock {hz}" for line in lines)
    if not confirmed and not accepted:
        # An explicit mismatch/rejection or missing setting ACK is still a
        # failure. Never treat the command echo or diagnostic counters as ACK.
        fallback = bridge.send_command("cmd.set_swd_clock(1000000)")
        if not isinstance(fallback, str) or not any(
            line.strip() == "set clock 1000000" for line in fallback.splitlines()
        ):
            bridge._ctx.swd_clock_hz = 0
            raise ValueError(f"Probe firmware did not confirm {interface} profile or fallback clock")
        bridge._ctx.swd_clock_hz = 1_000_000
        raise ClockProfileUnavailable(f"Probe firmware does not confirm this {interface} profile; restored 1 MHz")
    bridge._ctx.swd_clock_hz = hz
    return {"profile": profile, "clock_hz": hz, "profile_confirmed": confirmed,
            "interface": interface,
            "qualification": f"{interface} profile confirmed; exact target and board stability not identified by IDCODE" if confirmed else "Probe accepted clock setting; target timing not verified"}
