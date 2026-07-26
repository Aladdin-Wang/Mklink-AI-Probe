"""Cortex-M HardFault register and stack-frame decoding."""

from __future__ import annotations

import struct
from typing import Any, Iterable


FAULT_REGISTERS = ["SCB.CFSR", "SCB.HFSR", "SCB.MMFAR", "SCB.BFAR", "SCB.AFSR"]


CFSR_FLAGS = [
    (0, "IACCVIOL", "MemManage: instruction access violation"),
    (1, "DACCVIOL", "MemManage: data access violation"),
    (3, "MUNSTKERR", "MemManage: unstacking error"),
    (4, "MSTKERR", "MemManage: stacking error"),
    (5, "MLSPERR", "MemManage: lazy FP state preservation error"),
    (7, "MMARVALID", "MemManage fault address valid"),
    (8, "IBUSERR", "BusFault: instruction bus error"),
    (9, "PRECISERR", "BusFault: precise data bus error"),
    (10, "IMPRECISERR", "BusFault: imprecise data bus error"),
    (11, "UNSTKERR", "BusFault: unstacking error"),
    (12, "STKERR", "BusFault: stacking error"),
    (13, "LSPERR", "BusFault: lazy FP state preservation error"),
    (15, "BFARVALID", "BusFault address valid"),
    (16, "UNDEFINSTR", "UsageFault: undefined instruction"),
    (17, "INVSTATE", "UsageFault: invalid EPSR state"),
    (18, "INVPC", "UsageFault: invalid PC load"),
    (19, "NOCP", "UsageFault: no coprocessor"),
    (24, "UNALIGNED", "UsageFault: unaligned access"),
    (25, "DIVBYZERO", "UsageFault: divide by zero"),
]

HFSR_FLAGS = [
    (1, "VECTTBL", "Fault during vector table read"),
    (30, "FORCED", "Configurable fault escalated to HardFault"),
    (31, "DEBUGEVT", "Debug event"),
]


def decode_cfsr(value: int) -> list[str]:
    return [f"{name}: {desc}" for bit, name, desc in CFSR_FLAGS if value & (1 << bit)]


def decode_hfsr(value: int) -> list[str]:
    return [f"{name}: {desc}" for bit, name, desc in HFSR_FLAGS if value & (1 << bit)]


def parse_exception_stack_frame(data: bytes) -> dict[str, int]:
    if len(data) < 32:
        raise ValueError("exception stack frame requires at least 32 bytes")
    names = ["r0", "r1", "r2", "r3", "r12", "lr", "pc", "xpsr"]
    values = struct.unpack("<8I", data[:32])
    return dict(zip(names, values))


def is_exception_return(value: int) -> bool:
    """Return whether *value* is a Cortex-M EXC_RETURN token."""
    return (value & 0xFFFFFF00) == 0xFFFFFF00 and (value & 0x03) == 0x01


def normalize_code_address(value: int) -> int:
    return value & ~1


def _in_executable_range(value: int, ranges: Iterable[tuple[int, int]]) -> bool:
    address = normalize_code_address(value)
    return any(start <= address < end for start, end in ranges)


def find_exception_stack(
    core_registers: dict[str, int],
    stack_regions: dict[str, tuple[int, bytes]],
    executable_ranges: list[tuple[int, int]],
) -> dict[str, Any] | None:
    """Locate a Cortex-M basic exception frame in captured MSP/PSP data.

    Besides the architectural frame-at-SP case, this recognizes handlers such
    as RT-Thread that save EXC_RETURN and r4-r11 below the hardware frame before
    entering C code.
    """
    handler_lr = int(core_registers.get("lr", 0))
    direct_return = handler_lr if is_exception_return(handler_lr) else None
    direct_pointer = None
    direct_frame_address = None
    if direct_return is not None:
        direct_pointer = "psp" if direct_return & (1 << 2) else "msp"
        direct_base = int(core_registers.get(direct_pointer, 0))
        direct_frame_address = direct_base + (72 if not (direct_return & (1 << 4)) else 0)

    candidates: list[tuple[int, dict[str, Any]]] = []
    for pointer_name, (base, data) in stack_regions.items():
        word_count = len(data) // 4
        if word_count < 8:
            continue
        words = struct.unpack(f"<{word_count}I", data[:word_count * 4])
        for index in range(word_count - 7):
            frame = dict(zip(
                ["r0", "r1", "r2", "r3", "r12", "lr", "pc", "xpsr"],
                words[index:index + 8],
            ))
            if not frame["xpsr"] & (1 << 24):
                continue
            if not _in_executable_range(frame["pc"], executable_ranges):
                continue

            frame_address = base + index * 4
            score = 100
            if _in_executable_range(frame["lr"], executable_ranges):
                score += 20
            elif is_exception_return(frame["lr"]):
                score += 10

            saved_return = None
            for saved_index in range(index - 1, max(-1, index - 33), -1):
                if is_exception_return(words[saved_index]):
                    saved_return = words[saved_index]
                    expected_pointer = "psp" if saved_return & (1 << 2) else "msp"
                    score += 250 if expected_pointer == pointer_name else -100
                    score += max(0, 32 - (index - saved_index))
                    break

            if direct_frame_address == frame_address and direct_pointer == pointer_name:
                score += 1000
                saved_return = direct_return

            candidates.append((score, {
                "frame": frame,
                "pointer": pointer_name,
                "pointer_address": base,
                "frame_address": frame_address,
                "frame_offset": frame_address - base,
                "exc_return": saved_return,
                "handler_lr": handler_lr,
                "extended_frame": bool(saved_return is not None and not (saved_return & (1 << 4))),
                "stack_data": data,
            }))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _function_for_address(symbols: Iterable[Any], address: int) -> str | None:
    normalized = normalize_code_address(address)
    matches: list[tuple[int, int, str]] = []
    for symbol in symbols:
        if getattr(symbol, "kind", None) != "function":
            continue
        start = normalize_code_address(int(getattr(symbol, "address", 0)))
        size = max(2, int(getattr(symbol, "size", 0)))
        if start <= normalized < start + size:
            matches.append((start, size, str(getattr(symbol, "name", ""))))
    if not matches:
        return None
    return max(matches, key=lambda item: (item[0], -item[1]))[2]


