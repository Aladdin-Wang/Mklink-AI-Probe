"""
MKLink Serial Bridge — CLI 入口。

依赖检查 → 命令分发。
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import sys

from mklink._deps import require_dependencies


def _cli_security(args: argparse.Namespace) -> int:
    """Run a guarded one-shot reversible target security operation."""
    import json

    from mklink.security_operations import run_security_operation

    result = run_security_operation(
        args.security_command,
        args.target_part,
        voltage_mv=args.voltage_mv,
        confirm_user=args.confirm,
        confirm_data_loss=getattr(args, "confirm_data_loss", False),
        firmware=getattr(args, "firmware", None),
        base_address=getattr(args, "base_address", None),
        probe_id=args.probe_id,
        frequency=args.frequency,
        timeout=args.timeout,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        action = "解锁" if args.security_command == "unlock" else "加锁"
        reset = (
            "已完成 CTRL-AP 复位，未切换 VCC"
            if result["reset_mode"] == "default" and result["voltage_mv"] is None
            else f"已按 {result['voltage_mv']} mV 断电复位"
        )
        print(f"[OK] {result['target_part']} {action}完成，{reset}")
    return 0


def _cli_keil_parse(project_root: str):
    """解析 Keil .uvprojx 工程文件并显示配置。"""
    import json
    from mklink.keil_parser import find_uvprojx, parse_uvprojx

    uvp = find_uvprojx(project_root)
    if not uvp:
        print("[FAIL] 未找到 .uvprojx 文件")
        return

    print(f"[OK] 找到工程文件: {uvp}")
    info = parse_uvprojx(uvp)
    if not info:
        print("[FAIL] 解析工程文件失败")
        return

    # 格式化输出（排除 groups 以保持简洁）
    display = {k: v for k, v in info.items() if k != "groups"}
    print(json.dumps(display, indent=2, ensure_ascii=False))


def _cli_iar_parse(project_root: str):
    """解析 IAR .ewp 工程文件并显示配置。"""
    import json
    from mklink.iar_parser import find_ewp, parse_ewp

    ewp = find_ewp(project_root)
    if not ewp:
        print("[FAIL] 未找到 .ewp 文件")
        return

    print(f"[OK] 找到工程文件: {ewp}")
    info = parse_ewp(ewp)
    if not info:
        print("[FAIL] 解析工程文件失败")
        return

    # 格式化输出（排除冗余字段）
    exclude_keys = {"groups"}
    display = {k: v for k, v in info.items() if k not in exclude_keys}
    print(json.dumps(display, indent=2, ensure_ascii=False))


def _detect_hpm_segger_project(project_root: str) -> dict | None:
    """Detect HPM SDK output layouts.

    Prefer native CMake build directories (``*_flash_xip_debug/output``) over
    generated IDE exports, because one sample root may contain stale exports
    for several boards.
    """
    from pathlib import Path
    import json
    from mklink.hpm_config import HPM_BOARD_FLASH_CFG

    root = Path(project_root)

    def _read_json_target(json_files):
        for json_file in sorted(json_files):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    maybe_target = data.get("target")
                    target = maybe_target if isinstance(maybe_target, dict) else data
                    if isinstance(target, dict):
                        return target
            except Exception:
                continue
        return {}

    def _parse_cmake_cache(cache_file: Path) -> dict:
        values = {}
        try:
            for line in cache_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line or line.startswith(("//", "#")) or "=" not in line:
                    continue
                key_type, value = line.split("=", 1)
                key = key_type.split(":", 1)[0].strip()
                if key:
                    values[key] = value.strip()
        except Exception:
            return {}
        return values

    def _first_file(directory: Path, suffix: str) -> Path | None:
        files = sorted(directory.glob(f"*.{suffix}"))
        return files[0] if files else None

    cmake_candidates = []
    for cache_file in root.glob("**/CMakeCache.txt"):
        build_dir = cache_file.parent
        output_dir = build_dir / "output"
        if not output_dir.is_dir():
            continue
        bin_file = _first_file(output_dir, "bin")
        map_file = _first_file(output_dir, "map")
        elf_file = _first_file(output_dir, "elf")
        if not (bin_file and map_file and elf_file):
            continue

        cache = _parse_cmake_cache(cache_file)
        target = _read_json_target(
            list((build_dir / "segger_embedded_studio").glob("*.json"))
            + list((build_dir / "iar_embedded_workbench").glob("*.json"))
        )
        board = target.get("board") or cache.get("BOARD") or build_dir.name.split("_", 1)[0]
        soc = target.get("soc", "")
        device = target.get("target_device_name") or (f"{soc}x" if soc else board)
        cmake_candidates.append((
            bin_file.stat().st_mtime,
            {
                "ide_type": "HPM SDK CMake",
                "project_name": cache.get("CMAKE_PROJECT_NAME") or target.get("name", root.name),
                "device": device,
                "vendor": "HPMicro",
                "compiler": "gcc",
                "board": board,
                "soc": soc,
                "flash_base": "0x80003000",
                "bin_base": "0x80000400",
                "hpm_flash_cfg": HPM_BOARD_FLASH_CFG.get(str(board).lower()),
                "ram_base": "0x01200000",
                "flash_size": 0x1000000,
                "ram_size": 0x80000,
                "bin_path": str(bin_file.resolve()),
                "map_path": str(map_file.resolve()),
                "axf_path": str(elf_file.resolve()),
                "out_path": str(elf_file.resolve()),
                "readelf_path": cache.get("CMAKE_READELF", ""),
            },
        ))
    if cmake_candidates:
        return sorted(cmake_candidates, key=lambda item: item[0], reverse=True)[0][1]

    ses_candidates = []
    for ses_dir in root.glob("**/segger_embedded_studio"):
        exe_dir = ses_dir / "Output" / "Debug" / "Exe"
        if not exe_dir.is_dir():
            continue

        bin_files = sorted(exe_dir.glob("*.bin"))
        map_files = sorted(exe_dir.glob("*.map"))
        elf_files = sorted(exe_dir.glob("*.elf"))
        if not (bin_files and map_files and elf_files):
            continue

        target = _read_json_target(ses_dir.glob("*.json"))

        board = target.get("board", "hpm5301evklite")
        ses_candidates.append((
            bin_files[0].stat().st_mtime,
            {
            "ide_type": "SEGGER Embedded Studio",
            "project_name": target.get("name", root.name),
            "device": target.get("target_device_name", "HPM5301xEGx"),
            "vendor": "HPMicro",
            "compiler": "gcc",
            "board": board,
            "soc": target.get("soc", "HPM5301"),
            "flash_base": "0x80003000",
            "bin_base": "0x80000400",
            "hpm_flash_cfg": HPM_BOARD_FLASH_CFG.get(str(board).lower()),
            "ram_base": "0x00080300",
            "flash_size": 0x100000,
            "ram_size": 130304,
            "bin_path": str(bin_files[0].resolve()),
            "map_path": str(map_files[0].resolve()),
            "axf_path": str(elf_files[0].resolve()),
            "out_path": str(elf_files[0].resolve()),
            },
        ))
    if ses_candidates:
        return sorted(ses_candidates, key=lambda item: item[0], reverse=True)[0][1]

    return None


def _cli_project_init(project_root: str):
    """离线解析工程；连接、算法和 RTT 在使用时解析，不固化猜测的硬件信息。"""
    from pathlib import Path
    from mklink.keil_parser import find_uvprojx, parse_uvprojx
    from mklink.iar_parser import find_ewp, parse_ewp
    from mklink.project_config import (
        get_mklink_dir, lint_json_file, load_project_info,
        save_config, save_project_info,
    )

    # Reinitialization must not overwrite malformed or user-maintained settings.
    for name in ("config.json", "project_info.json", "keil_project.json",
                 "rtt_config.json", "toolchain.json"):
        if (get_mklink_dir(project_root) / name).exists():
            error = lint_json_file(project_root, name)
            if error:
                print(f"[FAIL] {error}；原配置未修改")
                return

    hpm = _detect_hpm_segger_project(project_root)
    uvp = find_uvprojx(project_root)
    ewp = find_ewp(project_root)
    if hpm:
        info = hpm
    elif uvp:
        info = parse_uvprojx(uvp)
        if info:
            info["ide_type"] = "Keil"
        if ewp:
            print("[INFO] 同时发现 Keil/IAR，使用 Keil 工程")
    elif ewp:
        info = parse_ewp(ewp)
        if info:
            info["ide_type"] = "IAR"
    else:
        print("[FAIL] 未找到 Keil、IAR 或 HPM SDK 工程")
        return
    if not info:
        print("[FAIL] 工程解析失败；原配置未修改")
        return

    # Keep only inputs needed by build/download/symbol tools. Do not infer a
    # profile key from a shared SW-DP ID, scan serial ports or copy an FLM here.
    fields = {
        "ide_type", "device", "vendor", "target_name", "config_name", "compiler",
        "uvprojx_path", "ewp_path", "hex_path", "bin_path", "map_path",
        "axf_path", "elf_path", "out_path", "flash_base", "flash_size", "ram_base",
        "ram_size", "scatter_file", "bin_base", "download_base", "board",
        "hpm_flash_cfg",
    }
    saved = load_project_info(project_root) or {}
    saved.update({key: value for key, value in info.items()
                  if key in fields and value not in (None, "", 0)})
    save_project_info(project_root, saved)
    if not (get_mklink_dir(project_root) / "config.json").exists():
        save_config(project_root, {"swd_clock": 1000000})

    print(f"[OK] {info.get('ide_type', 'HPM SDK')} · {info.get('device', '未指定器件')}")
    print(f"  固件: {info.get('bin_path') or info.get('hex_path') or '未配置'}")
    print("[OK] 已保存精简工程配置；已有连接、RTT 和工具链设置保持不变")
    print("[INFO] 连接时自动发现端口；烧录时按精确器件/地址选择算法，缺失或不明确时停止")


def _cli_copy_flm(project_root: str):
    """拷贝 FLM 文件到 MICROKEEN 磁盘。"""
    from mklink.project_config import load_config, load_project_info
    from mklink.discovery import check_flm_on_microkeen, copy_flm_to_microkeen
    from mklink.profiles import load_mcu_profiles

    project = load_project_info(project_root)
    if project is None:
        print("[FAIL] 项目未配置，先运行 `python -m mklink project-init`")
        return

    flm_name = project.get("flm_name", "")
    if not flm_name:
        config = load_config(project_root) or {}
        mcu_key = config.get("mcu_key", "")
        profile = load_mcu_profiles().get(mcu_key, {})
        flm_path = str(profile.get("flm_path", "")).replace("\\", "/")
        if flm_path:
            flm_name = flm_path.split("/")[-1]
    if not flm_name:
        print("[FAIL] 未找到 FLM 配置")
        print("提示: 先运行 `python -m mklink mcu-detect` 固化 MCU profile")
        return

    # 检查是否已存在
    exists, path = check_flm_on_microkeen(flm_name)
    if exists:
        print(f"[OK] FLM 已存在: {path}")
        return

    # 执行拷贝
    success, dest = copy_flm_to_microkeen(flm_name)
    if not success:
        print(f"[FAIL] FLM '{flm_name}' 拷贝失败")
        print("请确保：")
        print("  1. [MICROKEEN] 磁盘已插入")
        print("  2. Keil/Arm Pack 已安装且包含该芯片的 FLM")
    else:
        print(f"[OK] 已拷贝 FLM: {dest}")


def _cli_project_info(project_root: str):
    """显示项目已缓存的配置。"""
    import json
    from mklink.project_config import (
        load_config, load_project_info, load_rtt_config, is_configured,
    )
    from mklink.discovery import check_flm_on_microkeen

    if not is_configured(project_root):
        print("[*] 项目未配置，运行 `python -m mklink project-init` 初始化")
        return

    config = load_config(project_root)
    project = load_project_info(project_root)
    rtt = load_rtt_config(project_root)

    print("=== 基本配置 ===")
    if config:
        print(json.dumps(config, indent=2, ensure_ascii=False))

    if project:
        ide_type = project.get("ide_type", "Keil")
        print(f"\n=== {ide_type} 工程 ===")
        print(f"  设备: {project.get('device', '?')} ({project.get('vendor', '?')})")
        if ide_type == "Keil":
            print(f"  FLM: {project.get('flm_name', '?')}")
        elif ide_type == "IAR":
            print(f"  Flash Loader: {project.get('flash_loader_path', '?')}")
            print(f"  CPU: {project.get('cpu', '?')}")
        print(f"  Flash: {project.get('flash_base', '?')}")
        if project.get("bin_base"):
            print(f"  Bin base: {project.get('bin_base')}")
        if project.get("bin_path"):
            print(f"  BIN: {project.get('bin_path')}")
        print(f"  HEX: {project.get('hex_path', '?')}")
        print(f"  MAP: {project.get('map_path', '?')}")
        if project.get("axf_path"):
            print(f"  ELF/AXF: {project.get('axf_path')}")

        # 检查 MICROKEEN 磁盘上的 FLM（仅 Keil）
        if ide_type == "Keil":
            flm_name = project.get("flm_name", "")
            if flm_name:
                exists, path = check_flm_on_microkeen(flm_name)
                if exists:
                    print(f"  MICROKEEN FLM: {path}")
                else:
                    print(f"  MICROKEEN FLM: 未找到 '{flm_name}'")

    if rtt:
        print("\n=== RTT 配置 ===")
        print(json.dumps(rtt, indent=2, ensure_ascii=False))

    # Modbus 配置（从 config.json 中提取）
    if config and config.get("modbus_port"):
        print("\n=== Modbus 配置 ===")
        print(f"  串口: {config['modbus_port']}")
        print(f"  波特率: {config.get('modbus_baud', 9600)}")
        print(f"  校验位: {config.get('modbus_parity', 'N')}")
        print(f"  停止位: {config.get('modbus_stopbits', 1)}")


def _print_integration_result_v2(result: dict) -> None:
    """打印 v2 静态模式集成结果。"""
    print()
    print("=" * 52)
    print("  RTT 静态模式集成结果")
    print("=" * 52)

    copy = result.get("copy")
    if copy and copy.get("copied"):
        print("\n[1] 复制源文件:")
        for f in copy["copied"]:
            print(f"  + {f}")

    reg = result.get("register")
    if reg:
        if reg.get("added"):
            print("\n[2] 注册源文件到 uvprojx:")
            for f in reg["added"]:
                print(f"  + {f}")
        if reg.get("skipped"):
            for f in reg["skipped"]:
                print(f"  ~ {f} (已存在)")

    main_r = result.get("main")
    if main_r and main_r.get("success"):
        print("\n[3] main.c 已加 #include + SEGGER_RTT_Init()")

    macro = result.get("macro_use_rtt")
    if macro and macro.get("added"):
        print("\n[4] USE_RTT 宏已加入 uvprojx <Define>")

    sm = result.get("macro_static")
    if sm and sm.get("added"):
        print("\n[5] MKLINK_RTT_STATIC 宏已加入 uvprojx <Define>")

    sct = result.get("scatter")
    if sct and sct.get("success"):
        print("\n[6] scatter 已更新:")
        for c in sct.get("changes", []):
            print(f"  - {c}")

    if result.get("errors"):
        print("\n[FAIL] 错误:")
        for e in result["errors"]:
            print(f"  - {e}")


def _find_and_save_rtt_addr(project_root: str) -> None:
    """从 MAP 文件查 RTT 地址并写入 .mklink/rtt_config.json。"""
    from pathlib import Path
    from mklink.rtt_addr import find_rtt_addr_from_map
    from mklink.project_config import load_project_info, save_rtt_config, load_rtt_config

    root_path = Path(project_root)
    project = load_project_info(project_root) or {}
    map_path = project.get("map_path")
    if not map_path:
        for c in root_path.glob("**/*.map"):
            map_path = str(c)
            break

    if map_path and Path(map_path).exists():
        addr = find_rtt_addr_from_map(map_path)
        if addr:
            rtt_cfg = load_rtt_config(project_root) or {}
            old = rtt_cfg.get("rtt_addr", "")
            rtt_cfg["rtt_addr"] = addr
            rtt_cfg["rtt_storage_mode"] = 1
            save_rtt_config(project_root, rtt_cfg)
            print(f"[OK] RTT 地址已更新: {old or '(空)'} -> {addr} (rtt_storage_mode=1)")
        else:
            print("[!] RTT 地址未找到，请重新编译项目后再次运行")
    else:
        print("[!] 未找到 MAP 文件，无法自动获取 RTT 地址")


def _cli_systemview_analyze(project_root: str, port: str | None, duration: float):
    """采集 SystemView 跟踪并打印 RTOS 运行态分析报告。"""
    import mklink
    from mklink.project_config import ensure_rtt_config_updated
    from mklink.systemview_analyzer import analyze_events, format_report

    ensure_rtt_config_updated(project_root)
    # 自动加载 axf（读 SystemCoreClock 做 µs 换算 + 任务名解析需要符号）
    axf = _systemview_symbol_source(project_root)
    print(f"[*] 连接 MKLink（端口: {port or '自动检测'}）…" + (f"  axf={axf}" if axf else "  [WARN] 未找到 axf，将无法换算 µs"))
    try:
        dev = mklink.connect(port=port, project_root=project_root, axf=axf)
    except Exception as e:
        print(f"[FAIL] 连接失败: {e}")
        return
    print("[OK] 连接成功")
    try:
        dev.systemview_start()
    except Exception as e:
        print(f"[FAIL] SystemView 启动失败: {e}")
        dev.close()
        return
    print(f"[*] 采集 {duration}s 跟踪并分析…")
    try:
        result = dev.systemview_read(duration=duration)
        dev.systemview_stop()
        # 任务名解析：直接读 RT-Thread rt_thread.name 字段（不依赖开机 INIT 包）
        ids = list({e["task_id"] for e in result.get("events", []) if "task_id" in e})
        if ids:
            try:
                names = dev.systemview_resolve_task_names(ids)
                if names:
                    for e in result["events"]:
                        if e.get("task_id") in names:
                            e["task_name"] = names[e["task_id"]]
            except Exception:
                pass
    finally:
        try:
            dev.systemview_stop()
        except Exception:
            pass
        dev.close()
    report = analyze_events(result.get("events", []))
    print(format_report(report))


def _cli_systemview_report(
    project_root: str,
    port: str | None,
    duration: float,
    out_path: str,
    no_browser: bool,
):
    """采集 SystemView 并生成自包含 HTML 可视化分析报告。"""
    import mklink
    from pathlib import Path
    from mklink.project_config import ensure_rtt_config_updated
    from mklink.systemview_analyzer import analyze_events
    from mklink.systemview_report import generate_html_report

    ensure_rtt_config_updated(project_root)
    axf = _systemview_symbol_source(project_root)
    print(f"[*] 连接 MKLink（端口: {port or '自动检测'}）…")
    try:
        dev = mklink.connect(port=port, project_root=project_root, axf=axf)
    except Exception as e:
        print(f"[FAIL] 连接失败: {e}")
        return
    print("[OK] 连接成功")
    try:
        dev.systemview_start()
    except Exception as e:
        print(f"[FAIL] SystemView 启动失败: {e}")
        dev.close()
        return
    print(f"[*] 采集 {duration}s 生成报告…")
    events: list = []
    try:
        result = dev.systemview_read(duration=duration)
        events = result.get("events", [])
        dev.systemview_stop()
        # 任务名解析
        ids = list({e["task_id"] for e in events if "task_id" in e})
        if ids:
            try:
                names = dev.systemview_resolve_task_names(ids)
                for e in events:
                    if e.get("task_id") in names:
                        e["task_name"] = names[e["task_id"]]
            except Exception:
                pass
    finally:
        try:
            dev.systemview_stop()
        except Exception:
            pass
        dev.close()

    report = analyze_events(events)
    meta = {"cpu_freq": result.get("cpu_freq") if "result" in dir() else 0}
    html_str = generate_html_report(
        report, events, meta=meta, title=f"SystemView RTOS 报告 — {Path(project_root).name}"
    )
    out = Path(out_path).resolve()
    out.write_text(html_str, encoding="utf-8")
    print(f"\n[OK] 报告已生成: {out}  ({len(events)} 事件, {report['summary'].get('task_count',0)} 任务)")
    if not no_browser:
        try:
            import webbrowser
            webbrowser.open(out.as_uri())
            print("[*] 已在浏览器打开")
        except Exception:
            pass


def _cli_systemview_integrate(project_root: str, sv_dir: str = "segger_systemview"):
    """集成 SEGGER SystemView 到 RT-Thread 项目（克隆 rtt-integrate 思路）。

    复制 SEGGER_SYSVIEW 源到 sv_dir → 注册 Keil 工程 + IncludePath →
    main.c 加 include → 加 USE_SYSTEMVIEW 宏。RT-Thread 启动时自动初始化并
    开始把事件写入 RTT 通道 1。任何步骤失败自动回滚。
    """
    from mklink.systemview_integration import (
        check_systemview_sources_bundled, full_systemview_integrate,
        generate_systemview_usage_example,
    )
    if not check_systemview_sources_bundled():
        print("[FAIL] 技能目录中缺少 SystemView 源文件 (systemview_sources/)")
        return

    print(f"[*] 集成 SystemView 到 {project_root} ...")
    result = full_systemview_integrate(project_root, sv_dir=sv_dir)

    def _step(label, key):
        r = result.get(key)
        if not r:
            return
        ok = r.get("success", r.get("macro_added", False))
        print(f"[{'OK' if ok else 'FAIL'}] {label}")
        for e in r.get("errors", []):
            print(f"       - {e}")

    _step("复制 SystemView 源文件", "copy")
    _step("注册到 Keil 工程 + IncludePath", "keil")
    if result.get("main", {}).get("added"):
        print("[OK] main.c 注入 #include \"SEGGER_SYSVIEW.h\"（USE_SYSTEMVIEW 守卫）")
    _step("添加 USE_SYSTEMVIEW 宏", "macro")

    if result["success"]:
        print("\n[OK] SystemView 集成完成。下一步：重新编译烧录，再运行 "
              "`python -m mklink systemview --duration 10`")
        print(generate_systemview_usage_example())
    else:
        print("\n[FAIL] SystemView 集成未完成：")
        for e in result.get("errors", []):
            print(f"  - {e}")


def _cli_rtt_integrate(
    project_root: str,
    src_dir: str | None,
    inc_dir: str | None,
    force: bool = False,
    static_addr: str | None = None,
):
    """集成 SEGGER RTT 源文件到项目。

    模式 1（默认）：仅动态模式，集成 RTT 后从 MAP/ELF 解析地址。
    模式 2（--static-addr）：一键启用静态编译，包含：
        1. 复制 RTT 源 + 心跳源
        2. 注册到 uvprojx 文件组
        3. 加 #include "SEGGER_RTT.h" + SEGGER_RTT_Init() 到 main.c
        4. 加 USE_RTT 和 MKLINK_RTT_STATIC 宏
        5. 更新 scatter 加 RW_IRAM_RTT 段
        任何步骤失败自动回滚。
    """
    from pathlib import Path
    from mklink.project_config import load_keil_project, save_rtt_config
    from mklink.rtt_integration import (
        check_rtt_in_project, full_rtt_integrate,
        check_rtt_sources_bundled, generate_rtt_usage_example,
    )
    from mklink.rtt_addr import diagnose_rtt_addr, find_rtt_addr_from_map

    if not check_rtt_sources_bundled():
        print("[FAIL] 技能目录中缺少 RTT 源文件 (rtt_sources/)")
        return

    # 确定 src/inc 目录
    root = Path(project_root).resolve()
    if not src_dir or not inc_dir:
        # 尝试 IAR 项目
        from mklink.iar_parser import find_ewp, parse_ewp, resolve_iar_path
        ewp_path = find_ewp(root)
        if ewp_path:
            ewp_info = parse_ewp(ewp_path)
            if ewp_info and ewp_info.get("include_paths"):
                for inc_path in ewp_info["include_paths"]:
                    resolved = resolve_iar_path(ewp_path, inc_path)
                    if Path(resolved).exists() and not inc_dir:
                        inc_dir = resolved
                        break

        # 尝试 Keil 项目
        if not inc_dir:
            keil = load_keil_project(project_root)
            if keil and keil.get("include_paths"):
                uvp_dir = Path(keil["uvprojx_path"]).parent
                for inc_path in keil["include_paths"]:
                    resolved = (uvp_dir / inc_path).resolve()
                    if resolved.exists() and str(resolved).startswith(str(root)):
                        if not inc_dir:
                            inc_dir = str(resolved)
                        break

        # 通用回退：扫描常见头文件目录
        if not inc_dir:
            for candidate in ["inc", "Core/Inc", "User", "App", "include"]:
                candidate_path = root / candidate
                if candidate_path.exists() and any(candidate_path.glob("*.h")):
                    inc_dir = str(candidate_path)
                    break

    if not src_dir:
        src_dir = str(root / "src")
    if not inc_dir:
        inc_dir = str(root / "inc")

    if not Path(inc_dir).exists():
        print(f"[WARN] 头文件目录不存在: {inc_dir}")
        print("       RTT 头文件将被复制到该目录（目录将自动创建）")
        print("       建议确认该目录是否在项目的 Include Path 中")

    print(f"[*] 源文件目录: {src_dir}")
    print(f"[*] 头文件目录: {inc_dir}")

    # 检查当前状态（跳过 force 时）
    if not force:
        status = check_rtt_in_project(src_dir, inc_dir)
        if status["integrated"]:
            print("[OK] RTT 源文件已存在于项目中（使用 --force 强制重新集成）")
            return

    # 静态模式：调用 v2 全自动化函数
    if static_addr:
        print(f"\n[*] 开始 RTT 静态编译模式集成（CB 地址: {static_addr}）...")
        from mklink.rtt_integration import full_rtt_integrate_v2
        result = full_rtt_integrate_v2(
            project_root=project_root,
            static_addr=static_addr,
            src_dir=src_dir,
            inc_dir=inc_dir,
        )
        _print_integration_result_v2(result)
        if not result["success"]:
            print("\n[FAIL] 静态模式集成失败（已自动回滚）")
            return
        # 集成成功后查 RTT 地址写回配置
        _find_and_save_rtt_addr(project_root)
        return

    # 动态模式：调用原 full_rtt_integrate
    print("\n[*] 开始 RTT 集成（动态模式）...")
    result = full_rtt_integrate(
        project_root=project_root,
        uvprojx_path=None,  # 自动查找
        ewp_path=None,     # 自动查找
        src_dir=src_dir,
        inc_dir=inc_dir,
        main_c_path=None,  # 自动查找
    )

    print()
    print("=" * 50)
    print("  RTT 集成结果")
    print("=" * 50)

    # 复制源文件
    copy = result.get("copy")
    if copy:
        if copy["success"]:
            print("\n[1] 复制源文件:")
            for f in copy.get("copied", []):
                print(f"  + {f}")
            for f in copy.get("skipped", []):
                print(f"  ~ {f} (已存在)")
        else:
            print(f"\n[FAIL] 复制源文件失败: {copy.get('errors', [])}")

    # 添加到 IAR 工程
    iar = result.get("iar")
    if iar:
        print(f"\n[2] 添加到 IAR 工程:")
        if iar["success"]:
            print(f"  + 已添加 SEGGER_RTT 文件到 .ewp")
            print(f"  + 工程文件已备份到: {iar.get('backup_path', 'N/A')}")
        else:
            for e in iar.get("errors", []):
                print(f"  ! {e}")

    # 添加到 Keil 工程
    keil = result.get("keil")
    if keil:
        print(f"\n[2] 添加到 Keil 工程:")
        if keil["success"]:
            print(f"  + 已添加 SEGGER_RTT 分组到 .uvprojx")
            print(f"  + 工程文件已备份到: {keil.get('backup_path', 'N/A')}")
        else:
            for e in keil.get("errors", []):
                print(f"  ! {e}")

    # 添加初始化代码
    main_res = result.get("main")
    if main_res:
        print(f"\n[3] 添加初始化代码到 main.c:")
        if main_res["success"]:
            if main_res.get("added_include"):
                print(f"  + 已添加 #ifdef USE_RTT / #include \"SEGGER_RTT.h\" / #endif")
            if main_res.get("added_init"):
                print(f"  + 已添加 USE_RTT 宏保护的 SEGGER_RTT_Init() 调用")
            if main_res.get("verified"):
                print(f"  + 初始化验证通过")
            print(f"  + main.c 已备份到: {main_res.get('backup_path', 'N/A')}")
        else:
            for e in main_res.get("errors", []):
                print(f"  ! {e}")
        for w in main_res.get("warnings", []):
            print(f"  ~ {w}")
    elif result.get("main_error"):
        print(f"\n[3] 添加初始化代码到 main.c:")
        print(f"  ! {result['main_error']}")

    # 添加 USE_RTT 宏
    macro_res = result.get("macro")
    if macro_res:
        print(f"\n[4] 添加 USE_RTT 宏:")
        if macro_res["success"] and macro_res.get("macro_added"):
            print(f"  + 已添加 USE_RTT 到 {macro_res.get('ide_type', '?')} 工程定义")
        elif macro_res["success"] and not macro_res.get("macro_added"):
            print(f"  ~ USE_RTT 宏已存在于 {macro_res.get('ide_type', '?')} 工程定义中，跳过")
        else:
            for e in macro_res.get("errors", []):
                print(f"  ! {e}")

    # 最终结果
    print("\n" + "=" * 50)
    if result.get("success"):
        print("  RTT 集成全部成功")
    else:
        print("  RTT 集成存在失败项，请检查上方输出")
    print("=" * 50)

    # 查找 RTT 地址并更新配置
    keil = load_keil_project(project_root)
    rtt_addr = ""
    if keil and keil.get("map_path"):
        map_path = keil["map_path"]
        print(f"\n[*] 正在从 MAP 文件查找 RTT 地址: {map_path}")
        rtt_result = diagnose_rtt_addr(map_path)
        rtt_addr = rtt_result.addr
        if rtt_addr:
            source = f" ({rtt_result.source})" if rtt_result.source else ""
            print(f"[OK] 找到 _SEGGER_RTT 地址: {rtt_addr}{source}")
        else:
            print("[WARN] 未能解析出 _SEGGER_RTT 地址")
            for detail in rtt_result.details:
                print(f"      - {detail}")
            for warning in rtt_result.warnings:
                print(f"      - {warning}")
            print("      请确保已重新编译项目后运行此命令")

    # 更新 rtt_config
    save_rtt_config(project_root, {
        "integrated": result.get("success", False),
        "rtt_addr": rtt_addr or "",
        "search_size": 1024,
        "channel": 0,
        "autostart": False,
        "rtt_storage_mode": 0,
    })

    if rtt_addr:
        print("\n[OK] RTT 配置已更新到 .mklink/rtt_config.json")

    if result.get("success"):
        print("\n--- 使用示例 ---")
        print(generate_rtt_usage_example())
    elif not rtt_addr:
        print("\n[!] RTT 地址未找到，请重新编译项目后再次运行 `python -m mklink rtt-integrate`")


def _resolve_port(port: str | None) -> str:
    """Resolve a unique passive selection without opening ports or saving config."""
    if port:
        return port
    from mklink.probes import select_probe
    from mklink.runtime import RuntimeErrorResponse
    try:
        return select_probe()['port']
    except RuntimeErrorResponse as error:
        raise SystemExit(str(error)) from error


# ---------------------------------------------------------------------------
# 烧录器版本信息
# ---------------------------------------------------------------------------

import re as _re

# 匹配 "  V4.3.1" 形式的版本号（行首允许空白，版本号严格 V\d+.\d+.\d+）
_VERSION_LINE_RE = _re.compile(r"^\s*(V\d+\.\d+\.\d+)\s*$", _re.MULTILINE)


def _parse_version_response(text: str) -> tuple[str | None, list[str]]:
    """从 cmd.get_version() 响应中解析当前版本与历史。

    Args:
        text: 设备响应的完整文本（已 UTF-8 解码）。

    Returns:
        (current_version, [history_versions]) 元组。
        current_version 为 None 表示未找到版本号。
        history_versions 按时间倒序排列（最新在前）。
    """
    matches = _VERSION_LINE_RE.findall(text)
    if not matches:
        return None, []
    current, *history = matches
    return current, history


def _print_power_read(result: dict, as_json: bool = False) -> int:
    import json

    if as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        for key, label, unit in (("voltage_mv", "VCC", "mV"),
                                 ("current_ma", "Current", "mA"),
                                 ("power_mw", "Power", "mW")):
            value = result[key]
            print(f"{label}: unavailable" if value is None else f"{label}: {value:g} {unit}")
        print(f"Sample age: {result['sample_age_ms']} ms")
        if not result["current_supported"]:
            print("Current/power measurement is not supported by this firmware/hardware.")
    return 0


def _print_probe_version(resp: str, all_history: bool = False, raw: bool = False):
    if raw:
        print(resp.rstrip())
        return

    current, history = _parse_version_response(resp)
    if current is None:
        print("[WARN] 响应中未识别到 V*.*.* 版本号")
        print("      可能是设备固件变更或未处于 PikaScript 交互模式")
        print("      原始响应:")
        print(resp.rstrip())
        return

    print(f"[OK] 烧录器固件版本: {current}")

    if all_history:
        print()
        print("=== 完整版本历史 ===")
        # 从原始响应中按版本号切分段落；只输出以 V*.*.* 起始的段
        # （开头的 "cmd.get_version()"/"使用手册: ..." 不属于版本段，跳过）
        sections = _re.split(r"^\s*(?=V\d+\.\d+\.\d+\s*$)", resp, flags=_re.MULTILINE)
        for section in sections:
            section = section.strip()
            if not section:
                continue
            first_line, _, rest = section.partition("\n")
            first_line = first_line.strip()
            # 防御：非 V*.*.* 起始的段不视为版本段
            if not _re.match(r"^V\d+\.\d+\.\d+$", first_line):
                continue
            print(f"  {first_line}")
            for line in rest.splitlines():
                line = line.rstrip()
                if line:
                    print(f"    {line}")
            print()
    else:
        if history:
            # 打印相邻的最近几个版本作为快速参考
            preview = history[:3]
            print(f"     近期版本: {', '.join(preview)}")
            print(f"     (使用 --all 查看完整变更历史)")

    # 提取并显示文档链接
    doc_match = _re.search(r"https?://\S+", resp)
    if doc_match:
        print(f"     文档: {doc_match.group(0)}")






# ---------------------------------------------------------------------------
# 静默写 RAM（flush_memory，多地址多字节）
# ---------------------------------------------------------------------------

def _parse_flush_item(raw: str) -> tuple[int, list[int]]:
    """解析一项 'ADDR:BYTE,BYTE,...' 字符串。

    接受的字节写法：
      - 逗号分隔 + 0x 前缀： "0x20010000:0x11,0x22,0x33"
      - 逗号分隔无前缀：      "0x20010000:11,22,33"
      - 空格分隔 + 0x 前缀：  "0x20010000:0x11 0x22 0x33"
      - 混合：                "0x20010000:0x11 0x22,0x33"
      - 单字节重复（推荐大块/填充）： "0x20008000:0xAA*12288"
        * 绕开 Windows 命令行长度限制（实测逐字节展开 ≈16KB 即撞墙）；
        * 复用固件 bytes([0xVV])*N 短表达式，命令串极短，单次可写数 KB；
        * count 为十进制；byte 接受 0xAA / AA。

    Returns:
        (addr_int, [byte_int, ...])

    Raises:
        ValueError: 解析失败（含 BYTE*N 与逐字节列表混排）
    """
    if ":" not in raw:
        raise ValueError(f"缺少 ':' 分隔 addr 与 data（格式: ADDR:BYTE,BYTE,... 或 ADDR:BYTE*N）")
    addr_part, data_part = raw.split(":", 1)
    addr_int = int(addr_part.strip(), 16)
    # 同时接受逗号和空格分隔
    tokens = [t for t in data_part.replace(",", " ").split() if t]
    if not tokens:
        raise ValueError(f"data 部分为空（至少 1 字节）")
    # BYTE*N 单字节重复形式：必须是单一 token 且含且仅含一个 '*'
    if any("*" in t for t in tokens):
        if len(tokens) != 1 or tokens[0].count("*") != 1:
            raise ValueError(
                "BYTE*N 形式必须是单一 'BYTE*COUNT'（如 0xAA*12288），"
                "不能与逐字节列表混排"
            )
        byte_spec, _, count_spec = tokens[0].partition("*")
        try:
            byte_val = int(byte_spec, 16)
            count = int(count_spec)
        except ValueError:
            raise ValueError(f"无法解析 BYTE*N: {tokens[0]!r}（byte 用 0x-AA，count 为十进制）")
        if not (0 <= byte_val <= 0xFF):
            raise ValueError(f"BYTE*N 的字节超出 0..0xFF: {byte_spec!r}")
        if not 1 <= count <= 12288:
            raise ValueError(f"BYTE*N count must be 1..12288: {count}")
        return addr_int, [byte_val] * count
    byte_list = [int(t, 16) for t in tokens]
    return addr_int, byte_list


def _parse_dump_region(raw: str) -> tuple[int, int]:
    """Parse one dump-memory region: ADDR:SIZE."""
    if ":" not in raw:
        raise ValueError("expected ADDR:SIZE")
    addr_part, size_part = raw.split(":", 1)
    addr = int(addr_part.strip(), 0)
    size = int(size_part.strip(), 0)
    if addr < 0:
        raise ValueError("address must be >= 0")
    if size <= 0:
        raise ValueError("size must be > 0")
    return addr, size


def _cli_resources(args):
    """Local resource management that does not require FastAPI."""
    import json

    from mklink.local_resources import (
        local_resource_status,
        release_serial_resources,
    )

    command = getattr(args, "resources_command", None)
    if command in (None, "status"):
        result = local_resource_status(port=getattr(args, "port", None))
    elif command in ("release-serial", "release-all"):
        result = release_serial_resources(
            port=getattr(args, "port", None),
            force=getattr(args, "force", False),
        )
    else:
        print("[FAIL] unknown resources subcommand")
        return

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False))
        return

    if command in (None, "status"):
        print("[OK] local resource status")
    else:
        print("[OK] local serial resources checked")

    for item in result.get("serial_locks", []):
        owner = item.get("owner_pid") or "-"
        print(
            f"  serial_port: {item.get('action', 'status')} "
            f"pid={owner} alive={item.get('owner_alive', False)} "
            f"path={item.get('path')}"
        )


def _cli_symbols(
    source: str,
    filter_pattern: str | None,
    *,
    backend: str | None = None,
    project_root: str | None = None,
):
    """Browse RAM object symbols from an ELF/AXF file.

    Usage:
        python -m mklink symbols --source <axf>
        python -m mklink symbols --source <axf> --filter <regex>
    """
    from mklink.elf_backend import list_writable_object_symbols
    try:
        normalized = list_writable_object_symbols(
            source, backend=backend, project_root=project_root
        )
    except Exception as e:
        print(f"[FAIL] {e}")
        return
    symbols = [
        {
            "name": symbol.name,
            "address": f"0x{symbol.address:08x}",
            "size": symbol.size,
        }
        for symbol in normalized
    ]

    if not symbols:
        print("No RAM OBJECT symbols found")
        return

    # Apply filter if specified
    if filter_pattern:
        try:
            import re
            re.compile(filter_pattern)  # Validate regex first
        except re.error as e:
            print(f"[FAIL] Invalid regex pattern: {e}")
            return

        symbols = [
            symbol for symbol in symbols
            if re.search(filter_pattern, symbol["name"])
        ]

        if not symbols:
            print("No matching symbols found")
            return

    # Print table
    # Format: Name  Address  Size
    name_w = max(len(s["name"]) for s in symbols)
    name_w = max(name_w, 4)  # at least "Name" width

    print(f"{'Name':<{name_w}}  {'Address':<12}  {'Size':>4}")
    print(f"{'-' * name_w}  {'-' * 12}  {'-' * 4}")
    for sym in symbols:
        print(f"{sym['name']:<{name_w}}  {sym['address']:<12}  {sym['size']:>4}")


def _default_axf_from_project(project_root: str) -> str | None:
    from mklink.project_config import load_project_info, load_keil_project

    project = load_project_info(project_root) or load_keil_project(project_root)
    if not project:
        return None
    return project.get("axf_path") or project.get("out_path")


def _systemview_symbol_source(project_root: str) -> str | None:
    from pathlib import Path

    configured = _default_axf_from_project(project_root)
    if configured and Path(configured).is_file():
        return str(Path(configured))
    for pattern in ("build/**/*.axf", "**/output/*.elf"):
        candidate = next(Path(project_root).glob(pattern), None)
        if candidate is not None:
            return str(candidate)
    return None


def _project_root_from_args(args) -> str:
    project_root = getattr(args, "project_root", ".")
    positional = getattr(args, "project_root_positional", None)
    return project_root if project_root != "." else positional or "."


def _profile_sizes(project_root: str) -> tuple[int, int]:
    from mklink.project_config import load_config, load_project_info, load_keil_project
    from mklink.profiles import load_mcu_profiles

    flash_size = 0
    ram_size = 0
    project = load_project_info(project_root) or load_keil_project(project_root) or {}
    flash_size = int(project.get("flash_size") or 0)
    ram_size = int(project.get("ram_size") or 0)
    config = load_config(project_root) or {}
    mcu_key = config.get("mcu_key")
    if mcu_key:
        profile = load_mcu_profiles().get(mcu_key, {})
        for region in profile.get("regions", []):
            if region.get("name") == "flash" and not flash_size:
                flash_size = int(str(region.get("size", "0")), 0)
            if region.get("name") == "ram" and not ram_size:
                ram_size = int(str(region.get("size", "0")), 0)
    return flash_size, ram_size




def _cli_typeinfo(args):
    from mklink.typeinfo import run_typeinfo

    args.project_root = _project_root_from_args(args)
    if not args.source:
        args.source = _default_axf_from_project(args.project_root)
    if not args.source:
        print("[FAIL] 请指定 --source 或先运行 project-init")
        return
    try:
        print(run_typeinfo(args))
    except Exception as e:
        print(f"[FAIL] {e}")


def _cli_memmap(args):
    from mklink.memmap import analyze_memmap, format_memmap, format_memmap_json

    project_root = _project_root_from_args(args)
    source = args.source or _default_axf_from_project(project_root)
    if not source:
        print("[FAIL] 请指定 --source 或先运行 project-init")
        return
    flash_size, ram_size = _profile_sizes(project_root)
    try:
        summary = analyze_memmap(
            source,
            flash_size=flash_size,
            ram_size=ram_size,
            backend=getattr(args, "elf_backend", None),
            project_root=project_root,
        )
    except Exception as e:
        print(f"[FAIL] {e}")
        return
    print(format_memmap_json(summary) if args.json else format_memmap(summary))


def _enable_utf8_console():
    """Windows 控制台 UTF-8 模式支持。"""
    import os
    if os.name == "nt":
        import sys
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Modbus RTU CLI 处理函数
# ---------------------------------------------------------------------------

def _modbus_resolve_defaults(args) -> bool:
    """Fill omitted options from the saved port profile, then builtin defaults.

    An explicit port does not inherit another port's saved settings. Explicit
    options always win, including values equal to the builtin defaults.
    """
    config = {}
    saved_port = not args.port
    if saved_port:
        from mklink.project_config import load_config
        config = load_config(".") or {}
        args.port = config.get("modbus_port")
        if not args.port:
            config = {}
    for name, default in [('baud', 9600), ('parity', 'N'), ('stopbits', 1)]:
        if getattr(args, name) is None:
            value = config.get('modbus_' + name)
            setattr(args, name, default if value is None else value)
    if args.port and saved_port:
        print(f"[AUTO] 从配置读取 Modbus 串口: {args.port} @ {args.baud}bps")
    if args.port:
        return True

    print("[FAIL] 未指定 --port 且 config.json 中无 modbus_port 配置")
    print("  用法: python -m mklink modbus read --port COM8 --slave 1 --fc 3 --start 0 --quantity 10")
    print("  配置后会自动记住串口参数，后续无需再指定 --port")
    return False


def _modbus_save_config(args):
    """Modbus 通信成功后，将串口参数持久化到 config.json。"""
    from mklink.project_config import load_config, save_config
    config = load_config(".")
    if config is None:
        config = {}
    updated = False
    for key, val in [("modbus_port", args.port), ("modbus_baud", args.baud),
                     ("modbus_parity", args.parity), ("modbus_stopbits", args.stopbits)]:
        if config.get(key) != val:
            config[key] = val
            updated = True
    if updated:
        save_config(".", config)


@contextmanager
def _shared_uart_client(args, stream, settings, *, after_stop=None):
    """Subscribe to the existing UART owner; release only this CLI's ownership."""
    from mklink.runtime import RuntimeClient, RuntimeErrorResponse
    client = RuntimeClient(kind='cli', name=f'{stream.title()} CLI')
    created = False
    try:
        client.connect(scope='uart', probe=getattr(args, 'probe', None))
        if client.call(f'{stream}_status')['running']:
            client.call(f'{stream}_start', {})
        else:
            client.call(f'{stream}_start', settings)
            created = True
        yield client
    finally:
        operation_error = sys.exc_info()[1]
        cleanup_errors = []
        try:
            if created:
                try:
                    client.call(f'{stream}_stop')
                except BaseException as exc:
                    if isinstance(exc, RuntimeErrorResponse) and exc.status_code == 409:
                        print('[INFO] 未取得停止权限，保留连接；可在后台管理中显式停止。')
                    else:
                        cleanup_errors.append(exc)
            if after_stop is not None and operation_error is None and not cleanup_errors:
                try:
                    after_stop(client)
                except BaseException as exc:
                    cleanup_errors.append(exc)
        finally:
            try:
                client.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
        if cleanup_errors:
            if operation_error is None:
                raise cleanup_errors[0]
            for error in cleanup_errors:
                print(f'[WARN] {stream.title()} 会话清理失败，请检查共享后台: {error}', file=sys.stderr)


