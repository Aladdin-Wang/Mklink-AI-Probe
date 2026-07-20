"""Explicit GNU readelf/addr2line compatibility backend."""

from __future__ import annotations

import re
import subprocess
from os import PathLike
from typing import Iterable

from mklink.elf_backend import ElfSection, ElfSymbol


_SYMBOL_RE = re.compile(
    r"^\s*\d+:\s+([0-9a-fA-F]+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+)$"
)


def _flag_bits(flags: str) -> int:
    bits = 0
    if "W" in flags:
        bits |= 0x1
    if "A" in flags:
        bits |= 0x2
    if "X" in flags:
        bits |= 0x4
    return bits


class ExternalElfBackend:
    name = "external"
    parser_version = "gnu-binutils-text-v1"

    def __init__(
        self,
        *,
        readelf: str | None = None,
        addr2line: str | None = None,
        project_root: str | PathLike[str] | None = None,
    ) -> None:
        self._readelf = readelf
        self._addr2line = addr2line
        self._project_root = project_root

    def _readelf_path(self) -> str:
        if self._readelf:
            return self._readelf
        from mklink.toolchain import require_readelf

        return require_readelf(self._project_root)

    def _addr2line_path(self) -> str:
        if self._addr2line:
            return self._addr2line
        from mklink.toolchain import require_addr2line

        return require_addr2line(self._project_root)

    def _run_readelf(self, *arguments: str, timeout: float = 60) -> str:
        try:
            result = subprocess.run(
                [self._readelf_path(), *arguments],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                text=True,
                timeout=timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"external readelf failed: {exc}") from exc
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "external readelf failed")
        return result.stdout

    def symbols(self, source: str) -> list[ElfSymbol]:
        output = self._run_readelf("-sW", source, timeout=30)
        symbols = []
        for line in output.splitlines():
            match = _SYMBOL_RE.match(line)
            if not match:
                continue
            kind_token = match.group(3)
            if kind_token not in {"OBJECT", "FUNC"} or match.group(6) == "UND":
                continue
            name = match.group(7).strip()
            if not name:
                continue
            section_token = match.group(6)
            section: int | str = (
                int(section_token) if section_token.isdigit() else section_token
            )
            symbols.append(
                ElfSymbol(
                    name=name,
                    address=int(match.group(1), 16),
                    size=int(match.group(2)),
                    kind="object" if kind_token == "OBJECT" else "function",
                    binding=match.group(4).lower(),
                    visibility=match.group(5).lower(),
                    section=section,
                )
            )
        return symbols

    def sections(self, source: str) -> list[ElfSection]:
        from mklink.memmap import parse_section_headers

        output = self._run_readelf("-S", source, timeout=30)
        return [
            ElfSection(
                name=section.name,
                address=section.address,
                size=section.size,
                flags=_flag_bits(section.flags),
                section_type="",
            )
            for section in parse_section_headers(output)
        ]

    def dwarf_info(self, source: str):
        from mklink.dwarf_parser import parse_dwarf_info_output

        return parse_dwarf_info_output(
            self._run_readelf("--debug-dump=info", source, timeout=60)
        )

    def source_locations(
        self, source: str, addresses: Iterable[int]
    ) -> dict[int, str]:
        requested = [int(address) for address in addresses]
        if not requested:
            return {}
        command = [self._addr2line_path(), "-e", source, "-f", "-p"]
        command.extend(f"0x{address:08X}" for address in requested)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                text=True,
                timeout=20,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"external addr2line failed: {exc}") from exc
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "external addr2line failed")
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return {address: line for address, line in zip(requested, lines)}
