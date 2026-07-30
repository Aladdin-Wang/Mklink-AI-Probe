# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir definition for the standalone Site Agent."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


SPEC_DIR = Path(SPECPATH).resolve()

EXCLUDED_PREFIXES = (
    "mklink.mcp_server",
    "mklink.web_entry",
    "mklink.remote.api",
    "mklink.remote.dashboards",
    "mklink.remote.mcp",
    "mklink.remote.offline_download_api",
    "mklink.remote.online_flash_api",
    "mklink.remote.stream_api",
    "mklink.remote.stream_hub",
    "mklink.remote.stream_protocol",
    "mklink.cmsis_dap.builtin_flm_bundle",
    "mklink.cmsis_dap.builtin_pack_bundle",
)


def include_module(name):
    return not any(
        name == prefix or name.startswith(f"{prefix}.")
        for prefix in EXCLUDED_PREFIXES
    )


hidden_imports = collect_submodules("mklink", filter=include_module)
hidden_imports += collect_submodules("websockets")
hidden_imports += collect_submodules("serial")
hidden_imports += collect_submodules("pymodbus")
hidden_imports += collect_submodules("elftools")
hidden_imports += collect_submodules("pycparser")

data_files = copy_metadata("mklink")
data_files += copy_metadata("pycparser")
data_files += collect_data_files(
    "mklink",
    includes=[
        "mcu_profiles.json",
        "modbus/profiles/*.json",
        "modbus/prompts/*.md",
        "serial/profiles/*.json",
    ],
)

analysis = Analysis(
    [str(SPEC_DIR / "entry.py")],
    pathex=[],
    binaries=[],
    datas=data_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "fastapi",
        "fastmcp",
        "starlette",
        "uvicorn",
        "pytest",
        "build",
        "PyInstaller",
        *EXCLUDED_PREFIXES,
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="mklink-remote-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="mklink-remote-agent",
)
