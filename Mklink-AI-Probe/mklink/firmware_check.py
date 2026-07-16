"""Probe firmware version check for MicroLink (V3/V4) burners.

纯函数 + dataclass 设计；CLI / FastAPI / GUI 共用。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal
import os

# 固件文件名格式：MicroLink_V3.3.1.uf2 / MicroLink_V4.3.1.uf2
_FIRMWARE_FILE_RE = re.compile(
    r"^MicroLink_(V(\d+)\.(\d+)\.(\d+))\.uf2$"
)

# Firmware directory name (relative to repo/package root)
FIRMWARE_DIR_NAME = "MK-Firmware"

# Default environment variable for overriding firmware dir
FIRMWARE_DIR_ENV = "MKLINK_FIRMWARE_DIR"

# Serial command timeout (seconds) for cmd.get_version()
DEFAULT_VERSION_TIMEOUT = 5.0

# Status of CheckResult
CheckStatus = Literal["ok", "upgrade_required", "no_firmware_dir", "skipped"]


@dataclass(frozen=True)
class Version:
    """SemVer-style version with V<major>.<minor>.<patch> string format."""
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"V{self.major}.{self.minor}.{self.patch}"

    def __lt__(self, other: "Version") -> bool:
        return (self.major, self.minor, self.patch) < (
            other.major, other.minor, other.patch
        )

    def __le__(self, other: "Version") -> bool:
        return self == other or self < other

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) == (
            other.major, other.minor, other.patch
        )

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch))


@dataclass
class FirmwareInfo:
    """A single MicroLink_V*.uf2 firmware file in MK-Firmware/."""
    name: str
    version: Version
    model: str  # "V3" | "V4"
    path: Path

    @property
    def version_str(self) -> str:
        return str(self.version)


def parse_firmware_filename(name) -> FirmwareInfo | None:
    """Parse a MicroLink_V<major>.<minor>.<patch>.uf2 filename.

    Accepts str or Path; returns None for non-matching names.
    """
    raw = Path(name).name  # strip parent directories
    m = _FIRMWARE_FILE_RE.match(raw)
    if not m:
        return None
    major = int(m.group(2))
    minor = int(m.group(3))
    patch = int(m.group(4))
    return FirmwareInfo(
        name=raw,
        version=Version(major, minor, patch),
        model=f"V{major}",
        path=Path(name),
    )


def list_firmwares(root: Path) -> list[FirmwareInfo]:
    """List all MicroLink_V*.uf2 files in `root`, sorted by version ascending.

    Raises FileNotFoundError if `root` does not exist.
    Files that don't match the pattern are silently skipped.
    """
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"Firmware directory not found: {root}")
    if not root.is_dir():
        raise FileNotFoundError(f"Not a directory: {root}")

    result: list[FirmwareInfo] = []
    for entry in root.iterdir():
        info = parse_firmware_filename(entry)
        if info is not None:
            result.append(info)
    result.sort(key=lambda f: f.version)
    return result


def find_min_version(firmwares: list[FirmwareInfo]) -> Version | None:
    """Return the lowest version among firmwares, or None if empty."""
    if not firmwares:
        return None
    return min(f.version for f in firmwares)


def find_recommended_uf2(
    firmwares: list[FirmwareInfo], current: Version | None
) -> FirmwareInfo | None:
    """Recommend the highest-version firmware with the same major version as `current`.

    Returns None if current is None or no firmware shares current.major.
    """
    if current is None or not firmwares:
        return None
    same_major = [f for f in firmwares if f.version.major == current.major]
    if not same_major:
        return None
    return max(same_major, key=lambda f: f.version)


def _resolve_firmware_root() -> Path:
    """Resolve the MK-Firmware directory.

    Priority:
      1. MKLINK_FIRMWARE_DIR env var
      2. <cwd>/MK-Firmware
      3. <package_parent>/MK-Firmware  (i.e., one level above mklink/ in the installed package)

    Returns the first path that exists; if none exist, returns the env-var path
    (or cwd path) so the caller can decide how to handle the missing case.
    """
    # 1. env var
    env_path = os.environ.get(FIRMWARE_DIR_ENV)
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return candidate
        # env-set but missing → still return it; caller handles FileNotFoundError
        return candidate

    # 2. cwd
    cwd_candidate = Path.cwd() / FIRMWARE_DIR_NAME
    if cwd_candidate.exists():
        return cwd_candidate

    # 3. package parent (one level above the mklink/ package)
    pkg_parent = _PACKAGE_PARENT_OVERRIDE if _PACKAGE_PARENT_OVERRIDE is not None else Path(__file__).resolve().parent.parent
    pkg_candidate = pkg_parent / FIRMWARE_DIR_NAME
    return pkg_candidate  # may not exist; caller handles


# Test seam: lets tests inject a different package parent.
_PACKAGE_PARENT_OVERRIDE: Path | None = None


def read_device_version(port: str, *, timeout: float = DEFAULT_VERSION_TIMEOUT) -> Version | None:
    """Read probe firmware version via cmd.get_version().

    Returns the parsed Version, or None if the response cannot be parsed.
    Raises (TimeoutError, ConnectionError, etc.) on serial errors — caller
    decides how to recover.
    """
    from mklink.bridge import MKLinkSerialBridge

    bridge = MKLinkSerialBridge(port)
    try:
        if not bridge.connect():
            raise ConnectionError("Unable to connect to MKLink CDC port")
        resp = bridge.send_command("cmd.get_version()", timeout=timeout)
    finally:
        bridge.close()
    # Reuse the existing CLI parser (single source of truth for the format)
    from mklink.cli import _parse_version_response
    current_str, _ = _parse_version_response(resp)
    if not current_str:
        return None
    # Re-parse into Version using the firmware file regex (same shape)
    m = _FIRMWARE_FILE_RE.match(f"MicroLink_{current_str}.uf2")
    if not m:
        return None
    return Version(int(m.group(2)), int(m.group(3)), int(m.group(4)))


# Late-bound import: bridge is only needed when read_device_version is called.
# This avoids forcing pyserial import on every module load.
def __getattr__(name: str):
    if name == "MKLinkSerialBridge":
        from mklink.bridge import MKLinkSerialBridge
        return MKLinkSerialBridge
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@dataclass
class CheckResult:
    """Outcome of probe firmware check. See CheckStatus for possible values."""
    status: CheckStatus
    current_version: Version | None
    min_required_version: Version | None
    recommended_uf2: FirmwareInfo | None
    all_uf2s: list[FirmwareInfo]
    firmware_dir: Path | None
    instructions: str

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "current_version": str(self.current_version) if self.current_version else None,
            "min_required_version": str(self.min_required_version) if self.min_required_version else None,
            "recommended_uf2": _firmware_to_dict(self.recommended_uf2) if self.recommended_uf2 else None,
            "all_uf2s": [_firmware_to_dict(f) for f in self.all_uf2s],
            "firmware_dir": str(self.firmware_dir) if self.firmware_dir else None,
            "instructions": self.instructions,
        }


def _firmware_to_dict(f: FirmwareInfo) -> dict:
    return {
        "name": f.name,
        "version": f.version_str,
        "model": f.model,
        "path": str(f.path),
    }


# Button locations per probe model (V3: between two "eyes"; V4: side toggle)
_BUTTON_HINT = {
    "V3": "按住 V3 探针上**两个眼睛中间**的按钮",
    "V4": "按住 V4 探针**侧边拨轮**按钮",
}


def build_instructions(result: CheckResult) -> str:
    """Build the user-facing multi-line instructions text.

    Used by both CLI (printed as [WARN] block) and GUI (rendered in modal).
    """
    lines: list[str] = []
    lines.append("[WARN] 探针固件需要升级，请按以下步骤操作：")
    lines.append("")

    # 1. Determine button hint based on what we know about the probe model
    model: str | None = None
    if result.current_version is not None:
        model = f"V{result.current_version.major}"
    if model and model in _BUTTON_HINT:
        lines.append(f"  1. {_BUTTON_HINT[model]}，再插上 USB 上电")
    else:
        # unknown model — explain both
        lines.append("  1. 按住探针的升级按钮不放：")
        lines.append(f"     - V3 探针：{_BUTTON_HINT['V3']}")
        lines.append(f"     - V4 探针：{_BUTTON_HINT['V4']}")
        lines.append("     然后插上 USB 上电")
    lines.append("  2. 此时电脑会弹出一个 MICROKEEN U 盘")
    lines.append("  3. 将以下固件文件拷贝到该 U 盘根目录：")

    # 2. Tell the user which UF2 to use
    if result.recommended_uf2 is not None:
        lines.append(f"     - {result.recommended_uf2.path}")
    elif result.current_version is not None and not result.recommended_uf2:
        # current known but no same-major firmware
        lines.append(
            f"     - （无 V{result.current_version.major} 同型号固件，"
            "请检查 MK-Firmware/ 目录或联系维护者）"
        )
    else:
        for f in result.all_uf2s:
            lines.append(f"     - {f.path}")
    lines.append("  4. 拷贝完成后拔下 USB，重新插上即可使用新固件")
    lines.append("")
    if result.current_version is not None and result.min_required_version is not None:
        lines.append(
            f"  [诊断] 当前 {result.current_version}，"
            f"最低要求 {result.min_required_version}"
        )
    return "\n".join(lines)


def check_probe_firmware(
    port: str | None, firmware_root: Path
) -> CheckResult:
    """Top-level check: list firmwares, read device version, decide status.

    Failure-soft: never raises. Any error → returns a CheckResult with
    a non-'ok' status. UI/CLI can inspect `status` and act accordingly.
    """
    # Step 1: scan firmware directory
    try:
        firmwares = list_firmwares(firmware_root)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return CheckResult(
            status="no_firmware_dir",
            current_version=None,
            min_required_version=None,
            recommended_uf2=None,
            all_uf2s=[],
            firmware_dir=Path(firmware_root),
            instructions="",
        )

    if not firmwares:
        return CheckResult(
            status="no_firmware_dir",
            current_version=None,
            min_required_version=None,
            recommended_uf2=None,
            all_uf2s=[],
            firmware_dir=Path(firmware_root),
            instructions="",
        )

    min_version = find_min_version(firmwares)
    assert min_version is not None  # firmwares non-empty implies min is not None

    # Step 2: read device version (may fail silently)
    current: Version | None = None
    if port is None:
        return CheckResult(
            status="skipped",
            current_version=None,
            min_required_version=min_version,
            recommended_uf2=None,
            all_uf2s=firmwares,
            firmware_dir=Path(firmware_root),
            instructions="",
        )

    try:
        current = read_device_version(port)
    except TimeoutError:
        # E4: probe is too old to respond — treat as unknown version
        current = None
    except Exception:
        # E8: other serial errors (ConnectionError, SerialException) — skip
        return CheckResult(
            status="skipped",
            current_version=None,
            min_required_version=min_version,
            recommended_uf2=None,
            all_uf2s=firmwares,
            firmware_dir=Path(firmware_root),
            instructions="",
        )

    # Step 3: decide
    recommended = find_recommended_uf2(firmwares, current)
    requires_upgrade = (current is None) or (current < min_version)
    status: CheckStatus = "upgrade_required" if requires_upgrade else "ok"

    result = CheckResult(
        status=status,
        current_version=current,
        min_required_version=min_version,
        recommended_uf2=recommended,
        all_uf2s=firmwares,
        firmware_dir=Path(firmware_root),
        instructions="",
    )
    if status == "upgrade_required":
        result.instructions = build_instructions(result)
    return result
