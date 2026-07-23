"""
MKLink Serial Bridge — 依赖预检模块。

在 Skill 执行最开始运行，检查所有必需的外部依赖。
本模块仅依赖 stdlib，确保在 pyserial 缺失时也能正常报错。
"""

from __future__ import annotations

import os
import sys

REQUIRED_PACKAGES: dict[str, str] = {
    "serial": "pyserial",  # import_name -> pip_name
}

GUI_PACKAGES: dict[str, str] = {
    "fastapi": "fastapi>=0.100",
    "uvicorn": "uvicorn>=0.20",
    "websockets": "websockets>=11.0",
}


def check_dependencies() -> list[str]:
    """检查缺失的依赖，返回缺失包的 pip 名称列表。空列表表示全部满足。"""
    missing = []
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)
    return missing


def check_gui_dependencies() -> list[str]:
    """检查 GUI/远程服务所需的依赖，返回缺失包的 pip 名称列表。"""
    missing = []
    for import_name, pip_name in GUI_PACKAGES.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)
    return missing


def check_readelf_available() -> tuple[bool, str | None]:
    """检查 arm-none-eabi-readelf 是否可用。

    Returns:
        (available, path_or_error):
        - (True, exe_path) 如果可用
        - (False, error_message) 如果不可用
    """
    import subprocess

    from mklink.toolchain import resolve_readelf
    path = resolve_readelf()
    if not path:
        return False, "arm-none-eabi-readelf 未找到（PATH / MKLINK_READELF / .mklink/toolchain.json 均无）"

    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return True, path
        return False, f"arm-none-eabi-readelf 执行失败: {result.stderr[:100]}"
    except Exception as e:
        return False, f"arm-none-eabi-readelf 执行异常: {e}"


def check_elf_available(
    *, project_root: str | None = None
) -> tuple[bool, str | None]:
    """检查当前选择的 ELF 后端；默认内置 pyelftools。"""
    from mklink.elf_backend import elf_status

    try:
        status = elf_status(project_root=project_root)
    except Exception as exc:
        return False, str(exc)
    if status["elf_available"]:
        if status["elf_backend"] == "builtin":
            return True, f"builtin pyelftools {status['builtin_elf_version']}"
        return True, str(status.get("readelf_path") or "external readelf")
    return False, f"ELF backend unavailable: {status['elf_backend']}"


def require_dependencies() -> None:
    """检查依赖，缺失则打印安装指引并退出。

    应在 Skill 执行入口（如 CLI main()）最开始调用。
    """
    missing = check_dependencies()
    if not missing:
        return

    print("[FAIL] 缺少必需的 Python 包:")
    for pkg in missing:
        print(f"  - {pkg}")
    print(f"\n安装命令: pip install {' '.join(missing)}")
    sys.exit(1)


def require_gui_dependencies() -> None:
    """检查 GUI/远程服务依赖，缺失则打印安装指引并退出。

    应在使用 serve --backend fastapi 或启动 GUI 前调用。
    """
    missing = check_gui_dependencies()
    if not missing:
        return

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print("[FAIL] 缺少 GUI/远程服务所需的 Python 包:")
    for pkg in missing:
        print(f"  - {pkg}")
    print(f"\n安装命令:")
    print(f"  pip install {' '.join(missing)}")
    print(f"  或安装完整 GUI 依赖:")
    print(f"  pip install -e \"{skill_dir}[gui]\"")
    sys.exit(1)
