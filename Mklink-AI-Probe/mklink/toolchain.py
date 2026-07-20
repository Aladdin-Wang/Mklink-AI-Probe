"""Resolution + availability for the GNU Arm host tools (readelf, addr2line).

mklink shells out to ``arm-none-eabi-readelf`` (symbol table + DWARF parsing)
and ``arm-none-eabi-addr2line`` (HardFault source-line lookup). These are NOT
bundled with mklink — they come from the GNU Arm Embedded Toolchain or from
system binutils. This module centralizes *how* those binaries are located so
that every call site behaves identically and a missing tool surfaces as one
clear, actionable error instead of an opaque ``[WinError 2]``.

Resolution order (first existing hit wins, per tool):
  1. Environment override — ``$MKLINK_READELF`` / ``$MKLINK_ADDR2LINE``.
  2. Project config — ``.mklink/toolchain.json`` searched from cwd upward:
     ``{"readelf": "C:/.../arm-none-eabi-readelf.exe", "addr2line": "..."}``.
  3. Well-known install locations — winget Program Files / WinGet package
     cache, the portable ``~/.local/tools`` dir used by ``install.md``.
  4. ``shutil.which("arm-none-eabi-<tool>")`` — anything already on PATH.
  5. System binutils fallback — plain ``readelf`` / ``addr2line`` (reads any
     ELF; works for ``-s`` / ``--debug-dump`` / ``-e ... -f``).

Call sites should use :func:`require_readelf` / :func:`require_addr2line`
(raise :class:`ToolchainMissingError` with an install hint when absent) or
:func:`resolve_readelf` / :func:`resolve_addr2line` (return ``None``) — never
hardcode the binary name. :func:`status` reports availability for the MCP
``ping``/``connect`` layer so an agent can guide the user to install the
toolchain before any AXF feature is touched.
"""
from __future__ import annotations

import json
import os
import shutil
from functools import lru_cache
from pathlib import Path

# Environment-variable overrides (C).
ENV_READELF = "MKLINK_READELF"
ENV_ADDR2LINE = "MKLINK_ADDR2LINE"
# Project-local config file (C). Searched from cwd upward (git-style).
CONFIG_NAME = "toolchain.json"


class ToolchainMissingError(RuntimeError):
    """Raised when a required host tool cannot be resolved anywhere.

    Carries an actionable install hint so callers (and the MCP layer) can
    surface it verbatim instead of a bare FileNotFoundError.
    """

    def __init__(self, tool: str) -> None:
        self.tool = tool
        self.hint = (
            f"{tool} not found. Install the GNU Arm Embedded Toolchain "
            f"(e.g. `winget install Arm.GnuArmEmbeddedToolchain`) and put its "
            f"bin/ on PATH — or point at it via the {ENV_READELF if tool == 'readelf' else ENV_ADDR2LINE} "
            f"env var or .mklink/toolchain.json. mklink does not bundle this binary."
        )
        super().__init__(self.hint)


