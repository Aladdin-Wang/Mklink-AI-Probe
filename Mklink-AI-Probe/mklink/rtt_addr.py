"""
MKLink Serial Bridge — RTT 地址查找（从 .map / .elf / .out 文件）。

默认使用随包内置的 pyelftools；外部 GNU/IAR 工具仅用于格式兼容后备。
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from mklink.elf_backend import ElfParseError, list_elf_symbols


# 静态模式（rtt_storage_mode=1）地址解析：优先从 Keil .uvprojx 宏定义 + scatter 段定位
# 跳过 RTT 库的运行时扫描，直接用编译期固定地址。


@dataclass
class RTTFindResult:
    """RTT 地址查找结果。"""

    addr: str | None = None
    source: str = ""
    details: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    path_checked: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.addr)


def find_rtt_addr_from_map(
    map_file_path: str,
    *,
    project_root: str | None = None,
) -> str | None:
    """向后兼容接口：返回 RTT 地址或 None。"""
    return diagnose_rtt_addr(map_file_path, project_root=project_root).addr


def diagnose_rtt_addr(
    map_file_path: str,
    *,
    project_root: str | None = None,
) -> RTTFindResult:
    """诊断 RTT 地址查找过程，返回地址和失败原因。

    解析顺序：
    1. 静态模式（仅当 project_root 提供）：从 .uvprojx + scatter 解析固定地址
    2. 动态模式（默认）：从 .map / .elf / .out 符号搜索
    """
    # 1) 静态模式：项目根目录存在时优先尝试
    if project_root:
        static_result = find_rtt_addr_from_uvprojx(project_root)
        if static_result.success:
            return static_result

    path = Path(map_file_path)
    result = RTTFindResult()
    result.path_checked.append(str(path))

    # 把静态尝试的诊断也带过去，便于排查
    if project_root:
        for line in static_result.details:
            result.details.append(f"[static] {line}")
        for line in static_result.warnings:
            result.warnings.append(f"[static] {line}")

    if not path.exists():
        result.details.append(f"文件不存在: {map_file_path}")
        return result

    # 优先按传入文件类型解析。
    if path.suffix.lower() in (".elf", ".out", ".axf"):
        addr = _find_rtt_in_binary(path, result)
        if addr:
            result.addr = addr
            result.source = f"binary:{path.name}"
            return result
    else:
        addr = _find_rtt_in_map(path, result)
        if addr:
            result.addr = addr
            result.source = f"map:{path.name}"
            return result

    # 对 map 文件自动回退到同目录/兄弟目录的 ELF/OUT。
    if path.suffix.lower() == ".map":
        for candidate in _candidate_binary_paths(path):
            result.path_checked.append(str(candidate))
            if not candidate.exists():
                continue
            addr = _find_rtt_in_binary(candidate, result)
            if addr:
                result.addr = addr
                result.source = f"binary:{candidate.name}"
                return result

    # 如果还没找到，补充 map 诊断。
    if path.suffix.lower() == ".map":
        _diagnose_map_failure(path, result)

    if not result.details:
        result.details.append("未找到 _SEGGER_RTT 地址")
    return result


def _candidate_binary_paths(map_path: Path) -> list[Path]:
    """根据 .map 路径推断同构建目录中的 .out/.elf/.axf。"""
    candidates: list[Path] = []
    stem = map_path.stem

    for suffix in (".out", ".elf", ".axf"):
        candidates.append(map_path.with_suffix(suffix))

    if map_path.parent.name.lower() == "list":
        sibling_dir = map_path.parent.parent / "Exe"
        for suffix in (".out", ".elf", ".axf"):
            candidates.append(sibling_dir / f"{stem}{suffix}")

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _find_rtt_in_binary(path: Path, result: RTTFindResult) -> str | None:
    """优先用内置 pyelftools，格式不兼容时再调用外部符号工具。"""
    try:
        symbols = list_elf_symbols(str(path), backend="builtin")
    except (ImportError, ElfParseError) as error:
        result.warnings.append(f"内置 pyelftools 无法解析 {path.name}: {error}")
        return _find_rtt_in_binary_external(path, result)

    for symbol in symbols:
        if symbol.name != "_SEGGER_RTT":
            continue
        if _is_valid_ram_addr(symbol.address):
            result.details.append("内置 pyelftools 已解析 _SEGGER_RTT")
            return f"0x{symbol.address:08x}"
        result.warnings.append(
            f"内置 pyelftools 找到 _SEGGER_RTT，但地址不在 RAM 范围: "
            f"0x{symbol.address:08x}"
        )
        return None

    result.details.append("内置 pyelftools 已解析符号表，但未找到 _SEGGER_RTT")
    return None


def _find_rtt_in_binary_external(path: Path, result: RTTFindResult) -> str | None:
    """兼容 pyelftools 无法解析的 GNU/IAR 二进制格式。"""
    tools = [
        ["arm-none-eabi-nm", str(path)],
        ["D:\\IAR\\arm\\bin\\ielfdumparm.exe", str(path)],
        ["D:\\IAR\\arm\\bin\\ielftool.exe", "--symbols", str(path)],
    ]

    saw_missing_tool = False
    for cmd in tools:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=10,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt"
                    else 0
                ),
            )
        except FileNotFoundError:
            saw_missing_tool = True
            continue
        except subprocess.TimeoutExpired:
            result.warnings.append(f"符号工具超时: {cmd[0]}")
            continue

        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        addr = _extract_rtt_addr_from_text(output)
        if addr:
            return addr

    if saw_missing_tool:
        result.warnings.append("未找到可用的符号工具（arm-none-eabi-nm / ielfdumparm / ielftool）")
    return None


def _find_rtt_in_map(path: Path, result: RTTFindResult | None = None) -> str | None:
    """从 .map 文件中正则匹配 RTT 地址。"""
    patterns = [
        r"^\s*(0x[0-9a-fA-F]{8})\s+_SEGGER_RTT(?:\s|$)",
        r"^\s*(0x[0-9a-fA-F]{8})\s+\S+\s+_SEGGER_RTT(?:\s|$)",
        r"^\s*([0-9a-fA-F]{8})\s+[TtBbDd]\s+_SEGGER_RTT(?:\s|$)",
        r"^\s*_SEGGER_RTT\s+(0x[0-9a-fA-F]{8})(?:\s|$)",
        r"^\s*_SEGGER_RTT\s+(0x[0-9a-fA-F]{8})\s+[0-9a-fA-Fx]+\s+[A-Za-z]+(?:\s|$)",
    ]

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "_SEGGER_RTT" not in line:
                    continue
                for pattern in patterns:
                    match = re.search(pattern, line)
                    if not match:
                        continue
                    addr = match.group(1)
                    if not addr.startswith("0x"):
                        addr = "0x" + addr
                    addr_int = int(addr, 16)
                    if _is_valid_ram_addr(addr_int):
                        return addr
                    if result is not None:
                        result.warnings.append(f"找到 _SEGGER_RTT 但地址不在 RAM 范围: {addr}")
    except OSError as e:
        if result is not None:
            result.details.append(f"读取文件失败: {e}")

    return None


def _extract_rtt_addr_from_text(text: str) -> str | None:
    """从符号工具输出中提取 _SEGGER_RTT 地址。"""
    patterns = [
        r"\b([0-9A-Fa-f]{8})\b\s+[A-Za-z]\s+_SEGGER_RTT(?:\s|$)",
        r"\b([0-9A-Fa-f]{8})\b.*\b_SEGGER_RTT\b",
        r"_SEGGER_RTT\b.*\b(0x[0-9A-Fa-f]{8})\b",
    ]
    for line in text.splitlines():
        if "_SEGGER_RTT" not in line or "SEGGER_RTT_CB" in line:
            continue
        for pattern in patterns:
            match = re.search(pattern, line)
            if not match:
                continue
            addr = match.group(1)
            if not addr.startswith("0x"):
                addr = "0x" + addr
            if _is_valid_ram_addr(int(addr, 16)):
                return addr
    return None


def _diagnose_map_failure(path: Path, result: RTTFindResult) -> None:
    """对 map 文件失败场景给出更可执行的诊断。"""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        result.details.append(f"读取 MAP 文件失败: {e}")
        return

    has_segger_obj = "SEGGER_RTT.o" in content or "SEGGER_RTT_printf.o" in content
    has_rtt_init = "SEGGER_RTT_Init" in content
    has_rtt_symbol = "_SEGGER_RTT" in content

    if has_rtt_symbol:
        result.details.append("MAP 文件包含 _SEGGER_RTT 符号，但当前解析器未能提取地址")
        return

    if has_segger_obj or has_rtt_init:
        result.details.append("已发现 SEGGER RTT 相关对象或函数，但未发现 _SEGGER_RTT 符号")
        result.warnings.append("可能是链接裁剪、MAP 输出格式变化，或应改从 .out/.elf 符号表读取")
        return

    result.details.append("未发现 SEGGER RTT 相关对象或符号")
    result.warnings.append("请确认已运行 rtt-integrate，并重新完整编译生成最新 MAP/OUT 后再试")


def _is_valid_ram_addr(addr: int) -> bool:
    """检查地址是否在常见 RAM 区域范围内。"""
    return (
        0x20000000 <= addr <= 0x3FFFFFFF  # 主 SRAM
        or 0x10000000 <= addr <= 0x1FFFFFFF  # CCM / Backup SRAM
        or 0x30000000 <= addr <= 0x3FFFFFFF  # SRAM4 等
    )


# --- 静态模式（rtt_storage_mode=1）地址解析 ---

# Keil uvprojx 中 Define 行的 SEGGER_RTT_SECTION 段名捕获
# 支持三种形式：
#   SEGGER_RTT_SECTION=.segger_rtt_ops
#   SEGGER_RTT_SECTION=".segger_rtt_ops"
#   SEGGER_RTT_SECTION=\".segger_rtt_ops\"
_UVPROJX_SECTION_RE = re.compile(
    r"SEGGER_RTT_SECTION\s*=\s*"
    r"(?:\"([.\w]+)\"|\\\"([.\w]+)\\\"|([.\w]+))",
    re.IGNORECASE,
)
# MKLINK_RTT_STATIC 触发宏：仅出现即启用静态模式（无值，避开 IDE 引号自动剥离）
_UVPROJX_MKLINK_STATIC_RE = re.compile(
    r"\bMKLINK_RTT_STATIC\b",
    re.IGNORECASE,
)
# uvprojx 中 ScatterFile 路径捕获
_UVPROJX_SCATTER_RE = re.compile(
    r"<ScatterFile>\s*([^<]+?)\s*</ScatterFile>",
    re.IGNORECASE,
)
# uvprojx 中 Define 标签包裹
_UVPROJX_DEFINE_RE = re.compile(
    r"<Define>\s*([^<]+?)\s*</Define>",
    re.IGNORECASE,
)
# scatter 文件中执行域段：NAME 0xADDR 0xSIZE { ... *.o (.SECTION) ... }
# 兼容 AC5/IAR 写法（段名前可有空格，十六进制大小写）
# 排除 load region（以 LR_ 开头），只匹配 execution region（ER_/RW_）
_SCATTER_EXEC_RE = re.compile(
    r"^\s*(?!LR_)(\w+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s*\{",
    re.MULTILINE,
)
_SCATTER_SECTION_INNER_RE = re.compile(
    r"\.\s*([.\w]+)\s*\)",
)


def find_rtt_addr_from_uvprojx(project_root: str) -> RTTFindResult:
    """从 Keil .uvprojx 解析静态编译模式下 RTT 控制块地址。

    工作流程：
    1. 在 project_root 下找 .uvprojx（顶层优先）
    2. 解析 <Define> 中 SEGGER_RTT_SECTION=.<section> 宏
    3. 解析 <ScatterFile> 路径
    4. 在 .sct 中找到包含该段的执行域，取其起始地址

    Returns:
        RTTFindResult.addr 命中时为 hex 字符串（如 "0x2001F800"），source 形如
        "static:uvprojx@0x2001F800"。
    """
    result = RTTFindResult()
    root = Path(project_root)

    uvprojx = _find_uvprojx(root)
    if not uvprojx:
        result.details.append("未找到 .uvprojx（仅支持 Keil 静态模式解析）")
        return result
    result.path_checked.append(str(uvprojx))

    try:
        text = uvprojx.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        result.details.append(f"读取 uvprojx 失败: {e}")
        return result

    # 1) 检测 MKLINK_RTT_STATIC 触发宏（推荐方式，不受 IDE 引号剥离影响）
    mklink_static = False
    for m in _UVPROJX_DEFINE_RE.finditer(text):
        if _UVPROJX_MKLINK_STATIC_RE.search(m.group(1)):
            mklink_static = True
            break

    # 2) 段名查找优先级：
    #    a) MKLINK_RTT_STATIC 触发 → 硬编码段名 ".segger_rtt_ops"
    #       （与 GEC6100D src/SEGGER_RTT.c 第 96-100 行的项目特定宏定义保持一致）
    #    b) 否则回退到 SEGGER_RTT_SECTION 三种引号形式
    if mklink_static:
        section_name = ".segger_rtt_ops"
        result.details.append("uvprojx 触发宏: MKLINK_RTT_STATIC（项目硬编码段名）")
    else:
        section_name = None
        for m in _UVPROJX_DEFINE_RE.finditer(text):
            defines = m.group(1)
            sm = _UVPROJX_SECTION_RE.search(defines)
            if sm:
                section_name = sm.group(1) or sm.group(2) or sm.group(3)
                break
        if not section_name:
            result.details.append(
                "uvprojx <Define> 中未找到 MKLINK_RTT_STATIC 或 SEGGER_RTT_SECTION 宏"
            )
            return result
        result.details.append(f"uvprojx 段名: {section_name}")

    # 2) 找 scatter 文件
    scatter_rel = None
    sm = _UVPROJX_SCATTER_RE.search(text)
    if sm:
        scatter_rel = sm.group(1).strip()
    if not scatter_rel:
        result.details.append("uvprojx 中未找到 <ScatterFile>")
        return result
    scatter_path = (uvprojx.parent / scatter_rel).resolve()
    if not scatter_path.exists():
        result.details.append(f"scatter 文件不存在: {scatter_path}")
        return result
    result.path_checked.append(str(scatter_path))

    # 3) 在 scatter 中找包含目标段的执行域
    try:
        sct_text = scatter_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        result.details.append(f"读取 scatter 失败: {e}")
        return result

    target_section = section_name.lstrip(".")
    for em in _SCATTER_EXEC_RE.finditer(sct_text):
        exec_name = em.group(1)
        exec_addr = int(em.group(2), 16)
        block_start = em.end()  # 块起点（'{' 之后）
        # 找到此执行域对应的 '}'，避免跨域匹配
        depth = 1
        i = block_start
        while i < len(sct_text) and depth > 0:
            ch = sct_text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        block = sct_text[block_start:i - 1]
        for sm2 in _SCATTER_SECTION_INNER_RE.finditer(block):
            if sm2.group(1) == target_section:
                if not _is_valid_ram_addr(exec_addr):
                    result.warnings.append(
                        f"scatter 执行域 {exec_name} 起始 {em.group(2)} 不在 RAM 范围"
                    )
                    return result
                result.addr = em.group(2)
                result.source = f"static:uvprojx@{em.group(2)}"
                result.details.append(
                    f"scatter 执行域 {exec_name} 起始地址 {em.group(2)}"
                )
                return result

    result.details.append(
        f"scatter {scatter_path.name} 中未找到段 {section_name}"
    )
    return result


def _find_uvprojx(root: Path) -> Path | None:
    """在项目根目录找一个 .uvprojx 文件（顶层优先）。"""
    for p in sorted(root.glob("*.uvprojx")):
        return p
    # 回退：任何子目录中第一个
    matches = list(root.glob("**/*.uvprojx"))
    return matches[0] if matches else None