def _function_starts_at(symbols: Iterable[Any], address: int) -> bool:
    normalized = normalize_code_address(address)
    return any(
        getattr(symbol, "kind", None) == "function"
        and normalize_code_address(int(getattr(symbol, "address", 0))) == normalized
        for symbol in symbols
    )


def build_call_stack(
    frame: dict[str, int],
    *,
    frame_address: int,
    stack_base: int,
    stack_data: bytes,
    executable_ranges: list[tuple[int, int]],
    symbols: Iterable[Any],
    max_frames: int = 12,
) -> list[dict[str, Any]]:
    """Build an exact fault frame plus a bounded heuristic caller stack."""
    symbol_list = list(symbols)
    frames: list[dict[str, Any]] = []
    seen: set[int] = set()

    def append(value: int, source: str, confidence: str, stack_address: int | None = None) -> None:
        if len(frames) >= max_frames:
            return
        normalized = normalize_code_address(value)
        lookup_address = normalized if (
            source == "exception_pc" or _function_starts_at(symbol_list, normalized)
        ) else max(0, normalized - 2)
        if normalized in seen or not _in_executable_range(normalized, executable_ranges):
            return
        seen.add(normalized)
        record: dict[str, Any] = {
            "index": len(frames),
            "address": value,
            "lookup_address": lookup_address,
            "function": _function_for_address(symbol_list, lookup_address),
            "source": source,
            "confidence": confidence,
        }
        if stack_address is not None:
            record["stack_address"] = stack_address
        frames.append(record)

    append(frame["pc"], "exception_pc", "exact")
    append(frame["lr"], "exception_lr", "high")

    scan_offset = max(0, frame_address + 32 - stack_base)
    scan_data = stack_data[scan_offset:]
    word_count = len(scan_data) // 4
    if word_count:
        for index, value in enumerate(struct.unpack(f"<{word_count}I", scan_data[:word_count * 4])):
            if len(frames) >= max_frames:
                break
            if not value & 1:
                continue
            append(value, "stack_scan", "heuristic", frame_address + 32 + index * 4)
    return frames


def addr2line(
    source: str,
    *addresses: int,
    backend: str | None = None,
    project_root: str | None = None,
) -> dict[int, str]:
    if not source or not addresses:
        return {}
    from mklink.elf_backend import lookup_source_locations

    try:
        return lookup_source_locations(
            source,
            addresses,
            backend=backend,
            project_root=project_root,
        )
    except Exception:
        # Source decoration is best-effort; fault decoding remains available.
        return {}


def format_hardfault_report(
    fault_regs: dict[str, int],
    *,
    frame: dict[str, int] | None = None,
    locations: dict[int, str] | None = None,
) -> str:
    locations = locations or {}
    lines = ["========== Hard Fault Analysis ==========", "--- Fault Status ---"]
    cfsr = fault_regs.get("SCB.CFSR", 0)
    hfsr = fault_regs.get("SCB.HFSR", 0)
    lines.append(f"CFSR: 0x{cfsr:08X}")
    for item in decode_cfsr(cfsr) or ["no configurable fault bits set"]:
        lines.append(f"  - {item}")
    lines.append(f"HFSR: 0x{hfsr:08X}")
    for item in decode_hfsr(hfsr) or ["no hard fault status bits set"]:
        lines.append(f"  - {item}")
    for name in ("SCB.MMFAR", "SCB.BFAR", "SCB.AFSR"):
        if name in fault_regs:
            lines.append(f"{name}: 0x{fault_regs[name]:08X}")
    if frame:
        lines.extend(["", "--- Stack Frame ---"])
        for name in ["r0", "r1", "r2", "r3", "r12", "lr", "pc", "xpsr"]:
            value = frame[name]
            suffix = f"  {locations[value]}" if value in locations else ""
            lines.append(f"{name.upper():>4} = 0x{value:08X}{suffix}")
    return "\n".join(lines)