# --------------------------------------------------------------------------
# Config (.mklink/toolchain.json) — cwd-upward search, git-style.
# --------------------------------------------------------------------------
def load_toolchain_overrides(
    start: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """Return overrides from the nearest ``.mklink/toolchain.json``."""
    start_path = Path(start).resolve() if start is not None else Path.cwd()
    if start_path.is_file():
        start_path = start_path.parent
    for here in [start_path, *start_path.parents]:
        f = here / ".mklink" / CONFIG_NAME
        if f.is_file():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
            if isinstance(data, dict):
                return {k: str(v) for k, v in data.items() if isinstance(v, str)}
            return {}
    return {}


def _find_config() -> dict[str, str]:
    """Backward-compatible private alias for nearest toolchain overrides."""
    return load_toolchain_overrides()


# --------------------------------------------------------------------------
# Well-known install locations (D).
# --------------------------------------------------------------------------
def _wellknown_candidates(tool: str) -> list[str]:
    """Glob patterns for common install locations of the GNU Arm toolchain.

    Returns *patterns* (may contain ``*``); the caller expands + verifies.
    Prefers arm-none-eabi-<tool>; the system binutils fallback is handled
    separately via shutil.which so it always runs last.
    """
    exe = ".exe" if os.name == "nt" else ""
    arm_tool = f"arm-none-eabi-{tool}{exe}"
    sys_tool = f"{tool}{exe}"
    patterns: list[str] = []

    if os.name == "nt":
        progfiles = os.environ.get("ProgramFiles", r"C:\Program Files")
        progfiles_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        home = os.path.expanduser("~")
        # winget system-scope: <ProgramFiles>\Arm GNU Toolchain arm-none-eabi\<ver>\bin\
        patterns += [
            f"{progfiles}/Arm GNU Toolchain arm-none-eabi/*/bin/{arm_tool}",
            f"{progfiles_x86}/Arm GNU Toolchain arm-none-eabi/*/bin/{arm_tool}",
        ]
        # winget user-scope package cache + Links shim
        if localappdata:
            patterns += [
                f"{localappdata}/Microsoft/WinGet/Packages/*/bin/{arm_tool}",
                f"{localappdata}/Microsoft/WinGet/Packages/*/{arm_tool}",
                f"{localappdata}/Microsoft/WinGet/Links/{arm_tool}",
            ]
        # portable install location used by references/install.md
        patterns += [
            f"{home}/.local/tools/*/bin/{arm_tool}",
            f"{home}/.local/tools/bin/{arm_tool}",
        ]
    else:
        patterns += [
            f"/opt/gcc-arm-none-eabi/*/bin/{arm_tool}",
            "/usr/bin/" + arm_tool,
            "/usr/local/bin/" + arm_tool,
            "/opt/homebrew/bin/" + arm_tool,
        ]
    # System binutils fallback (always last) — GNU readelf/addr2line read any ELF.
    patterns += [sys_tool]
    return patterns


def _expand_first(patterns: list[str]) -> str | None:
    """Return the first pattern that resolves to an existing executable.

    Globs are sorted descending so a version directory wins over a generic
    one; a bare-name pattern resolves via shutil.which (PATH).
    """
    for pat in patterns:
        if "*" in pat:
            matches = sorted(Path(pat).parent.glob(Path(pat).name), reverse=True)
            for m in matches:
                if m.is_file():
                    return str(m)
        else:
            # Bare name → resolve via PATH (works cross-platform).
            found = shutil.which(pat)
            if found:
                return found
    return None


# --------------------------------------------------------------------------
# Public resolution API. Cached per-process; clear_cache() for tests.
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def resolve_readelf() -> str | None:
    """Resolve the readelf binary path, or ``None`` if unavailable."""
    env_path = os.environ.get(ENV_READELF)
    if env_path and Path(env_path).is_file():
        return env_path
    cfg = _find_config().get("readelf")
    if cfg and Path(cfg).is_file():
        return cfg
    return _expand_first(_wellknown_candidates("readelf"))


@lru_cache(maxsize=1)
def resolve_addr2line() -> str | None:
    """Resolve the addr2line binary path, or ``None`` if unavailable."""
    env_path = os.environ.get(ENV_ADDR2LINE)
    if env_path and Path(env_path).is_file():
        return env_path
    cfg = _find_config().get("addr2line")
    if cfg and Path(cfg).is_file():
        return cfg
    return _expand_first(_wellknown_candidates("addr2line"))


def require_readelf() -> str:
    """Return the readelf path, raising :class:`ToolchainMissingError` if absent."""
    p = resolve_readelf()
    if not p:
        raise ToolchainMissingError("readelf")
    return p


def require_addr2line() -> str:
    """Return the addr2line path, raising :class:`ToolchainMissingError` if absent."""
    p = resolve_addr2line()
    if not p:
        raise ToolchainMissingError("addr2line")
    return p


def status() -> dict[str, object]:
    """Snapshot of built-in ELF and optional GNU host-tool capabilities."""
    from mklink.elf_backend import elf_status

    return elf_status()


def clear_cache() -> None:
    """Drop cached resolutions (tests / config edits)."""
    resolve_readelf.cache_clear()
    resolve_addr2line.cache_clear()