@contextmanager
def _modbus_shared_client(args, *, scan=False):
    from mklink.runtime import RuntimeErrorResponse
    from mklink.usb_interfaces import canonical_serial_port
    if not _modbus_resolve_defaults(args):
        raise ValueError('Modbus port is required')
    connection = {'port': canonical_serial_port(args.port), 'baudrate': args.baud,
                  'bytesize': 8, 'parity': args.parity, 'stopbits': args.stopbits}
    if not scan:
        for key in ('timeout', 'retries'):
            value = getattr(args, key, None)
            if value is not None:
                connection[key] = value
    settings = {'timeout': .15 if scan else 1.0, 'retries': 0, **connection, 'registers': []}
    with _shared_uart_client(args, 'modbus', settings) as client:
        # Compare after subscribing, while shared stop/reconfiguration is refused.
        actual = client.call('modbus_status')['connection']
        if any(actual.get(key) != value for key, value in connection.items()):
            raise RuntimeErrorResponse('Existing Modbus connection uses different port/settings; stop it explicitly before changing settings')
        yield client


def _cli_modbus_scan(args):
    from mklink.modbus._scanner import scan_slaves, validate_scan_range
    validate_scan_range(args.start, args.end)
    with _modbus_shared_client(args, scan=True) as client:
        print(f"[*] Modbus 从站扫描: {args.port} @ {args.baud}bps (地址 {args.start}-{args.end})")

        def on_progress(current, total, msg):
            pct = current * 100 // total
            status = f" {msg}" if msg else ""
            print(f"\r  [{pct:3d}%] {current}/{total}{status}", end="", flush=True)

        found = scan_slaves(
            lambda slave, register: client.call('modbus_probe', {'slave': slave, 'address': register}),
            start_addr=args.start, end_addr=args.end, on_progress=on_progress,
        )
        print()
        if found:
            print(f"[OK] 发现 {len(found)} 个从站: {', '.join(str(a) for a in found)}")
            _modbus_save_config(args)
        else:
            print("[WARN] 未发现任何从站")


