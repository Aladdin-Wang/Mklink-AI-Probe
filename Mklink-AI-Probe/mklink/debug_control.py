"""Cortex-M CPU debug control via SWD memory-mapped registers.

Provides halt, resume, and FPB hardware breakpoint operations
using the existing write-ram / read-ram bridge commands.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field

from mklink.bridge import MKLinkSerialBridge
from mklink.memory_access import parse_read_ram_response


# --- Cortex-M Debug Registers (PPB) ---
DHCSR = 0xE000EDF0  # Debug Halting Control and Status Register
DHCSR_KEY = 0xA05F0000
DHCSR_C_DEBUGEN = 1 << 0
DHCSR_C_HALT = 1 << 1
DHCSR_C_STEP = 1 << 2
DHCSR_S_REGRDY = 1 << 16  # Register read/write transfer complete
DHCSR_S_HALT = 1 << 17
DHCSR_S_LOCKUP = 1 << 19

# --- FPB (Flash Patch and Breakpoint) ---
FP_CTRL = 0xE0002000
FP_COMP_BASE = 0xE0002008  # FP_COMP0, stride 4 bytes
FP_CTRL_ENABLE = 1 << 0
FP_CTRL_KEY = 1 << 1

# FPB revision detection
FP_REMAP = 0xE0002004


@dataclass
class BreakpointSlot:
    index: int
    address: int
    enabled: bool = True


@dataclass
class DebugState:
    halted: bool = False
    lockup: bool = False
    dhcsr_raw: int = 0
    num_breakpoints: int = 0
    breakpoints: list[BreakpointSlot] = field(default_factory=list)


def _read_u32(bridge: MKLinkSerialBridge, addr: int) -> int:
    resp = bridge.send_command(f"cmd.read_ram(0x{addr:08X}, 4)", timeout=5.0)
    data = parse_read_ram_response(resp)
    if len(data) < 4:
        raise RuntimeError(f"read_ram(0x{addr:08X}) returned {len(data)} bytes, expected 4")
    return struct.unpack("<I", data[:4])[0]


def _write_u32(bridge: MKLinkSerialBridge, addr: int, value: int) -> None:
    b = struct.pack("<I", value)
    cmd = f"cmd.write_ram(0x{addr:08X}, 0x{b[0]:02X}, 0x{b[1]:02X}, 0x{b[2]:02X}, 0x{b[3]:02X})"
    bridge.send_command(cmd, timeout=5.0)


def _wait_regrdy(bridge: MKLinkSerialBridge, timeout: float = 0.5) -> None:
    """Poll DHCSR.S_REGRDY until the DCRSR→DCRDR register transfer completes.

    Mandatory step 2 of the Cortex-M core-register read/write sequence: after
    writing DCRSR, the core copies the register into DCRDR asynchronously and
    raises S_REGRDY (bit 16) only when DCRDR holds a valid value. Skipping this
    poll races the transfer and yields stale/residual DCRDR values when reading
    multiple registers back-to-back.
    """
    deadline = time.monotonic() + timeout
    while True:
        if _read_u32(bridge, DHCSR) & DHCSR_S_REGRDY:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("DHCSR.S_REGRDY never asserted after DCRSR write")


def read_debug_state(bridge: MKLinkSerialBridge) -> DebugState:
    """Read current CPU debug state."""
    dhcsr = _read_u32(bridge, DHCSR)
    state = DebugState(
        halted=bool(dhcsr & DHCSR_S_HALT),
        lockup=bool(dhcsr & DHCSR_S_LOCKUP),
        dhcsr_raw=dhcsr,
    )

    # Read FP_CTRL to get number of comparators
    fp_ctrl = _read_u32(bridge, FP_CTRL)
    state.num_breakpoints = (fp_ctrl >> 4) & 0x0F  # NUM_CODE field [7:4]

    # Read each comparator
    for i in range(state.num_breakpoints):
        comp_addr = FP_COMP_BASE + i * 4
        comp_val = _read_u32(bridge, comp_addr)
        if comp_val & 0x01:  # ENABLE bit
            # FPBv1: address in bits [28:2], REPLACE in [31:30]
            # FPBv2: address in bits [31:1]
            bp_addr = comp_val & 0x1FFFFFFC
            state.breakpoints.append(BreakpointSlot(index=i, address=bp_addr, enabled=True))

    return state


def halt_cpu(bridge: MKLinkSerialBridge) -> DebugState:
    """Halt the CPU via DHCSR."""
    _write_u32(bridge, DHCSR, DHCSR_KEY | DHCSR_C_DEBUGEN | DHCSR_C_HALT)
    return read_debug_state(bridge)


def resume_cpu(bridge: MKLinkSerialBridge) -> DebugState:
    """Resume CPU execution. If halted at a breakpoint, step past it first."""
    state = read_debug_state(bridge)
    if state.halted and state.breakpoints:
        # Step past the breakpoint instruction before resuming
        _write_u32(bridge, DHCSR, DHCSR_KEY | DHCSR_C_DEBUGEN | DHCSR_C_HALT | DHCSR_C_STEP)
        import time
        time.sleep(0.001)
    _write_u32(bridge, DHCSR, DHCSR_KEY | DHCSR_C_DEBUGEN)
    return read_debug_state(bridge)


def step_cpu(bridge: MKLinkSerialBridge) -> DebugState:
    """Single-step the CPU (execute one instruction)."""
    _write_u32(bridge, DHCSR, DHCSR_KEY | DHCSR_C_DEBUGEN | DHCSR_C_HALT | DHCSR_C_STEP)
    return read_debug_state(bridge)


def get_num_breakpoints(bridge: MKLinkSerialBridge) -> int:
    """Get the number of FPB hardware breakpoint comparators available."""
    fp_ctrl = _read_u32(bridge, FP_CTRL)
    return (fp_ctrl >> 4) & 0x0F


def set_breakpoint(bridge: MKLinkSerialBridge, address: int, slot: int | None = None) -> int:
    """Set a hardware breakpoint at the given Flash address.

    Args:
        bridge: Connected MKLink bridge
        address: Flash address (must be in code region, < 0x20000000)
        slot: Specific comparator slot (0-5), or None for auto-assign

    Returns:
        The slot index used

    Raises:
        ValueError: If address is not in Flash or no free slot available
    """
    if address >= 0x20000000:
        raise ValueError(f"FPB breakpoints only work in Flash region (< 0x20000000), got 0x{address:08X}")

    num_comp = get_num_breakpoints(bridge)
    if num_comp == 0:
        raise RuntimeError("FPB reports 0 comparators — hardware may not support breakpoints")

    # Enable FPB unit if not already
    fp_ctrl = _read_u32(bridge, FP_CTRL)
    if not (fp_ctrl & FP_CTRL_ENABLE):
        _write_u32(bridge, FP_CTRL, FP_CTRL_KEY | FP_CTRL_ENABLE)

    if slot is not None:
        if slot >= num_comp:
            raise ValueError(f"Slot {slot} out of range (max {num_comp - 1})")
    else:
        # Find first free slot
        for i in range(num_comp):
            comp_val = _read_u32(bridge, FP_COMP_BASE + i * 4)
            if not (comp_val & 0x01):
                slot = i
                break
        if slot is None:
            raise ValueError(f"All {num_comp} breakpoint slots are in use")

    # FPBv1 encoding: address[28:2] | REPLACE[31:30] | ENABLE[0]
    # For Thumb instructions: if bit[1] of address is 0 → REPLACE=01 (lower halfword)
    #                         if bit[1] of address is 1 → REPLACE=10 (upper halfword)
    addr_aligned = address & 0x1FFFFFFC
    if address & 0x02:
        replace = 0x80000000  # REPLACE = 10 → upper halfword
    else:
        replace = 0x40000000  # REPLACE = 01 → lower halfword

    comp_val = replace | addr_aligned | 0x01  # ENABLE
    _write_u32(bridge, FP_COMP_BASE + slot * 4, comp_val)

    return slot


def clear_breakpoint(bridge: MKLinkSerialBridge, slot: int) -> None:
    """Clear a specific breakpoint slot."""
    _write_u32(bridge, FP_COMP_BASE + slot * 4, 0x00000000)


def clear_all_breakpoints(bridge: MKLinkSerialBridge) -> int:
    """Clear all breakpoint slots. Returns number cleared."""
    num_comp = get_num_breakpoints(bridge)
    cleared = 0
    for i in range(num_comp):
        comp_val = _read_u32(bridge, FP_COMP_BASE + i * 4)
        if comp_val & 0x01:
            _write_u32(bridge, FP_COMP_BASE + i * 4, 0x00000000)
            cleared += 1
    return cleared


def list_breakpoints(bridge: MKLinkSerialBridge) -> list[BreakpointSlot]:
    """List all active breakpoints."""
    state = read_debug_state(bridge)
    return state.breakpoints


def resolve_function_address(
    source: str,
    name: str,
    *,
    backend: str | None = None,
    project_root: str | None = None,
) -> int | None:
    """Resolve a function name to its linked Flash address.

    Args:
        source: Path to ELF/AXF file
        name: Function name to look up

    Returns:
        Address of the function, or None if not found
    """
    from mklink.elf_backend import resolve_function_symbol

    return resolve_function_symbol(
        source,
        name,
        backend=backend,
        project_root=project_root,
    )


def search_functions(
    source: str,
    pattern: str,
    max_results: int = 20,
    *,
    backend: str | None = None,
    project_root: str | None = None,
) -> list[dict]:
    """Search for function symbols matching a pattern.

    Returns list of dicts with keys: name, address, size
    """
    from mklink.elf_backend import search_function_symbols

    return search_function_symbols(
        source,
        pattern,
        max_results=max_results,
        backend=backend,
        project_root=project_root,
    )


# --- Core Register Access (via DCRSR/DCRDR, requires CPU halted) ---
DCRSR = 0xE000EDF4  # Debug Core Register Selector Register
DCRDR = 0xE000EDF8  # Debug Core Register Data Register

# DCRSR.REGSEL selectors that return a single 32-bit register.
# Universal across all Cortex-M profiles (v6-M / v7-M / v8-M).
DIRECT_CORE_REGS = {
    "r0": 0, "r1": 1, "r2": 2, "r3": 3,
    "r4": 4, "r5": 5, "r6": 6, "r7": 7,
    "r8": 8, "r9": 9, "r10": 10, "r11": 11,
    "r12": 12, "sp": 13, "lr": 14, "pc": 15,
    "xpsr": 16, "msp": 17, "psp": 18,
}

# CONTROL / FAULTMASK / BASEPRI / PRIMASK share a SINGLE DCRSR selector (0x14)
# and come back packed as the CFBP word:
#   bits [31:24]=CONTROL  [23:16]=FAULTMASK  [15:8]=BASEPRI  [7:0]=PRIMASK
# (ARMv7-M ARM DDI 0403 §C1.6.3; cross-checked vs pyOCD cortex_m_core_registers.py).
# FAULTMASK/BASEPRI read 0 on v6-M (they don't exist there).
CFBP_SELECTOR = 0x14
CFBP_CORE_REGS = {
    "control":   3,  # bits 31:24
    "faultmask": 2,  # bits 23:16
    "basepri":   1,  # bits 15:8
    "primask":   0,  # bits 7:0
}

# Backward-compatible name → selector map (direct registers only).
CORE_REGS = dict(DIRECT_CORE_REGS)


def _read_core_reg_selector(bridge: MKLinkSerialBridge, selector: int) -> int:
    """Read one DCRSR selector into DCRDR (REGWnR=0 read). Requires CPU halted."""
    _write_u32(bridge, DCRSR, selector)
    _wait_regrdy(bridge)
    return _read_u32(bridge, DCRDR)


def read_core_register(bridge: MKLinkSerialBridge, reg: str | int) -> int:
    """Read a CPU core register (requires CPU halted).

    Args:
        bridge: Connected MKLink bridge.
        reg: Register name, or a raw DCRSR selector int.
            Names: r0-r12, sp, lr, pc, xpsr, msp, psp, control, primask,
            basepri, faultmask. The control/mask names are decoded from the
            packed CFBP word (selector 0x14), so ``control`` returns the real
            CONTROL byte, not the whole CFBP word.
            Raw int: any DCRSR REGSEL, e.g. 0x21=FPSCR, 0x40+n=S{n} on FPU
            cores — lets callers read platform-specific registers (FPU /
            security banks) without changing this library.

    Returns:
        32-bit register value (byte-wide, 0-255, for the CFBP mask registers).
    """
    if isinstance(reg, str):
        key = reg.lower()
        if key in DIRECT_CORE_REGS:
            return _read_core_reg_selector(bridge, DIRECT_CORE_REGS[key])
        if key in CFBP_CORE_REGS:
            cfbp = _read_core_reg_selector(bridge, CFBP_SELECTOR)
            return (cfbp >> (8 * CFBP_CORE_REGS[key])) & 0xFF
        valid = ", ".join(list(DIRECT_CORE_REGS) + list(CFBP_CORE_REGS))
        raise ValueError(f"Unknown register '{reg}'. Valid: {valid}")

    # Raw selector passthrough (deliberately no 0x1F mask: FPU regs use 0x21/0x40+).
    return _read_core_reg_selector(bridge, int(reg))


def read_all_core_registers(bridge: MKLinkSerialBridge) -> dict[str, int]:
    """Read the universal Cortex-M core register set.

    Returns name→value for r0-r12, sp, lr, pc, xpsr, msp, psp, control,
    primask, basepri, faultmask. CFBP is read once and unpacked into the four
    mask registers.

    Platform-specific extensions (FPU S0-S31 / FPSCR on M4F/M7, security banks
    on v8-M) are intentionally NOT included — read those via
    ``read_core_register(<raw selector>)`` from the Skill layer when the target
    actually has them.
    """
    regs = {name: _read_core_reg_selector(bridge, sel)
            for name, sel in DIRECT_CORE_REGS.items()}
    cfbp = _read_core_reg_selector(bridge, CFBP_SELECTOR)
    for name, byte in CFBP_CORE_REGS.items():
        regs[name] = (cfbp >> (8 * byte)) & 0xFF
    return regs
