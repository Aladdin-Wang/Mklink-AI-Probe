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
    # High-speed kernels require a supported debug interface and an exact
    # firmware acknowledgement. This shared ID identifies neither the exact
    # HPM part nor the electrical qualification of the connected board.
    hpm = bridge.idcode == 0x1000563D
    # New SWD firmware exposes the same four profiles. Require its exact
    # acknowledgement below; old firmware must never be labelled 20/30 MHz.
    response = bridge.send_command(f"cmd.set_swd_clock({hz})")
    confirmed = False
    interface = "JTAG" if hpm else "SWD"
    # Deferred connects set the clock before reading the target IDCODE.
    # An exact firmware reply can identify the selected transport in that case.
    if not bridge.idcode and re.search(rf"(?m)^JTAG profile={hz}\s*$", response):
        interface = "JTAG"
    match = re.search(rf"{interface} profile=(\d+)\b", response)
    confirmed = bool(match and int(match.group(1)) == hz)
    legacy = match is None and profile in ("low", "medium") and f"set clock {hz}" in response
    if not confirmed and not legacy:
        # The command completed but this firmware lacks the exact timing
        # kernel. Restore a conservative clock, never label fallback as high.
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
            "qualification": f"{interface} profile confirmed; exact target and board stability not identified by IDCODE" if confirmed else "legacy timing not hardware-qualified"}