def _cli_modbus_read(args):
    from mklink.modbus._session import validate_slave, validate_transaction
    validate_slave(args.slave)
    validate_transaction(args.fc, args.start, quantity=args.quantity)
    with _modbus_shared_client(args) as client:
        result = client.call('modbus_transaction', {'fc': args.fc, 'start': args.start,
                             'quantity': args.quantity, 'slave': args.slave})
        label = {1: '线圈', 2: '离散输入', 3: '保持寄存器', 4: '输入寄存器'}[args.fc]
        print(f"[OK] FC{args.fc:02d} 读 {args.quantity} 个{label} (从站 {args.slave}, 地址 {args.start}):")
        formatter = _fmt_on_off if args.fc in (1, 2) else _fmt_val
        for i, value in enumerate(result['values']):
            print(f"  {args.start + i:>6}: {formatter(value, args.format)}")
        _modbus_save_config(args)


def _cli_modbus_write(args):
    from mklink.modbus._session import validate_slave, validate_transaction
    validate_slave(args.slave)
    parse = _parse_bool if args.fc in (5, 15) else lambda value: int(value, 0)
    values = [parse(value) for value in args.values]
    validate_transaction(args.fc, args.start, values=values)
    with _modbus_shared_client(args) as client:
        client.call('modbus_transaction', {'fc': args.fc, 'start': args.start,
                    'values': values, 'slave': args.slave})
        if args.fc == 5:
            print(f"[OK] FC05 写单个线圈 (从站 {args.slave}, 地址 {args.start}): {'ON' if values[0] else 'OFF'}")
        elif args.fc == 6:
            print(f"[OK] FC06 写单个寄存器 (从站 {args.slave}, 地址 {args.start}): {values[0]} (0x{values[0]:04X})")
        else:
            label = '线圈' if args.fc == 15 else '寄存器'
            print(f"[OK] FC{args.fc:02d} 写 {len(values)} 个{label} (从站 {args.slave}, 地址 {args.start})")
        _modbus_save_config(args)


def _cli_modbus_poll(args):
    from mklink.modbus._poller import poll_registers, validate_poll
    from mklink.modbus._format import parse_register_spec
    from mklink.modbus._session import validate_slave
    validate_slave(args.slave)
    specs = parse_register_spec(args.registers)
    for spec in specs:
        spec.register_type = args.register_type
    validate_poll(specs, args.interval, args.count)
    with _modbus_shared_client(args) as client:
        poll_registers(
            lambda fc, address, quantity: client.call('modbus_transaction',
                {'fc': fc, 'start': address, 'quantity': quantity, 'slave': args.slave})['values'],
            slave=args.slave, specs=specs, interval=args.interval, fmt=args.format, count=args.count,
        )


def _cli_modbus_monitor(args):
    from contextlib import nullcontext
    from mklink.modbus._monitor import monitor_traffic, validate_monitor
    from mklink.modbus._session import validate_slave
    validate_slave(args.slave)
    validate_monitor(args.interval, args.output_format, args.count)
    # Fail on an invalid log destination before attaching or opening a UART.
    with (open(args.save, 'w', encoding='utf-8') if args.save else nullcontext()) as output:
        with _modbus_shared_client(args) as client:
            monitor_traffic(client.call, slave=args.slave, interval=args.interval,
                            output_format=args.output_format, count=args.count,
                            output=output, passive=args.passive)


def _cli_modbus_diag(args):
    from mklink.modbus._session import validate_slave, validate_transaction

    slave = validate_slave(args.slave)
    supplied = {name: getattr(args, name, None) for name in
                ('addr', 'and_mask', 'or_mask', 'write_addr', 'write_values', 'read_count')}
    allowed = {'exception-status': set(), 'mask-write': {'addr', 'and_mask', 'or_mask'},
               'read-write': {'addr', 'write_addr', 'write_values', 'read_count'}}
    if args.subfunc not in allowed:
        raise ValueError('Unsupported Modbus diagnostic function')
    unused = [name for name, value in supplied.items() if value is not None and name not in allowed[args.subfunc]]
    if unused:
        raise ValueError('Arguments not used by this diagnostic function: ' + ', '.join(unused))
    address = supplied['addr'] if supplied['addr'] is not None else 0
    if args.subfunc == 'exception-status':
        params = {'fc': 7}
    elif args.subfunc == 'mask-write':
        params = {'fc': 22, 'start': address,
                  'and_mask': supplied['and_mask'] if supplied['and_mask'] is not None else 0xFFFF,
                  'or_mask': supplied['or_mask'] if supplied['or_mask'] is not None else 0}
    else:
        params = {'fc': 23, 'start': address,
                  'write_start': supplied['write_addr'] if supplied['write_addr'] is not None else address,
                  'quantity': supplied['read_count'] if supplied['read_count'] is not None else 10,
                  'values': supplied['write_values']}
    validate_transaction(**params)
    with _modbus_shared_client(args) as client:
        result = client.call('modbus_transaction', {'slave': slave, **params})
    if params['fc'] == 7:
        status = result['status']
        print(f"[OK] FC07 异常状态 (从站 {slave}): 0x{status:02X} (二进制: {status:08b})")
    elif params['fc'] == 22:
        print(f"[OK] FC22 掩码写寄存器 (从站 {slave}, 地址 {address}):")
        print(f"  AND=0x{params['and_mask']:04X}, OR=0x{params['or_mask']:04X}")
    else:
        print(f"[OK] FC23 读写多寄存器 (从站 {slave}, 读地址 {address}, 写地址 {params['write_start']}):")
        for i, value in enumerate(result['values']):
            print(f"  {address + i:>6}: {value} (0x{value:04X})")


def _cli_modbus_dashboard(args):
    """启动 Modbus Web 可视化仪表盘。"""
    from mklink.modbus._profile import load_profile
    from mklink.modbus._dashboard import run_modbus_dashboard

    from mklink.modbus._session import validate_slave
    from mklink.modbus._registers import validate_poll_interval

    profile = load_profile(getattr(args, "profile", None))
    slave = validate_slave(getattr(args, "slave", 1))
    fast_interval = validate_poll_interval(profile.get("poll_groups", {}).get("fast", {}).get("interval", 1.0))
    slow_interval = validate_poll_interval(profile.get("poll_groups", {}).get("slow", {}).get("interval", 5.0))
    with _modbus_shared_client(args) as client:
        run_modbus_dashboard(
            client=client,
            slave=slave,
            profile=profile,
            host=args.host if hasattr(args, "host") else "127.0.0.1",
            port=args.port_http if hasattr(args, "port_http") else 0,
            no_browser=args.no_browser if hasattr(args, "no_browser") else False,
            max_points=args.max_points if hasattr(args, "max_points") else 500,
            fast_interval=fast_interval,
            slow_interval=slow_interval,
            duration=args.duration if hasattr(args, "duration") else 0,
            html_path=getattr(args, "html", None),
            allow_arbitrary_writes=getattr(args, "allow_arbitrary_writes", False),
        )


def _cli_modbus_pointmap_detect(args):
    """Detect a Modbus point table without writing generated files."""
    import json
    from mklink.modbus._pointmap import detect_pointmap

    pointmap = detect_pointmap(
        project_root=getattr(args, "project_root", "."),
        source=getattr(args, "source", None),
        fmt=getattr(args, "format", "auto"),
    )
    if getattr(args, "json", False):
        print(json.dumps(pointmap.to_jsonable(), ensure_ascii=False, indent=2))
        return

    summary = pointmap.summary()
    print("[OK] Modbus point table detection")
    print(f"  Source:   {summary['source_format']}")
    print(f"  Files:    {', '.join(summary['source_files']) if summary['source_files'] else 'none'}")
    print(f"  Points:   {summary['points']}")
    print(f"  Writable: {summary['writable']}")
    print(f"  Bits:     {summary['bitfields']}")
    print(f"  Commands: {summary['commands']}")
    for warning in summary.get("warnings", []):
        print(f"  [WARN] {warning}")


def _cli_modbus_pointmap_generate(args):
    """Generate dashboard profile and Markdown docs from a detected point table."""
    from pathlib import Path
    from mklink.modbus._pointmap import detect_pointmap, generate_pointmap_artifacts

    project_root = Path(getattr(args, "project_root", "."))
    output = Path(getattr(args, "output", None) or project_root / ".mklink" / "modbus_profile.json")
    doc = Path(getattr(args, "doc", None) or project_root / "docs" / "modbus_pointmap.md")
    pointmap = detect_pointmap(
        project_root=project_root,
        source=getattr(args, "source", None),
        fmt=getattr(args, "format", "auto"),
    )
    summary = pointmap.summary()
    print("[INFO] Modbus point table summary")
    print(f"  Source:   {summary['source_format']}")
    print(f"  Files:    {', '.join(summary['source_files']) if summary['source_files'] else 'none'}")
    print(f"  Points:   {summary['points']}")
    print(f"  Writable: {summary['writable']}")
    print(f"  Commands: {summary['commands']}")
    for warning in summary.get("warnings", []):
        print(f"  [WARN] {warning}")

    if not getattr(args, "yes", False):
        answer = input(f"Write {output} and {doc}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("[CANCEL] Generation cancelled")
            return

    profile_path, doc_path = generate_pointmap_artifacts(pointmap, output, doc)
    print(f"[OK] Wrote profile: {profile_path}")
    print(f"[OK] Wrote document: {doc_path}")


def _cli_modbus_dispatch(args):
    """分发 modbus 子命令。"""
    if not hasattr(args, "modbus_command") or not args.modbus_command:
        from mklink.cli import _get_modbus_parser_help
        _get_modbus_parser_help()
        return
    dispatch = {
        "scan": _cli_modbus_scan,
        "read": _cli_modbus_read,
        "write": _cli_modbus_write,
        "poll": _cli_modbus_poll,
        "monitor": _cli_modbus_monitor,
        "diag": _cli_modbus_diag,
        "dashboard": _cli_modbus_dashboard,
        "pointmap": lambda ns: _cli_modbus_pointmap_detect(ns)
        if getattr(ns, "pointmap_command", None) == "detect"
        else _cli_modbus_pointmap_generate(ns)
        if getattr(ns, "pointmap_command", None) == "generate"
        else print("Usage: python -m mklink modbus pointmap <detect|generate> [options]"),
    }
    handler = dispatch.get(args.modbus_command)
    if handler:
        from mklink.runtime import RuntimeErrorResponse
        try:
            handler(args)
        except (OSError, ValueError, RuntimeErrorResponse) as error:
            raise SystemExit(str(error)) from error
    else:
        print("用法: python -m mklink modbus <scan|read|write|poll|monitor|diag|dashboard> [选项]")


def _get_modbus_parser_help():
    """打印 modbus 帮助信息。"""
    print("用法: python -m mklink modbus <命令> [选项]")
    print()
    print("Modbus RTU 调试命令:")
    print("  scan      扫描从站地址 (1-247)")
    print("  read      读取寄存器/线圈 (FC01-04)")
    print("  write     写入寄存器/线圈 (FC05/06/15/16)")
    print("  poll      实时轮询寄存器（表格刷新）")
    print("  monitor   监控通信流量")
    print("  diag      诊断功能 (FC07/22/23)")
    print("  dashboard Web 可视化仪表盘（实时图表 + 交互控制）")
    print()
    print("示例:")
    print("  python -m mklink modbus scan --port COM7")
    print("  python -m mklink modbus read --port COM7 --slave 1 --fc 3 --start 0 --quantity 10")
    print("  python -m mklink modbus write --port COM7 --slave 1 --fc 6 --start 0 100")
    print("  python -m mklink modbus poll --port COM7 --slave 1 --registers \"0:uint16:Temp 1:float\"")
    print("  python -m mklink modbus dashboard --port COM7 --slave 1 --baud 57600")


def _fmt_val(v: int, fmt: str) -> str:
    """格式化寄存器值。"""
    if fmt == "hex":
        return f"0x{v:04X}"
    elif fmt == "bin":
        return f"{v:016b}"
    else:
        return str(v)


def _fmt_on_off(b: bool, fmt: str) -> str:
    """格式化线圈/离散输入值。"""
    if fmt == "hex":
        return "0xFF00" if b else "0x0000"
    return "ON" if b else "OFF"


def _parse_bool(s: str) -> bool:
    """解析布尔值字符串。"""
    value = s.strip().lower()
    if value in ("1", "on", "true", "yes", "0xff00"):
        return True
    if value in ("0", "off", "false", "no", "0x0000"):
        return False
    raise ValueError(f"Invalid coil value: {s!r}; use on/off, true/false, yes/no, 1/0 or 0xff00/0x0000")


def _serial_connection(args, *, port=None):
    from mklink.usb_interfaces import canonical_serial_port
    if type(args.baud) is not int or not 1 <= args.baud <= 4000000:
        raise ValueError('Baud rate must be an integer in 1..4000000')
    if type(args.databits) is not int or args.databits not in (5, 6, 7, 8):
        raise ValueError('Data bits must be 5, 6, 7 or 8')
    if type(args.stop) is not int or args.stop not in (1, 2) or args.parity not in ('N', 'E', 'O'):
        raise ValueError('Stop bits must be 1 or 2; parity must be N, E or O')
    return {'port': canonical_serial_port(args.port if port is None else port), 'baudrate': args.baud,
                  'databits': args.databits, 'stopbits': args.stop, 'parity': args.parity}


def _require_serial_connection(status, connection):
    from mklink.runtime import RuntimeErrorResponse
    actual = next((item for item in status['config'] if item['port'] == connection['port']), None)
    if actual is None or any(actual.get(key, default) != connection[key] for key, default in
                            (('baudrate', 115200), ('databits', 8), ('stopbits', 1), ('parity', 'N'))):
        raise RuntimeErrorResponse('Existing serial connection uses different port/settings; stop it explicitly before changing settings')


def _cli_serial_send(args):
    import math
    import time
    from mklink.runtime import RuntimeErrorResponse

    if type(args.count) is not int or args.count < 1:
        raise ValueError('Send count must be a positive integer')
    if (isinstance(args.delay, bool) or not isinstance(args.delay, (int, float))
            or not math.isfinite(args.delay) or not 0 <= args.delay <= 3600):
        raise ValueError('Send delay must be finite and in 0..3600 seconds')
    connection = _serial_connection(args)
    data = bytes.fromhex(args.send_data) if args.hex else args.send_data.encode('utf-8')
    if not data:
        raise ValueError('Send data must not be empty')
    with _shared_uart_client(args, 'serial', {'ports': [connection]}) as client:
        _require_serial_connection(client.call('serial_status'), connection)
        for index in range(args.count):
            result = client.call('serial_send', {'port': connection['port'], 'data': data.hex(), 'hex': True})
            if result.get('ok') is not True:
                raise RuntimeErrorResponse('Serial send was not acknowledged; result unknown, do not retry')
            print(f"[TX] #{index + 1}/{args.count}: {data.hex(' ') if args.hex else args.send_data}", flush=True)
            if index + 1 < args.count:
                time.sleep(args.delay)


def _cli_serial_log(args):
    _cli_serial_capture(args, monitor=False)


def _cli_serial_monitor(args):
    _cli_serial_capture(args, monitor=True)


def _cli_serial_open(args):
    _cli_serial_capture(args, monitor=True, interactive=True)


def _cli_serial_capture(args, *, monitor, interactive=False):
    import math
    from pathlib import Path
    from mklink.serial._profile import load_profile, ProfileError
    from mklink.serial._frame import FrameParser
    from mklink.serial._logger import FileLogger
    from mklink.serial._capture import SerialCapture
    from mklink.serial._console_monitor import ConsoleMonitor

    selected = args.port if monitor and not interactive else [args.port]
    connections = [_serial_connection(args, port=port) for port in selected]
    if not 1 <= len(connections) <= 16 or len({item['port'] for item in connections}) != len(connections):
        raise ValueError('Select 1..16 distinct UART ports')
    if (isinstance(args.duration, bool) or not isinstance(args.duration, (int, float))
            or not math.isfinite(args.duration) or args.duration < 0):
        raise ValueError('Capture duration must be finite and nonnegative; zero means until interrupted')
    try:
        profile = load_profile(args.profile) if args.profile else None
        parsers = {item['port']: FrameParser(profile, max_buffer_bytes=1024 * 1024) if profile else None
                   for item in connections}
    except ProfileError as error:
        raise ValueError(str(error)) from error
    automation = None
    if interactive and args.auto_reply is not None:
        import json
        from dataclasses import asdict
        from mklink.serial._autoreply import load_rules_from_file
        rules = [asdict(rule) for rule in load_rules_from_file(args.auto_reply)]
        automation = {'profile': profile, 'rules': rules}
        settings = {'ports': connections, 'profile': profile, 'auto_reply_rules': rules}
        if len(json.dumps(settings)) > 16384:
            raise ValueError('Serial automation configuration exceeds the shared 16 KiB request limit')
    else:
        settings = {'ports': connections}
    output_name = args.log if monitor else args.output
    logger, output = None, None
    if output_name:
        output = Path(output_name).expanduser().resolve()
        if not output.parent.is_dir() or (output.exists() and not output.is_file()):
            raise ValueError('Log output must be a file in an existing directory')
        if args.profile and output == Path(args.profile).expanduser().resolve():
            raise ValueError('Log output must not overwrite its Profile')
        if interactive and args.auto_reply and output == Path(args.auto_reply).expanduser().resolve():
            raise ValueError('Log output must not overwrite auto-reply rules')
        log_format = getattr(args, 'format', None) or ('csv' if output.suffix.lower() == '.csv' else 'txt')
        logger = FileLogger(str(output), format=log_format)
    elif not monitor:
        raise ValueError('Log output is required')
    sink = ConsoleMonitor(args.mode, args.filter, logger) if monitor else logger
    if interactive:
        from mklink.serial._terminal import SerialTerminal
        from mklink.runtime import RuntimeErrorResponse
        def send(data):
            result = client.call('serial_send', {'port': connections[0]['port'], 'data': data.hex(), 'hex': True})
            if result.get('ok') is not True:
                raise RuntimeErrorResponse('Serial send was not acknowledged; result unknown, do not retry')
            print(f"[OK] 已发送 {len(data)} 字节到 {connections[0]['port']}", flush=True)
        terminal = SerialTerminal(send, sink)
    capture = None
    def finish(client):
        if capture is not None:
            capture.drain()
            if monitor:
                sink.finish()
    try:
        with _shared_uart_client(args, 'serial', settings, after_stop=finish) as client:
            status = client.call('serial_status')
            for connection in connections:
                _require_serial_connection(status, connection)
            if automation is not None and status.get('automation') != automation:
                raise ValueError('Existing serial automation differs; stop it explicitly before changing rules/Profile')
            capture = SerialCapture(client, parsers, sink)
            if logger is not None:
                logger.start()
            if interactive:
                with terminal:
                    print('[OK] 共享终端：Ctrl+C/Ctrl+Q 或 >quit 退出；>hex、>file、>mode、>filter', flush=True)
                    capture.run(args.duration, on_poll=terminal.poll)
            elif monitor:
                print(f"[OK] 被动监听: {', '.join(parsers)} (Ctrl+C 停止)", flush=True)
                capture.run(args.duration, on_poll=sink.tick)
            else:
                print(f'[OK] 日志记录中: {output} (Ctrl+C 停止)', flush=True)
                capture.run(args.duration)
    except BaseException:
        if logger is not None:
            try:
                logger.close()
            except OSError as error:
                print(f'[WARN] Log close failed: {error}', file=sys.stderr)
        raise
    else:
        if logger is not None:
            logger.close()
    print(f'[OK] 日志已保存: {output}' if output else '[OK] 终端已结束' if interactive else '[OK] 监听已结束', flush=True)


def _cli_serial_dispatch(args):
    """串口调试命令分发。"""
    if getattr(args, 'serial_command', None) in ('send', 'log', 'monitor', 'open'):
        from mklink.runtime import RuntimeErrorResponse
        try:
            {'send': _cli_serial_send, 'log': _cli_serial_log, 'monitor': _cli_serial_monitor, 'open': _cli_serial_open}[args.serial_command](args)
        except (OSError, ValueError, RuntimeErrorResponse) as error:
            raise SystemExit(str(error)) from error
        return
    from mklink.serial._port import list_uart_ports, is_mklink_port
    from mklink.serial._profile import load_profile, find_profile, ProfileError
    from mklink.serial._monitor import SerialMonitor
    from mklink.serial._logger import FileLogger
    from mklink.serial._dashboard import SerialDashboardServer
    from mklink.serial._profile_from_c import generate_profile_from_c

    cmd = getattr(args, "serial_command", None)
    if not cmd:
        print("用法: python -m mklink serial <命令> [选项]")
        print()
        print("串口调试命令:")
        print("  list       列出可用 UART 端口")
        print("  open       交互式串口终端")
        print("  send       发送数据后退出")
        print("  monitor    多端口被动监听")
        print("  log        无头模式日志记录")
        print("  dashboard  Web 可视化 Dashboard")
        print("  profile    Profile 管理")
        print()
        print("示例:")
        print("  python -m mklink serial list")
        print("  python -m mklink serial open --port COM3 --baud 115200")
        print("  python -m mklink serial send --port COM3 --hex 01030000000A")
        print("  python -m mklink serial monitor --port COM3 --port COM4")
        print("  python -m mklink serial dashboard --port COM3 --profile frame.json")
        return

    if cmd == "list":
        ports = list_uart_ports()
        if not ports:
            print("[*] 未发现可用 UART 端口")
            return
        print(f"[OK] 发现 {len(ports)} 个 UART 端口:")
        for p in ports:
            tag = " [MKLink]" if p.get("is_mklink") else ""
            print(f"  {p['device']} — {p['description']}{tag}")

    elif cmd == "dashboard":
        profile = None
        if args.profile:
            try:
                profile = load_profile(args.profile)
            except ProfileError as e:
                print(f"[FAIL] Profile 加载失败: {e}")
                return

        port_configs = [{"port": p, "baudrate": args.baud, "databits": args.databits,
                         "stopbits": args.stop, "parity": args.parity} for p in args.port]

        monitor = SerialMonitor(ports=port_configs, profile=profile)

        dashboard = SerialDashboardServer(
            monitor=monitor,
            host=args.host,
            port=args.port_http,
            open_browser=not args.no_browser,
        )

        try:
            monitor.start()
            dashboard.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            dashboard.stop()
            monitor.stop()

    elif cmd == "profile":
        pcmd = getattr(args, "profile_command", None)
        if pcmd == "detect":
            try:
                profile = generate_profile_from_c(args.source, struct_name=args.struct)
                import json
                print(json.dumps(profile, indent=2, ensure_ascii=False))
            except (ValueError, FileNotFoundError) as e:
                print(f"[FAIL] {e}")
        elif pcmd == "generate":
            try:
                profile = generate_profile_from_c(args.source, struct_name=args.struct)
                from mklink.serial._profile import save_profile
                output = args.output or ".mklink/serial_profile.json"
                import os
                os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
                save_profile(profile, output)
                print(f"[OK] Profile 已生成: {output}")
            except (ValueError, FileNotFoundError) as e:
                print(f"[FAIL] {e}")
        elif pcmd == "show":
            import json
            path = args.profile or find_profile(".")
            if not path:
                print("[FAIL] 未找到 Profile 文件")
                return
            try:
                profile = load_profile(path)
                print(f"Profile: {path}")
                print(json.dumps(profile, indent=2, ensure_ascii=False))
            except ProfileError as e:
                print(f"[FAIL] {e}")
        else:
            print("[FAIL] 请指定 profile 子命令: detect, generate, show")
    else:
        print("[FAIL] 未知的 serial 子命令，使用 --help 查看帮助")


# --- CPU Debug Control CLI handlers ---




def _cli_gui(args):
    """Open the selected shared CDC backend."""
    import webbrowser
    from mklink.runtime import RuntimeClient, browser_url, ensure_runtime
    if args.host != "127.0.0.1":
        raise SystemExit("Shared GUI binds only 127.0.0.1")
    info = ensure_runtime(project_root=args.project_root, port=args.port, probe=args.probe,
                          device_port=args.device_port, allow_lobby=True)
    if args.device_port or args.axf:
        client = RuntimeClient(info=info)
        client.connect(project_root=args.project_root if args.project_root != "." else None, port=args.device_port, axf=args.axf)
        client.close()
    url = browser_url(info)
    print(f"[MKLink] Shared CDC runtime: http://127.0.0.1:{info['port']}")
    print("[MKLink] Closing the GUI leaves the shared runtime running. Stop with: mklink runtime stop --confirm")
    if not args.no_browser:
        webbrowser.open(url)
    return


def _cli_web_entry(args):
    """Install or operate the cross-platform HTML Web entry point."""
    import json
    from pathlib import Path
    from mklink.web_entry import (
        WebEntryError,
        handle_protocol_uri,
        install_quick_launcher,
        install_protocol,
        start_web_entry,
        stop_web_entry,
        uninstall_protocol,
        web_entry_status,
        write_launcher_html,
    )

    try:
        if args.web_entry_command == "install":
            result = install_quick_launcher() if args.quick_launch else install_protocol()
            if args.html:
                result["html"] = str(write_launcher_html(Path(args.html)).resolve())
        elif args.web_entry_command == "uninstall":
            result = uninstall_protocol()
        elif args.web_entry_command == "html":
            output = write_launcher_html(Path(args.output)).resolve()
            result = {"status": "created", "html": str(output)}
        elif args.web_entry_command == "start":
            browser_open = (lambda _url: None) if args.no_browser else None
            result = (
                start_web_entry(browser_open=browser_open)
                if browser_open is not None else start_web_entry()
            )
        elif args.web_entry_command == "stop":
            result = stop_web_entry()
        elif args.web_entry_command == "status":
            result = web_entry_status()
        elif args.web_entry_command == "handle":
            result = handle_protocol_uri(args.uri)
        else:
            raise WebEntryError("Missing web-entry command")
    except WebEntryError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc
    print(json.dumps(result, ensure_ascii=False))


def _cli_serve(args):
    """启动远程调试服务器。"""
    from mklink._deps import require_gui_dependencies
    backend = getattr(args, "backend", "fastapi")
    if backend == "fastapi":
        require_gui_dependencies()
        if getattr(args, "desktop_instance_id", None):
            from mklink.runtime_proxy import serve_desktop_proxy
            serve_desktop_proxy(args)
            return
        from mklink.remote.api import create_app, run_server
        app = create_app(
            auth_token=args.token,
            project_root=args.project_root,
            desktop_instance_id=args.desktop_instance_id,
        )
        print(f"[MKLink] Starting FastAPI server on {args.host}:{args.port}")
        print(f"[MKLink] Backend: fastapi | Auth: {'enabled' if args.token else 'disabled'}")
        print(f"[MKLink] API docs: http://{args.host}:{args.port}/docs")
        run_server(
            app, host=args.host, port=args.port,
            device_port=args.device_port, axf=args.axf,
            project_root=args.project_root,
            desktop_port_end=args.desktop_port_end,
            desktop_runtime_info=args.desktop_runtime_info,
            desktop_instance_id=args.desktop_instance_id,
        )
    else:
        from mklink.remote.server import serve
        serve(
            host=args.host, port=args.port,
            auth_token=args.token,
            device_port=args.device_port, axf=args.axf,
        )


def _cli_mcp(args):
    """Start the shared-backend MCP adapter."""
    from mklink.runtime_mcp import run
    run()


def _cli_runtime(args):
    import json
    from mklink.runtime import RuntimeClient, RuntimeErrorResponse, ensure_runtime, request, running_runtimes, selected_runtime, serve_runtime
    try:
        if args.runtime_command == "serve":
            serve_runtime(project_root=args.project_root, port=args.port, probe_id=args.probe_id)
            return
        if args.runtime_command == "start":
            info = ensure_runtime(project_root=args.project_root, port=args.port, probe=args.probe, device_port=args.device_port)
            result = request(info, "GET", "/_runtime/status")
        elif args.runtime_command == "status":
            result = [request(info, "GET", "/_runtime/status") for info in running_runtimes()]
        elif args.runtime_command == 'jobs':
            info = selected_runtime(args.probe)
            if info is None:
                raise RuntimeErrorResponse('Selected backend is not running')
            from mklink.runtime import job_status
            result = job_status(info, args.job)
        elif args.runtime_command == "stop":
            if not args.confirm:
                raise RuntimeErrorResponse("Stopping the shared backend requires --confirm")
            info = selected_runtime(args.probe)
            result = request(info, "POST", "/_runtime/stop", {"confirm": True}) if info else {"status": "not_running"}
        else:
            client = RuntimeClient(project_root=args.project_root or ".", kind='cli', name='CLI runtime call')
            try:
                client.connect(project_root=args.project_root, probe=args.probe, port=args.device_port, axf=args.axf)
                result = client.call(args.capability, json.loads(args.arguments))
            finally:
                client.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeErrorResponse, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


def _print_mcu_detect_result(result: dict, *, json_output: bool = False) -> None:
    if json_output:
        import json

        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    status = result.get("status")
    if status in ("created", "matched"):
        prefix = "[OK]" if status == "matched" else "[AUTO]"
        print(f"{prefix} MCU profile: {result.get('profile_key')} ({result.get('device')})")
        selected = result.get("selected_algorithm") or {}
        if selected:
            print(f"  FLM: {selected.get('name')}")
        if result.get("flm_source"):
            print(f"  FLM source: {result.get('flm_source')}")
        if result.get("microkeen_flm"):
            copied = " (已拷贝)" if result.get("flm_copied") else ""
            print(f"  MICROKEEN: {result.get('microkeen_flm')}{copied}")
        if result.get("profile_written"):
            print(f"  profile: {result.get('profile_path')}")
            if result.get("backup_path"):
                print(f"  backup:  {result.get('backup_path')}")
        return

    if status == "needs_selection":
        print("[WARN] 发现多个内部 Flash 算法:")
        for i, candidate in enumerate(result.get("candidates", []), 1):
            print(f"  {i}. {candidate.get('name')} (size={candidate.get('size')})")
        print("请用 --flm <CMSIS/Flash/xxx.FLM> 指定后重试。")
        return

    print(f"[FAIL] {result.get('message', status)}")


def _cli_mcu_detect(
    project_root: str,
    device: str | None,
    port: str | None,
    flm: str | None,
    json_output: bool,
):
    """发现/固化 MCU profile 和 FLM。"""
    from mklink.mcu_detect import detect_mcu_profile

    result = detect_mcu_profile(
        project_root=project_root,
        device=device,
        port=port,
        flm=flm,
        write_profile=True,
        copy_flm=True,
        read_idcode=bool(port),
    )

    if result.get("status") == "needs_selection" and not json_output and sys.stdin.isatty():
        candidates = result.get("candidates", [])
        for i, candidate in enumerate(candidates, 1):
            print(f"  {i}. {candidate.get('name')} (size={candidate.get('size')})")
        try:
            choice = input("选择 FLM 编号并固化（留空取消）: ").strip()
        except EOFError:
            choice = ""
        if choice:
            try:
                selected = candidates[int(choice) - 1]["name"]
            except (ValueError, IndexError, KeyError):
                print("[FAIL] 无效选择")
                return
            result = detect_mcu_profile(
                project_root=project_root,
                device=device,
                port=port,
                flm=selected,
                write_profile=True,
                copy_flm=True,
                read_idcode=bool(port),
            )

    _print_mcu_detect_result(result, json_output=json_output)


def main():
    """CLI 入口，首先执行依赖检查。"""
    # Keep the direct-site CLI isolated in its owning module.  Early routing
    # also lets ``mklink remote --help`` render the complete remote parser.
    if len(sys.argv) > 1 and sys.argv[1] == "remote":
        from mklink.remote.cli import main as remote_main

        return remote_main(sys.argv[2:])

    # Windows 控制台 UTF-8 支持
    _enable_utf8_console()

    # 第一步：依赖预检
    require_dependencies()

    # 延迟导入（依赖检查通过后再导入 pyserial 相关模块）
    from mklink.rtt_addr import diagnose_rtt_addr, find_rtt_addr_from_map
    from mklink.autostart import generate_autostart_config

    parser = argparse.ArgumentParser(
        prog="mklink",
        description="MKLink Flash Programmer CLI",
    )
    subparsers = parser.add_subparsers(dest="command")
    from mklink.peripheral_cli import add_parser as add_peripheral_parser

    add_peripheral_parser(subparsers)
    speed_parser = subparsers.add_parser("debug-speed", help="Set low=4 MHz / medium=10 MHz / high=20 MHz / ultra=30 MHz debug timing")
    speed_parser.add_argument("profile", choices=("low", "medium", "high", "ultra"))
    speed_parser.add_argument("--port", default=None)
    speed_parser.add_argument("--project-root", default=None)
    speed_parser.add_argument("--save", dest="persist_profile", action="store_true", help="Save this profile in the shared backend's project for future connections")
    measure_parser = subparsers.add_parser("dump-benchmark", help="Measure periodic mem_dump without a waveform GUI")
    measure_parser.add_argument("regions", nargs="+")
    measure_parser.add_argument("--speed", choices=("low", "medium", "high", "ultra"), default=None)
    measure_parser.add_argument("--port", default=None)
    measure_parser.add_argument("--project-root", default=None)
    measure_parser.add_argument("--duration", type=float, default=3.0)
    measure_parser.add_argument("--period", type=float, default=0.000001)
    config_parser = subparsers.add_parser(
        "configuration",
        help="Inspect option bytes/OTP and generate option configuration scripts",
    )
    config_parser.add_argument("action", choices=("describe", "read", "generate"))
    config_parser.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE")
    config_parser.add_argument("--chip", required=True)
    config_parser.add_argument("--model", choices=("V2", "V3", "V4"), default="V4")
    config_parser.add_argument("--port")
    config_parser.add_argument("--project-root", default=None)
    config_parser.add_argument("--probe", help="共享后台下载器 ID 或别名")

    subparsers.add_parser(
        "remote",
        add_help=False,
        help="manage and use direct VPN/LAN field sites",
    )

    # rtt-find 子命令
    rtt_parser = subparsers.add_parser("rtt-find", help="从 map/elf 查找 RTT 地址")
    rtt_parser.add_argument("path", help=".map 或 .elf 文件路径")

    # autostart 子命令
    auto_parser = subparsers.add_parser("autostart", help="生成上电自动启动 RTT 配置")
    auto_parser.add_argument("--addr", required=True)
    auto_parser.add_argument("--size", type=int, default=1024)
    auto_parser.add_argument("--channel", type=int, default=0)

    def _add_project_root_arg(parser):
        """为子命令添加 project-root 参数（同时支持选项和位置参数）。"""
        parser.add_argument("--project-root", default=".", help="项目根目录")
        parser.add_argument("project_root_positional", nargs="?", default=None, help="项目根目录（位置参数，等同于 --project-root）")

    def _add_elf_backend_arg(parser):
        parser.add_argument(
            "--elf-backend",
            choices=("builtin", "external"),
            help="ELF/DWARF 解析后端（默认 builtin）",
        )

    def _resolve_project_root(args):
        """从参数中解析 project_root，优先使用位置参数。"""
        return args.project_root if args.project_root != "." else args.project_root_positional or "."

    # keil-parse 子命令
    keil_parser_cmd = subparsers.add_parser("keil-parse", help="解析 Keil .uvprojx 工程文件")
    _add_project_root_arg(keil_parser_cmd)

    # iar-parse 子命令
    iar_parser_cmd = subparsers.add_parser("iar-parse", help="解析 IAR .ewp 工程文件")
    _add_project_root_arg(iar_parser_cmd)

    # project-init 子命令
    init_parser = subparsers.add_parser("project-init", help="离线初始化精简工程配置（Keil/IAR/HPM；不探测硬件）")
    _add_project_root_arg(init_parser)

    # mcu-detect 子命令
    mcu_detect_parser = subparsers.add_parser("mcu-detect", help="发现/固化未知 MCU profile 与 FLM")
    _add_project_root_arg(mcu_detect_parser)
    mcu_detect_parser.add_argument("--device", default=None, help="MCU 型号，如 STM32H723ZETx")
    mcu_detect_parser.add_argument("--port", default=None, help="可选：连接目标读取 IDCODE")
    mcu_detect_parser.add_argument("--flm", default=None, help="指定要固化的 PDSC 算法路径")
    mcu_detect_parser.add_argument("--json", action="store_true", help="输出 JSON")

    # project-info 子命令
    info_parser = subparsers.add_parser("project-info", help="显示项目已缓存的配置")
    _add_project_root_arg(info_parser)

    # rtt-integrate 子命令
    rtt_int_parser = subparsers.add_parser("rtt-integrate", help="集成 SEGGER RTT 源文件到项目")
    _add_project_root_arg(rtt_int_parser)
    rtt_int_parser.add_argument("--src-dir", help="源文件目录（默认自动检测）")
    rtt_int_parser.add_argument("--inc-dir", help="头文件目录（默认自动检测）")
    rtt_int_parser.add_argument("--force", action="store_true", help="强制重新集成（即使已集成）")
    rtt_int_parser.add_argument(
        "--static-addr",
        help="启用 RTT 静态编译模式，指定 CB 绝对地址（如 0x2001F000）。"
             "自动完成：复制 RTT+心跳源、注册文件组、加 USE_RTT/MKLINK_RTT_STATIC 宏、"
             "更新 scatter 加 RW_IRAM_RTT 段。任何步骤失败自动回滚。"
    )

    # systemview-integrate 子命令（RTOS 跟踪集成）
    sv_int_parser = subparsers.add_parser(
        "systemview-integrate",
        help="集成 SEGGER SystemView 到 RT-Thread 项目（RTOS 跟踪，跑在 RTT 通道 1）",
    )
    _add_project_root_arg(sv_int_parser)
    sv_int_parser.add_argument(
        "--sv-dir", default="segger_systemview",
        help="SystemView 源文件存放目录（默认 segger_systemview）",
    )

    # copy-flm 子命令
    copy_flm_parser = subparsers.add_parser("copy-flm", help="拷贝 FLM 文件到 MICROKEEN 磁盘")
    _add_project_root_arg(copy_flm_parser)

    # flash 子命令（一站式烧录）
    flash_parser = subparsers.add_parser("flash", help="一站式烧录（自动连接 → IDCODE → FLM → 烧录）")
    _add_project_root_arg(flash_parser)
    flash_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    flash_parser.add_argument("--hex", help="HEX 文件路径（默认从 .mklink/ 配置读取）")

    # rtt 子命令（一站式 RTT 捕获）
    rtt_cmd_parser = subparsers.add_parser("rtt", help="一站式 RTT 捕获（自动连接 → 启动 RTT → 读取输出）")
    _add_project_root_arg(rtt_cmd_parser)
    rtt_cmd_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    rtt_cmd_parser.add_argument("--duration", type=float, default=10.0, help="读取时长（秒，默认 10）")
    # --visualize 及相关选项
    rtt_cmd_parser.add_argument("--visualize", action="store_true", help="启用 Web RAW 终端模式")
    rtt_cmd_parser.add_argument("--host", default="127.0.0.1", help="HTTP 服务器绑定地址（默认 127.0.0.1）")
    rtt_cmd_parser.add_argument("--port-http", type=int, default=0, help="HTTP 服务器端口（默认 0 = 随机）")
    rtt_cmd_parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    rtt_cmd_parser.add_argument("--source", help="ELF/AXF path accepted for HIL smoke compatibility")

    # systemview 子命令（RTOS 跟踪：RTT 通道 1 → SEGGER 事件解码）
    sv_parser = subparsers.add_parser(
        "systemview",
        help="SystemView RTOS 跟踪（RTT 通道 1 → 解码任务切换/ISR/CPU 占用）",
    )
    _add_project_root_arg(sv_parser)
    sv_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    sv_parser.add_argument("--duration", type=float, default=10.0, help="读取时长（秒，默认 10）")
    sv_parser.add_argument("--channel", type=int, default=1, help="SystemView 上行通道（SEGGER 默认 1）")
    sv_parser.add_argument("--addr", help="RTT 控制块地址（默认从 rtt_config.json 读）")
    sv_parser.add_argument("--visualize", action="store_true", help="提示用 mklink gui 查看可视化")

    # systemview-analyze 子命令（采集 + RTOS 运行态分析报告）
    sv_an_parser = subparsers.add_parser(
        "systemview-analyze",
        help="采集 SystemView 并打印 RTOS 运行态分析（CPU%%/切换/ISR/异常）",
    )
    _add_project_root_arg(sv_an_parser)
    sv_an_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    sv_an_parser.add_argument("--duration", type=float, default=6.0, help="采集时长（秒，默认 6）")

    # systemview-report 子命令（生成 HTML 可视化分析报告）
    sv_rep_parser = subparsers.add_parser(
        "systemview-report",
        help="采集 SystemView 并生成自包含 HTML 可视化分析报告",
    )
    _add_project_root_arg(sv_rep_parser)
    sv_rep_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    sv_rep_parser.add_argument("--duration", type=float, default=6.0, help="采集时长（秒，默认 6）")
    sv_rep_parser.add_argument("--out", default="systemview_report.html", help="输出 HTML 路径")
    sv_rep_parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    # read-ram 子命令
    read_ram_parser = subparsers.add_parser("read-ram", help="读取目标芯片 RAM 数据")
    read_ram_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    read_ram_parser.add_argument("--addr", required=True, help="读取地址（如 0x20000000）")
    read_ram_parser.add_argument("--size", type=int, default=256, help="读取字节数（默认 256）")
    read_ram_parser.add_argument("--save", help="保存到设备文件（如 ram.bin）")

    power_parser = subparsers.add_parser(
        "power-read", help="只读获取下载器 VCC 实测电压、电流和计算功率"
    )
    power_parser.add_argument("--port", help="命令串口（默认自动检测）")
    power_parser.add_argument("--json", action="store_true", help="输出 JSON，单位 mV/mA/mW")

    # version 子命令
    version_parser = subparsers.add_parser(
        "version", help="读取烧录器自身固件版本（cmd.get_version）"
    )
    version_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    version_parser.add_argument(
        "--all", action="store_true", help="显示完整版本历史（默认仅显示当前版本）"
    )
    version_parser.add_argument(
        "--raw", action="store_true", help="输出设备原始响应（不解析）"
    )

    # read-reg 子命令
    read_reg_parser = subparsers.add_parser("read-reg", help="读取内存映射寄存器（复用 cmd.read_ram）")
    read_reg_parser.add_argument("register", nargs="?", help="寄存器名（如 SCB.CFSR）")
    read_reg_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    read_reg_parser.add_argument("--addr", help="寄存器地址（如 0xE000ED28）")
    read_reg_parser.add_argument("--width", type=int, choices=[8, 16, 32], default=32, help="位宽（默认 32）")
    read_reg_parser.add_argument("--count", type=int, default=1, help="连续读取数量（默认 1）")
    read_reg_parser.add_argument("--format", choices=["hex", "dec", "bin", "both"], default="both", help="显示格式")
    read_reg_parser.add_argument("--raw", action="store_true", help="输出解码后的十六进制字节（共享后台）")
    read_reg_parser.add_argument("--project-root", default=".")
    read_reg_parser.add_argument("--svd")
    read_reg_parser.add_argument("--chip")
    read_reg_parser.add_argument("--target-id")

    # write-ram 子命令
    write_ram_parser = subparsers.add_parser("write-ram", help="写入数据到目标芯片 RAM 并回读验证")
    write_ram_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    write_ram_parser.add_argument("--addr", required=True, help="写入地址（如 0x20001000）")
    write_ram_parser.add_argument("data", nargs="+", help="待写入的字节（如 0xDE 0xAD 0xBE 0xEF）")

    # flush-memory 子命令（静默写 RAM，多地址多字节）
    # 调用的 PikaScript 函数: cmd.flush_memory([(addr, bytes([...])), ...])
    dump_memory_parser = subparsers.add_parser(
        "dump-memory",
        aliases=["dump"],
        help="读取 dump_memory 二进制帧（公共高速内存 dump；默认采集 1 个样本）",
    )
    dump_memory_parser.add_argument("--port", help="共享后台 CMD 端口")
    dump_memory_parser.add_argument("--project-root", default=None)
    dump_memory_parser.add_argument("--speed", choices=("low", "medium", "high", "ultra"), default=None,
                                    help="显式改变当前共享速度；省略保持后台速度")
    dump_memory_parser.add_argument(
        "regions",
        nargs="+",
        help="内存区域 ADDR:SIZE；最多 15 组，例如 0x20000000:16 0x20001000:4",
    )
    dump_memory_parser.add_argument(
        "--period",
        type=float,
        default=0.0,
        help="dump_memory 采样周期秒；0=单次样本",
    )
    dump_memory_parser.add_argument(
        "--frames",
        type=int,
        default=1,
        help="采集完整样本数量；0=仅按 --duration 限制",
    )
    dump_memory_parser.add_argument(
        "--duration",
        type=float,
        default=2.0,
        help="首个完整样本后的最长采集秒数；0按数量但最多300s，结果上限16MiB JSON",
    )
    dump_memory_parser.add_argument("--save", help="保存 region payload 到本地二进制文件")
    dump_memory_parser.add_argument("--json", action="store_true", help="采集完成后输出完整样本 JSON")

    flush_memory_parser = subparsers.add_parser(
        "flush-memory",
        help="静默写 RAM（cmd.flush_memory，多地址多字节；不得与流式采集并发）",
    )
    _add_project_root_arg(flush_memory_parser)
    flush_memory_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    flush_memory_parser.add_argument(
        "items", nargs="+",
        help='写入项，格式 "ADDR:BYTE,BYTE,..."，可传多项\n'
             '  字节接受 0x11 / 11，逗号或空格分隔\n'
             '  例: 0x20010000:0x11,0x22,0x33  0x20010100:0x44,0x55,0x66,0x77\n'
             '  单字节重复（清零/填 0xFF/大块填充）用 ADDR:BYTE*N：\n'
             '       0x20008000:0xAA*12288  （绕开 Windows 命令行长度限制）',
    )
    flush_memory_parser.add_argument(
        "--verify", action=argparse.BooleanOptionalAction, default=True, help="默认逐批回读校验；--no-verify 仅确认固件响应"
    )
    flush_memory_parser.add_argument(
        "--repeat", type=int, default=1, help="连续写 N 次（默认 1）"
    )
    flush_memory_parser.add_argument(
        "--interval-ms", type=int, default=0, help="每次写之间的间隔（毫秒，默认 0）"
    )

    # read-flash 子命令
    read_flash_parser = subparsers.add_parser("read-flash", help="通过共享后台读取映射 Flash 快照（1..4096 字节）")
    _add_project_root_arg(read_flash_parser)
    read_flash_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    read_flash_parser.add_argument("--addr", default="0x08000000", help="读取地址（默认 0x08000000）")
    read_flash_parser.add_argument("--size", type=int, default=128, help="读取字节数（默认 128）")
    read_flash_parser.add_argument("--save", help="不再支持写下载器文件；使用共享 Python SDK 保存到主机")

    # vofa 子命令
    vofa_parser = subparsers.add_parser("vofa", help="共享 VOFA 波形采集或订阅，复用后台二进制流")
    vofa_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    vofa_parser.add_argument("--period", type=float, default=None, help="采样周期秒；新采集默认 0.001，订阅时不可改动")
    vofa_parser.add_argument("--visualize", action="store_true", help="启动 Web 可视化仪表盘")
    vofa_parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    vofa_parser.add_argument("--duration", type=float, default=30.0, help="可视化运行时长（秒，默认 30）")
    vofa_parser.add_argument("--names", help="通道名称，逗号分隔（如 ntc_temp,comp_coeff）")
    vofa_parser.add_argument("--source", help="ELF/AXF 文件路径，用于变量名/struct.field 解析")
    vofa_parser.add_argument("--project-root", default=None, help="项目根目录")
    _add_elf_backend_arg(vofa_parser)
    vofa_parser.add_argument("variables", nargs="*", help="变量列表: 地址 类型 地址 类型 ...（如 0x20000030 uint8_t 0x2000154c float）")

    # symbols 子命令（符号浏览器）
    symbols_parser = subparsers.add_parser("symbols", help="Browse symbols from ELF/AXF file")
    symbols_parser.add_argument("--source", required=True, help="ELF/AXF file path")
    symbols_parser.add_argument("--filter", default=None, help="Regex pattern to filter symbol names")
    symbols_parser.add_argument("--project-root", default=".", help="项目根目录")
    _add_elf_backend_arg(symbols_parser)

    # hardfault 子命令
    hardfault_parser = subparsers.add_parser("hardfault", help="读取并解码 Cortex-M HardFault 寄存器/栈帧")
    hardfault_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    hardfault_parser.add_argument("--source", help="ELF/AXF 文件路径，用于 addr2line")
    hardfault_parser.add_argument("--sp", help="异常栈帧地址（MSP/PSP 值）；未指定时只读 Fault 寄存器")
    hardfault_parser.add_argument("--project-root", default=".", help="项目根目录")
    _add_elf_backend_arg(hardfault_parser)

    # typeinfo 子命令
    typeinfo_parser = subparsers.add_parser("typeinfo", help="查询 AXF DWARF 类型信息")
    _add_project_root_arg(typeinfo_parser)
    _add_elf_backend_arg(typeinfo_parser)
    typeinfo_parser.add_argument("--source", help="ELF/AXF 文件路径")
    typeinfo_parser.add_argument("--var", help="变量名")
    typeinfo_parser.add_argument("--struct", help="结构体名")
    typeinfo_parser.add_argument("--enum", help="枚举名")
    typeinfo_parser.add_argument("--list-structs", action="store_true", help="列出结构体")
    typeinfo_parser.add_argument("--list-enums", action="store_true", help="列出枚举")
    typeinfo_parser.add_argument("--json", action="store_true", help="JSON 输出")

    # memmap 子命令
    memmap_parser = subparsers.add_parser("memmap", help="分析 AXF 段表和 RAM/Flash 占用")
    _add_project_root_arg(memmap_parser)
    _add_elf_backend_arg(memmap_parser)
    memmap_parser.add_argument("--source", help="ELF/AXF 文件路径")
    memmap_parser.add_argument("--top", type=int, default=0, help="预留：显示前 N 个大符号")
    memmap_parser.add_argument("--json", action="store_true", help="JSON 输出")

    # watch 子命令
    watch_parser = subparsers.add_parser("watch", help="读取变量快照，支持 DWARF 类型解码")
    watch_parser.add_argument("--project-root", default=None, help="项目根目录")
    watch_parser.add_argument("variables", nargs="*", help="变量名，支持逗号分隔和 struct.field")
    watch_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    watch_parser.add_argument("--source", help="ELF/AXF 文件路径")
    watch_parser.add_argument("--period", type=float, default=0.0, help="周期刷新秒数；0 表示单次读取")
    watch_parser.add_argument("--profile", help="watch profile JSON，格式: {\"variables\": [...]}")
    watch_parser.add_argument("--json", action="store_true", help="JSON 输出")
    _add_elf_backend_arg(watch_parser)

    # ---- Modbus RTU 子命令组 ----
    superwatch_parser = subparsers.add_parser("superwatch", help="SuperWatch dump_memory binary-stream viewer")
    superwatch_parser.add_argument("variables", nargs="*", help="variables, struct.field paths, or registers")
    superwatch_parser.add_argument("--project-root", default=None, help="project root")
    superwatch_parser.add_argument("--port", help="COM port")
    superwatch_parser.add_argument("--source", help="ELF/AXF path for DWARF variable resolution")
    superwatch_parser.add_argument(
        "--svd",
        help="CMSIS-SVD path; otherwise restore the project peripheral selection",
    )
    superwatch_parser.add_argument("--chip", help="Exact installed Pack chip name")
    superwatch_parser.add_argument(
        "--target-id", help="Unambiguous installed peripheral target ID"
    )
    superwatch_parser.add_argument("--period", type=float, default=0.001,
        help="sampling period in seconds (default: 0.001)")
    superwatch_parser.add_argument("--visualize", action="store_true", help="start Web visualizer")
    superwatch_parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    superwatch_parser.add_argument("--port-http", type=int, default=0, help="HTTP port, 0=random")
    superwatch_parser.add_argument("--no-browser", action="store_true", help="do not open browser")
    superwatch_parser.add_argument("--max-points", type=int, default=500, help="maximum chart points")
    superwatch_parser.add_argument("--duration", type=float, default=30.0, help="run duration seconds; 0=forever")
    superwatch_parser.add_argument("--dump-mem", action="store_true",
        help="compatibility flag; SuperWatch always uses dump_memory binary streaming")
    _add_elf_backend_arg(superwatch_parser)

    modbus_parser = subparsers.add_parser(
        "modbus", help="Modbus RTU 调试（扫描、读写、轮询、监控）"
    )
    modbus_sub = modbus_parser.add_subparsers(dest="modbus_command")

    def _add_modbus_serial_args(p, *, scan=False, shared=False):
        """添加 Modbus 共用串口参数。"""
        p.add_argument("--port", default=None, help="Modbus 串口（如 COM8）；未指定时从 config.json 读取 modbus_port")
        p.add_argument("--baud", type=int, default=None, help="波特率（使用保存端口时读取配置，否则默认 9600）")
        p.add_argument("--parity", choices=["N", "E", "O"], default=None, help="校验位（使用保存端口时读取配置，否则默认 N）")
        p.add_argument("--stopbits", type=int, choices=[1, 2], default=None, help="停止位（使用保存端口时读取配置，否则默认 1）")
        if scan or shared:
            p.add_argument('--probe', help='共享后台的下载器身份/别名')
        if not scan:
            p.add_argument("--timeout", type=float, default=None if shared else 1.0,
                           help="响应超时秒数（共享时沿用连接，新连接默认 1.0）" if shared else "响应超时秒数（默认 1.0）")
            p.add_argument("--retries", type=int, default=None if shared else 3,
                           help="协议重试次数（共享时沿用连接，新连接默认 0；写入可能重复发送）" if shared else "超时重试次数（默认 3）")

    # modbus scan
    modbus_scan = modbus_sub.add_parser("scan", help="扫描 Modbus 从站地址")
    _add_modbus_serial_args(modbus_scan, scan=True)
    modbus_scan.add_argument("--start", type=int, default=1, help="起始地址（默认 1）")
    modbus_scan.add_argument("--end", type=int, default=247, help="结束地址（默认 247）")

    # modbus read
    modbus_read = modbus_sub.add_parser("read", help="读取寄存器/线圈")
    _add_modbus_serial_args(modbus_read, shared=True)
    modbus_read.add_argument("--slave", type=int, required=True, help="从站地址 (1-247)")
    modbus_read.add_argument("--fc", type=int, required=True, choices=[1, 2, 3, 4],
                             help="功能码: 1=线圈 2=离散输入 3=保持寄存器 4=输入寄存器")
    modbus_read.add_argument("--start", type=int, required=True, help="起始地址")
    modbus_read.add_argument("--quantity", type=int, default=1, help="数量（默认 1）")
    modbus_read.add_argument("--format", choices=["dec", "hex", "bin", "float"], default="dec",
                             help="显示格式（默认 dec）")

    # modbus write
    modbus_write = modbus_sub.add_parser("write", help="写入寄存器/线圈")
    _add_modbus_serial_args(modbus_write, shared=True)
    modbus_write.add_argument("--slave", type=int, required=True, help="从站地址 (1-247)")
    modbus_write.add_argument("--fc", type=int, required=True, choices=[5, 6, 15, 16],
                              help="功能码: 5=单线圈 6=单寄存器 15=多线圈 16=多寄存器")
    modbus_write.add_argument("--start", type=int, required=True, help="起始地址")
    modbus_write.add_argument("values", nargs="+", help="写入值（如 100 或 0x64）")

    # modbus poll
    modbus_poll = modbus_sub.add_parser("poll", help="轮询寄存器（实时表格）")
    _add_modbus_serial_args(modbus_poll, shared=True)
    modbus_poll.add_argument("--slave", type=int, required=True, help="从站地址 (1-247)")
    modbus_poll.add_argument("--registers", required=True,
                             help="寄存器列表: 地址:类型[:名称] 空格分隔（如 0:uint16:Temp 1:float）")
    modbus_poll.add_argument("--register-type", choices=["holding", "input"], default="holding",
                             help="寄存器区域：holding=FC03，input=FC04（默认 holding）")
    modbus_poll.add_argument("--interval", type=float, default=1.0, help="轮询间隔秒数（默认 1.0）")
    modbus_poll.add_argument("--format", choices=["dec", "hex", "bin", "float"], default="dec",
                             help="显示格式（默认 dec）")
    modbus_poll.add_argument("--count", type=int, default=None, help="轮询次数（默认无限，Ctrl+C 停止）")

    # modbus monitor
    modbus_monitor = modbus_sub.add_parser("monitor", help="监控 Modbus 通信流量")
    _add_modbus_serial_args(modbus_monitor, shared=True)
    modbus_monitor.add_argument("--slave", type=int, default=1, help="主动探测从站；记录共享连接全部流量（默认 1）")
    modbus_monitor.add_argument("--interval", type=float, default=2.0, help="探测/读取历史间隔秒数（默认 2.0）")
    modbus_monitor.add_argument("--output-format", choices=["decoded", "hex", "both"], default="decoded",
                                help="输出格式（默认 decoded）")
    modbus_monitor.add_argument("--save", help="逐条写入 UTF-8 日志（覆盖已有文件）")
    modbus_monitor.add_argument("--passive", action="store_true", help="只观察共享流量，不发送 FC03 探测")
    modbus_monitor.add_argument("--count", type=int, help="探测/历史读取轮数，默认持续监控")

    # modbus diag
    modbus_diag = modbus_sub.add_parser("diag", help="Modbus 诊断（FC07/22/23，共享后台）")
    _add_modbus_serial_args(modbus_diag, shared=True)
    modbus_diag.add_argument("--slave", type=int, required=True, help="从站地址 (1-247)")
    modbus_diag.add_argument("--subfunc", choices=["exception-status", "mask-write", "read-write"],
                             default="exception-status", help="诊断功能（默认 exception-status）")
    modbus_diag.add_argument("--addr", type=int, default=None, help="寄存器/读地址（mask-write/read-write 用，默认 0）")
    modbus_diag.add_argument("--and-mask", type=lambda x: int(x, 0), default=None, help="AND 掩码（默认 0xFFFF）")
    modbus_diag.add_argument("--or-mask", type=lambda x: int(x, 0), default=None, help="OR 掩码（默认 0x0000）")
    modbus_diag.add_argument("--write-addr", type=int, default=None, help="FC23 写地址（默认与 --addr 相同）")
    modbus_diag.add_argument("--write-values", type=lambda x: [int(v.strip(), 0) for v in x.split(",")],
                             default=None, help="写入值，逗号分隔（read-write 用）")
    modbus_diag.add_argument("--read-count", type=int, default=None, help="读取数量（read-write 用，默认 10）")

    # modbus dashboard
    modbus_dashboard = modbus_sub.add_parser("dashboard", help="Web 可视化仪表盘（实时图表 + 交互控制）")
    _add_modbus_serial_args(modbus_dashboard, shared=True)
    modbus_dashboard.add_argument("--slave", type=int, default=1, help="从站地址（默认 1）")
    modbus_dashboard.add_argument("--profile", default=None, help="寄存器配置文件路径（默认自动加载）")
    modbus_dashboard.add_argument("--host", default="127.0.0.1", help="HTTP 绑定地址（默认 127.0.0.1）")
    modbus_dashboard.add_argument("--port-http", type=int, default=0, help="HTTP 端口（默认随机）")
    modbus_dashboard.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    modbus_dashboard.add_argument("--max-points", type=int, default=500, help="图表最大数据点（默认 500）")
    modbus_dashboard.add_argument("--duration", type=float, default=0, help="运行时长秒（默认无限，Ctrl+C 停止）")
    modbus_dashboard.add_argument("--html", default=None, help="自定义仪表盘 HTML 文件路径（默认从 .mklink/modbus_dashboard.html 加载）")

    modbus_dashboard.add_argument("--allow-arbitrary-writes", action="store_true",
                                  help="Allow dashboard debug writes outside profile-writable addresses")

    # modbus pointmap
    modbus_pointmap = modbus_sub.add_parser("pointmap", help="Detect or generate Modbus point-table profile/docs")
    pointmap_sub = modbus_pointmap.add_subparsers(dest="pointmap_command")
    pm_detect = pointmap_sub.add_parser("detect", help="Detect point table without writing files")
    pm_detect.add_argument("--project-root", default=".", help="Project root")
    pm_detect.add_argument("--source", default=None, help="Explicit C/Markdown/CSV source file")
    pm_detect.add_argument("--format", choices=["auto", "c", "markdown", "csv"], default="auto")
    pm_detect.add_argument("--json", action="store_true", help="Print JSON detection result")
    pm_generate = pointmap_sub.add_parser("generate", help="Generate .mklink/modbus_profile.json and docs")
    pm_generate.add_argument("--project-root", default=".", help="Project root")
    pm_generate.add_argument("--source", default=None, help="Explicit C/Markdown/CSV source file")
    pm_generate.add_argument("--format", choices=["auto", "c", "markdown", "csv"], default="auto")
    pm_generate.add_argument("--output", default=None, help="Profile output path")
    pm_generate.add_argument("--doc", default=None, help="Markdown documentation output path")
    pm_generate.add_argument("--yes", action="store_true", help="Write files without prompting")

    # local resource management (no FastAPI required)
    resources_parser = subparsers.add_parser(
        "resources",
        aliases=["resource"],
        help="Local resource management (serial lock cleanup; no FastAPI required)",
    )
    resources_sub = resources_parser.add_subparsers(dest="resources_command")

    resources_status = resources_sub.add_parser(
        "status", help="Show local serial/MKLink resource lock status"
    )
    resources_status.add_argument("--port", default=None, help="Optional serial port, e.g. COM3")
    resources_status.add_argument("--json", action="store_true", help="Print JSON")

    resources_release_serial = resources_sub.add_parser(
        "release-serial",
        help="Release stale local serial resources without starting FastAPI",
    )
    resources_release_serial.add_argument("--port", default=None, help="Optional serial port, e.g. COM3")
    resources_release_serial.add_argument(
        "--force",
        action="store_true",
        help="Terminate a live owner process recorded in mklink lock files",
    )
    resources_release_serial.add_argument("--json", action="store_true", help="Print JSON")

    resources_release_all = resources_sub.add_parser(
        "release-all",
        help="Release stale local serial resources for all known mklink locks",
    )
    resources_release_all.add_argument("--port", default=None, help="Optional serial port, e.g. COM3")
    resources_release_all.add_argument(
        "--force",
        action="store_true",
        help="Terminate live owner processes recorded in mklink lock files",
    )
    resources_release_all.add_argument("--json", action="store_true", help="Print JSON")

    # ─── serial 串口调试 ───────────────────────────────────────────────
    serial_parser = subparsers.add_parser(
        "serial", help="通用串口调试（收发、监控、Dashboard）"
    )
    serial_sub = serial_parser.add_subparsers(dest="serial_command")

    def _add_serial_port_args(p, multi=False):
        """添加串口调试共用参数。"""
        if multi:
            p.add_argument("--port", action="append", required=True, help="串口号（可多次指定）")
        else:
            p.add_argument("--port", required=True, help="串口号（如 COM3）")
        p.add_argument("--baud", type=int, default=115200, help="波特率（默认 115200）")
        p.add_argument("--databits", type=int, choices=[5, 6, 7, 8], default=8, help="数据位（默认 8）")
        p.add_argument("--stop", type=int, choices=[1, 2], default=1, help="停止位（默认 1）")
        p.add_argument("--parity", choices=["N", "E", "O"], default="N", help="校验位（默认 N）")

    # serial list
    serial_sub.add_parser("list", help="列出可用 UART 端口")

    # serial open
    serial_open = serial_sub.add_parser("open", help="交互式串口终端")
    _add_serial_port_args(serial_open)
    serial_open.add_argument("--mode", choices=["ascii", "hex"], default="ascii", help="显示模式")
    serial_open.add_argument("--profile", default=None, help="协议 Profile 文件路径")
    serial_open.add_argument("--filter", default=None, help="过滤正则表达式")
    serial_open.add_argument("--log", default=None, help="日志输出文件路径")
    serial_open.add_argument("--auto-reply", default=None, help="自动应答规则文件路径")

    serial_open.add_argument('--probe', default=None, help='选择共享后台探针身份或别名')
    serial_open.add_argument('--duration', type=float, default=0, help='终端秒数，0 为直到退出或输入 EOF')

    # serial send
    serial_send = serial_sub.add_parser("send", help="发送数据后退出")
    _add_serial_port_args(serial_send)
    serial_send.add_argument("--probe", default=None, help="选择共享后台的探针身份或别名")
    serial_send.add_argument("send_data", help="要发送的数据")
    serial_send.add_argument("--hex", action="store_true", help="以 HEX 格式发送")
    serial_send.add_argument("--count", type=int, default=1, help="发送次数（默认 1）")
    serial_send.add_argument("--delay", type=float, default=1.0, help="多次发送间隔秒数（默认 1.0）")

    # serial monitor
    serial_monitor = serial_sub.add_parser("monitor", help="多端口被动监听")
    _add_serial_port_args(serial_monitor, multi=True)
    serial_monitor.add_argument('--probe', default=None, help='选择共享后台的探针身份或别名')
    serial_monitor.add_argument('--duration', type=float, default=0, help='监听秒数，0 为直到 Ctrl+C')
    serial_monitor.add_argument("--mode", choices=["ascii", "hex"], default="ascii", help="显示模式")
    serial_monitor.add_argument("--profile", default=None, help="协议 Profile 文件路径")
    serial_monitor.add_argument("--filter", default=None, help="过滤正则表达式")
    serial_monitor.add_argument("--log", default=None, help="日志输出文件路径")

    # serial log
    serial_log = serial_sub.add_parser("log", help="无头模式日志记录")
    _add_serial_port_args(serial_log)
    serial_log.add_argument('--probe', default=None, help='共享后台探针 ID/序列号/别名')
    serial_log.add_argument("--output", required=True, help="输出文件路径")
    serial_log.add_argument("--format", choices=["txt", "csv"], default=None, help="日志格式（默认按扩展名）")
    serial_log.add_argument("--profile", default=None, help="协议 Profile 文件路径")
    serial_log.add_argument("--duration", type=float, default=0, help="记录时长秒（默认无限）")

    # serial dashboard
    serial_dashboard = serial_sub.add_parser("dashboard", help="Web 可视化 Dashboard")
    _add_serial_port_args(serial_dashboard, multi=True)
    serial_dashboard.add_argument("--profile", default=None, help="协议 Profile 文件路径")
    serial_dashboard.add_argument("--host", default="127.0.0.1", help="HTTP 绑定地址")
    serial_dashboard.add_argument("--port-http", type=int, default=0, help="HTTP 端口（默认随机）")
    serial_dashboard.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    # serial profile (nested subcommands)
    serial_profile = serial_sub.add_parser("profile", help="Profile 管理")
    profile_sub = serial_profile.add_subparsers(dest="profile_command")

    sp_detect = profile_sub.add_parser("detect", help="从 C 源码检测帧结构")
    sp_detect.add_argument("--source", required=True, help="C 源文件路径")
    sp_detect.add_argument("--struct", default=None, help="指定 struct 名称")

    sp_generate = profile_sub.add_parser("generate", help="生成 Profile JSON")
    sp_generate.add_argument("--source", required=True, help="C 源文件路径")
    sp_generate.add_argument("--struct", default=None, help="指定 struct 名称")
    sp_generate.add_argument("--output", default=None, help="输出路径（默认 .mklink/serial_profile.json）")

    sp_show = profile_sub.add_parser("show", help="显示 Profile 内容")
    sp_show.add_argument("--profile", default=None, help="Profile 文件路径（默认自动查找）")

    # --- CPU Debug Control ---
    halt_parser = subparsers.add_parser("halt", help="停止 CPU 执行（写 DHCSR）")
    halt_parser.add_argument("--port", help="COM 端口（默认自动检测）")

    resume_parser = subparsers.add_parser("resume", help="恢复 CPU 执行")
    resume_parser.add_argument("--port", help="COM 端口（默认自动检测）")

    step_parser = subparsers.add_parser("step", help="单步执行一条指令")
    step_parser.add_argument("--port", help="COM 端口（默认自动检测）")

    break_parser = subparsers.add_parser("break", help="设置/管理 FPB 硬件断点")
    break_parser.add_argument("target", nargs="?", help="函数名或 Flash 地址（如 main 或 0x08001234）")
    break_parser.add_argument("--port", help="COM 端口（默认自动检测）")
    break_parser.add_argument("--source", help="ELF/AXF 文件路径（用于符号解析）")
    break_parser.add_argument("--project-root", default=".", help="项目根目录")
    _add_elf_backend_arg(break_parser)
    break_parser.add_argument("--slot", type=int, default=None, help="指定断点槽位 (0-5)")
    break_parser.add_argument("--list", action="store_true", help="列出当前已设置的断点")
    break_parser.add_argument("--clear", nargs="?", const="all", help="清除断点：指定槽位号或 all")
    break_parser.add_argument("--status", action="store_true", help="显示 CPU 调试状态")

    # serve 子命令
    serve_parser = subparsers.add_parser("serve", help="启动远程调试服务器（REST API + WebSocket JSON-RPC）")
    serve_parser.add_argument("--host", default="127.0.0.1", help="绑定地址（默认 127.0.0.1）")
    serve_parser.add_argument("--port", type=int, default=8765, help="绑定端口（默认 8765）")
    serve_parser.add_argument("--desktop-port-end", type=int, default=None, help=argparse.SUPPRESS)
    serve_parser.add_argument("--desktop-runtime-info", default=None, help=argparse.SUPPRESS)
    serve_parser.add_argument("--desktop-instance-id", default=None, help=argparse.SUPPRESS)
    serve_parser.add_argument("--token", default=None, help="客户端认证 Token")
    serve_parser.add_argument("--device-port", default=None, help="MKLink COM 端口（默认自动检测）")
    serve_parser.add_argument("--axf", default=None, help="AXF/ELF 文件路径")
    serve_parser.add_argument("--backend", choices=["legacy", "fastapi"], default="fastapi",
                              help="服务器后端（默认 fastapi，legacy 使用原始 socket）")
    serve_parser.add_argument("--project-root", default=".", help="项目根目录")

    # gui 子命令
    gui_parser = subparsers.add_parser("gui", help="启动 MKLink GUI（FastAPI + Vue 3 浏览器界面）")
    gui_parser.add_argument("--host", default="127.0.0.1", help="绑定地址（默认 127.0.0.1）")
    gui_parser.add_argument("--port", type=int, default=8765, help="绑定端口（默认 8765）")
    gui_parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    gui_parser.add_argument("--device-port", default=None, help="MKLink COM 端口（默认自动检测）")
    gui_parser.add_argument("--probe", default=None, help="下载器稳定 ID 或本机别名")
    gui_parser.add_argument("--axf", default=None, help="AXF/ELF 文件路径")
    gui_parser.add_argument("--project-root", default=".", help="项目根目录")

    # web-entry 子命令（U 盘单 HTML 跨平台启动入口）
    web_entry_parser = subparsers.add_parser(
        "web-entry",
        help="安装和管理跨平台 Mklink Web HTML 启动入口",
    )
    web_entry_sub = web_entry_parser.add_subparsers(dest="web_entry_command")
    web_entry_install = web_entry_sub.add_parser(
        "install", help="安装当前用户的自定义 URL 协议处理器",
    )
    web_entry_install.add_argument(
        "--html", default=None,
        help="同时生成通用 HTML 到指定路径（可直接指定 U 盘路径）",
    )
    web_entry_install.add_argument(
        "--quick-launch", action="store_true",
        help="检查完整依赖并自动将统一启动页写入 MICROKEEN U 盘或桌面",
    )
    web_entry_sub.add_parser("uninstall", help="卸载 URL 协议处理器")
    web_entry_html = web_entry_sub.add_parser("html", help="生成单文件通用启动 HTML")
    web_entry_html.add_argument("--output", required=True, help="HTML 输出路径")
    web_entry_start = web_entry_sub.add_parser("start", help="启动或复用 Mklink Web 服务")
    web_entry_start.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    web_entry_sub.add_parser("stop", help="停止由 Web 入口启动的服务")
    web_entry_sub.add_parser("status", help="显示 Web 入口服务状态")
    web_entry_handle = web_entry_sub.add_parser("handle", help=argparse.SUPPRESS)
    web_entry_handle.add_argument("uri", help=argparse.SUPPRESS)

    # mcp 子命令（MCP server，stdio transport）
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="启动 MCP (Model Context Protocol) server（stdio，供 Claude Code / 其他 MCP client 调用）",
    )

    runtime_parser = subparsers.add_parser("runtime", help="管理 0.3 共享 CDC 后台及调用 GUI 能力")
    runtime_sub = runtime_parser.add_subparsers(dest="runtime_command", required=True)
    for command in ("start", "serve"):
        entry = runtime_sub.add_parser(command)
        entry.add_argument("--project-root", default=".")
        entry.add_argument("--port", type=int, default=8765)
        entry.add_argument("--probe", default=None)
        entry.add_argument("--device-port", default=None)
        entry.add_argument("--probe-id", default="lobby", help=argparse.SUPPRESS)
    runtime_sub.add_parser("status")
    runtime_jobs = runtime_sub.add_parser('jobs', help='只查询已保留的独占任务，不连接硬件')
    runtime_jobs.add_argument('--probe')
    runtime_jobs.add_argument('--job')
    runtime_stop = runtime_sub.add_parser("stop")
    runtime_stop.add_argument("--confirm", action="store_true")
    runtime_stop.add_argument("--probe", default=None)
    runtime_call = runtime_sub.add_parser("call", help="调用共享能力，不独立打开 CDC")
    runtime_call.add_argument("capability")
    runtime_call.add_argument("--arguments", default="{}", help="JSON 参数对象")
    runtime_call.add_argument("--project-root", default=None)
    runtime_call.add_argument("--device-port", default=None)
    runtime_call.add_argument("--axf", default=None)
    runtime_call.add_argument("--probe", default=None)

    probes_parser = subparsers.add_parser("probes", help="被动列出下载器、设置本机别名")
    probes_sub = probes_parser.add_subparsers(dest="probes_command", required=True)
    probes_sub.add_parser("list")
    alias_parser = probes_sub.add_parser("alias", help="设置本机别名；空字符串清除别名")
    alias_parser.add_argument("probe", help="下载器稳定 ID、现有别名或 COM 端口")
    alias_parser.add_argument("alias")

    security_parser = subparsers.add_parser(
        "security",
        help="目标芯片可逆读保护（与 WebGUI/MCP 共用安全后端）",
    )
    security_sub = security_parser.add_subparsers(
        dest="security_command",
        required=True,
    )

    def _add_security_arguments(command_parser, *, unlock: bool) -> None:
        command_parser.add_argument("--target-part", required=True, help="精确器件型号")
        command_parser.add_argument(
            "--voltage-mv",
            type=int,
            choices=(1800, 3300, 5000),
            help="非 nRF54L15 安全操作后恢复的 VCC 电压；nRF54L15 请省略",
        )
        command_parser.add_argument(
            "--confirm",
            required=True,
            action="store_true",
            help="确认本次安全操作；非 nRF54L15 还需确认指定的 VCC 恢复电压",
        )
        if unlock:
            command_parser.add_argument(
                "--confirm-data-loss",
                required=True,
                action="store_true",
                help="确认解除读保护会永久擦除受保护的非易失数据",
            )
        else:
            command_parser.add_argument(
                "--firmware",
                required=True,
                help="加锁前必须校验通过的 BIN/HEX 固件",
            )
            command_parser.add_argument(
                "--base-address",
                type=lambda value: int(value, 0),
                default=None,
                help="BIN 固件起始地址（例如 0x08000000）",
            )
        command_parser.add_argument("--probe-id", default=None, help="可选探针 ID")
        command_parser.add_argument("--frequency", type=int, default=1_000_000)
        command_parser.add_argument("--timeout", type=float, default=240.0)
        command_parser.add_argument("--json", action="store_true")

    _add_security_arguments(
        security_sub.add_parser("lock", help="启用已验证的可逆读保护"),
        unlock=False,
    )
    _add_security_arguments(
        security_sub.add_parser("unlock", help="解除读保护并擦除受保护数据"),
        unlock=True,
    )

    flash_parser.add_argument('--request-id', help='保留任务请求 ID；结果未知时查询已有任务，不重放')
    for name in ('erase', 'reset'):
        entry = subparsers.add_parser(name, help='通过共享后台执行独占目标任务')
        entry.add_argument('--probe')
        entry.add_argument('--port')
        entry.add_argument('--project-root', default=None)
        entry.add_argument('--request-id')
    for entry in (read_ram_parser, write_ram_parser, rtt_cmd_parser, superwatch_parser, sv_parser, flash_parser,
                  read_flash_parser, halt_parser, resume_parser, step_parser, read_reg_parser, hardfault_parser, break_parser, speed_parser, power_parser, version_parser, dump_memory_parser, flush_memory_parser, measure_parser, watch_parser, vofa_parser):
        entry.add_argument('--probe', help='共享后台下载器 ID 或别名')
    for name in ('device-status', 'read-variable', 'write-variable'):
        entry = subparsers.add_parser(name, help='通过共享后台访问设备')
        entry.add_argument('--probe')
        entry.add_argument('--port')
        entry.add_argument('--project-root', default=None)
        entry.add_argument('--source', help='AXF/ELF 符号文件')
        if name != 'device-status':
            entry.add_argument('name', help='变量名')
        if name == 'write-variable':
            entry.add_argument('value', help='整数值，支持 0x 前缀')
    args = parser.parse_args()

    from mklink.runtime_cli import COMMANDS
    if args.command in COMMANDS:
        from mklink.runtime_cli import run
        run(args)
        return

    if args.command == "runtime":
        _cli_runtime(args)
        return
    if args.command == "probes":
        import json
        from mklink.probes import inventory, set_alias
        from mklink.runtime import RuntimeErrorResponse
        try:
            print(json.dumps(inventory() if args.probes_command == "list" else set_alias(args.probe, args.alias), ensure_ascii=False, indent=2))
        except RuntimeErrorResponse as exc:
            raise SystemExit(str(exc)) from exc
        return

    if args.command == "rtt-find":
        result = diagnose_rtt_addr(args.path)
        if result.addr:
            source = f" ({result.source})" if result.source else ""
            print(f"[OK] _SEGGER_RTT 地址: {result.addr}{source}")
        else:
            print("[FAIL] 未找到 RTT 地址")
            for detail in result.details:
                print(f"  - {detail}")
            for warning in result.warnings:
                print(f"  - {warning}")
            if result.path_checked:
                print("  - 已检查文件:")
                for checked in result.path_checked:
                    print(f"    {checked}")
    elif args.command == "autostart":
        print(generate_autostart_config(args.addr, args.size, args.channel))
    elif args.command == "keil-parse":
        _cli_keil_parse(_resolve_project_root(args))
    elif args.command == "iar-parse":
        _cli_iar_parse(_resolve_project_root(args))
    elif args.command == "project-init":
        _cli_project_init(_resolve_project_root(args))
    elif args.command == "mcu-detect":
        _cli_mcu_detect(
            _resolve_project_root(args),
            device=args.device,
            port=args.port,
            flm=args.flm,
            json_output=args.json,
        )
    elif args.command == "project-info":
        _cli_project_info(_resolve_project_root(args))
    elif args.command == "rtt-integrate":
        _cli_rtt_integrate(
            _resolve_project_root(args),
            args.src_dir, args.inc_dir, args.force,
            static_addr=getattr(args, "static_addr", None),
        )
    elif args.command == "systemview-integrate":
        _cli_systemview_integrate(_resolve_project_root(args), sv_dir=args.sv_dir)
    elif args.command == "copy-flm":
        _cli_copy_flm(_resolve_project_root(args))
    elif args.command == "systemview-analyze":
        _cli_systemview_analyze(
            _resolve_project_root(args), port=args.port, duration=args.duration,
        )
    elif args.command == "systemview-report":
        _cli_systemview_report(
            _resolve_project_root(args), port=args.port, duration=args.duration,
            out_path=args.out, no_browser=args.no_browser,
        )
    elif args.command in ("resources", "resource"):
        _cli_resources(args)
    elif args.command == "symbols":
        _cli_symbols(
            args.source,
            args.filter,
            backend=args.elf_backend,
            project_root=args.project_root,
        )
    elif args.command == "typeinfo":
        _cli_typeinfo(args)
    elif args.command == "memmap":
        _cli_memmap(args)
    elif args.command == "modbus":
        _cli_modbus_dispatch(args)
    elif args.command == "serial":
        _cli_serial_dispatch(args)
    elif args.command == "serve":
        _cli_serve(args)
    elif args.command == "gui":
        _cli_gui(args)
    elif args.command == "web-entry":
        _cli_web_entry(args)
    elif args.command == "mcp":
        _cli_mcp(args)
    elif args.command == "security":
        return _cli_security(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    raise SystemExit(main())
