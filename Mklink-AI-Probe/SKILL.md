---
name: mklink-ai-probe
description: |
  MKLink/MicroLink 嵌入式调试：固件烧录、RTT View/VOFA/SuperWatch 可视化、RAM/寄存器读写、
  AXF 符号与 HardFault 调试、Modbus RTU、通用串口调试、远程 GUI/API。
  能力以 MCP tool 暴露（vendor-neutral，Claude Code / Cursor / ChatGPT 等均可调用），
  亦提供 CLI（python -m mklink）与 FastAPI/GUI。
  触发：Keil/IAR 初始化/烧录、RTT/VOFA 观测、read_ram/watch/superwatch、
  Modbus 扫描/读写/dashboard/点表生成、串口 open/send/dashboard、resources、symbols/typeinfo、dump-memory、flush-memory、version、serve/gui、
  **SystemView RTOS 跟踪**（systemview-integrate 集成/systemview 观测/systemview-analyze 分析/systemview-report 报告，任务切换/ISR/CPU 占用）、
  RTT 控制块静态编译（rtt_storage_mode=1）、散射文件中固定 RTT 地址、MKLINK_RTT_STATIC 宏、`.ARM.__at_0xADDR` 段名。
---

# Mklink AI Probe Skill

## 三层架构（重要 — 先读）

本 skill 是一个 Claude Code **Plugin**，能力分三层，Agent 应按环境选路径：

| 层 | 形态 | 何时用 |
|---|---|---|
| **① MCP 能力层**（首选） | 51 个 MCP tool（`mcp__mklink__*`），见下方速查 | Claude Code / 任意 MCP client 环境——参数 schema 化、自带智能默认、自动分块等增值 |
| **② 方法论层**（本文件 + `references/`） | 编排知识 | 教 Agent「何时用哪个 tool/命令、边界、排查思路」——MCP 与 CLI 共用 |
| **③ CLI 兜底层** | `python -m mklink <cmd>` | 人类入口、OpenAI/Codex 跨 harness、无 MCP 环境、MCP 未覆盖的可视化/工作流 |

**路径选择规则**：
- 在有 MCP 的环境（Claude Code）→ **优先调 MCP tool**（更可靠、有校验、有增值）
- MCP 未覆盖的：`project-init`、`dashboard`（Web 可视化）、`modbus pointmap detect/generate`、`vofa`/`superwatch` Web、`serve`/`gui` → 走 CLI
- OpenAI/Codex 或无 MCP → 走 CLI（`python -m mklink`）

## Agent 核心约束

- **MCP 优先**：Claude Code 环境下，烧录/内存/变量/RTT/HardFault/Modbus/串口等原子操作优先用 MCP tool；CLI 仅作兜底或 MCP 未覆盖时使用
- **禁止**编写 Python 脚本替代 MCP tool 或 CLI
- Modbus/串口 **同一 COM 口禁止并行访问**（须串行；MCP 层已用跨进程锁 `modbus_locks`/`serial_locks` 保证，探针用 `SerialLock`）
- Modbus 点表：先 `detect` 汇报并确认，再 `generate`
- 执行具体操作前：**先 Read 下方路由表对应的 reference**，理解边界（如 flush-memory 分块、RTT 静态模式选型）
- **符号/AXF 默认使用内置 pyelftools**：`load_symbols`/`read_variable`/`write_variable`/`memory_map`/函数断点/`decode_hardfault` 源码行不依赖用户电脑的编译工具链。AI **默认使用内置 pyelftools**，不得因 `readelf_available:false` 阻止 AXF 操作。**仅在用户明确指定** `elf_backend=external` 时，才调用本机 `readelf`/`addr2line`；仅设置工具路径不会自动启用 external。内置解析遇到不支持的文件时先报告原因，取得用户同意后才能切换外部兼容后端。
- **未知 MCU 禁止直接改 `custom` 兜底**：烧录前若项目 MCU 不在 `mcu_profiles.json`，先调用 MCP `detect_mcu_profile` 或 CLI `python -m mklink mcu-detect`。多内部 FLM 候选时把候选报给用户选择，再用 `flm`/`--flm` 固化；找不到本地 FLM/Pack 时停止并提示安装或解包 Keil/Arm Pack。HPMicro 是明确例外，见下一条。
- **HPMicro 禁止寻找或加载 FLM**：`HPM*` 型号使用探针设备端 HPM ROM API。MCP `flash` 传 `.bin`、精确 `target_part`、`base_address`，并传 `board`（推荐）或四字 `hpm_flash_cfg`；返回 `algorithm_source: "hpm-rom-api"`。在线、脱机和 CLI 都不得为 HPM 下载 Pack 或调用 `load.flm`。

## MCP tool 速查（52 tools，按能力域）

| 域 | Tools | 备注 |
|---|---|---|
| 健康 | `ping` | 无需连接，首调确认 server 活着 |
| 项目配置 | `detect_mcu_profile` | 新 MCU 发现、FLM 候选选择、profile 固化 |
| 连接 | `discover_probes` · `connect` · `disconnect` · `device_status` | connect 传 `axf=` 才能读变量 |
| Flash | `flash` · `erase_chip` · `erase_sector` · `reset` | flash 一站式（MCU+FLM+时钟自动） |
| 内存 | `read_memory` · `write_memory` · `flush_memory` | flush_memory **自动分块**（CLI 不分块会 FAIL） |
| 变量/寄存器 | `read_variable` · `write_variable` · `read_register` | 需先 connect(axf=) 或 load_symbols |
| 调试 | `halt` · `resume` · `step` · `set_breakpoint` · `clear_breakpoint` · `clear_all_breakpoints` · `read_core_registers` | FPB 硬件断点 |
| 符号 | `load_symbols` · `symbols_status` · `memory_map` | DWARF 段表 |
| RTT | `rtt_start`(mode=auto/dynamic/static) · `rtt_read` · `rtt_write` · `rtt_stop` · `capture_rtt` | mode 决策见 [rtt-static-mode.md](references/rtt-static-mode.md) |
| **SystemView** | `systemview_integrate` · `systemview_start` · `systemview_read` · `systemview_stop` · `capture_systemview` · `systemview_decode` · `systemview_analyze` · `systemview_analyze_events` · `systemview_report` | RTOS 跟踪（任务切换/ISR/CPU%）；集成见 [systemview-rtthread.md](references/systemview-rtthread.md)；先 rtt-integrate |
| HardFault | `check_hardfault` · `decode_hardfault` | decode 自动 CFSR 展开 + 内置 DWARF 源码回溯 |
| Modbus | `modbus_open` · `modbus_close` · `modbus_read` · `modbus_write` · `modbus_scan` | 独立串口（非探针） |
| 串口 | `serial_list` · `serial_open` · `serial_close` · `serial_send` · `serial_read` | 独立串口（非探针） |

> bytes 在 MCP 经 hex 字符串往返（`read_memory`→hex，`write_memory`/`serial_send`/`flush_memory`←hex）。

## CLI 命令速查（兜底 / 人类入口 / 跨 harness / 可视化）

| 命令 | 说明 |
|------|------|
| `serve` | 远程调试服务器（REST API + WebSocket JSON-RPC） |
| `gui` | 启动 GUI（FastAPI 后端 + Vue 前端） |
| `mcp` | 启动 MCP server（stdio，供 Claude Code / 其他 MCP client 调用；本 plugin 自动拉起） |
| `project-init` | 初始化项目配置（自动检测 IAR/Keil、MCU、COM 口） |
| `mcu-detect` | 发现/固化未知 MCU profile 与 FLM（多候选需选择） |
| `project-info` | 显示项目配置状态 |
| `flash` | 一站式烧录（连接 → IDCODE → FLM → 烧录） |
| `rtt` | 一站式 RTT 捕获（支持 `--visualize`） |
| `read-ram` | 读取 RAM 数据（十六进制 dump） |
| `read-reg` | 读取内存映射寄存器 |
| `write-ram` | 写入 RAM 并回读验证 |
| `dump-memory` / `dump` | 公共高速内存 dump（`cmd.dump_memory` 二进制帧；默认采集 1 个样本，单次上限 **512 KiB**，V4.3.3 实测整片 Flash 稳定） |
| `flush-memory` | 静默写 RAM，**多地址多字节**（成功无 ACK；适合与 `dump_memory` 并发场景）。<br>**紧凑语法**: `ADDR:BYTE*N`（如 `"0x20008000:0xAA*16300"`）绕开 Windows cmdline 长度限制。<br>**边界**: 单项 ≤ 12KB(压线) / 多地址 ≤ 8 项 / varargs ≤ 20 字节，三类边界详见 [references/flush-memory.md](references/flush-memory.md) |
| `read-flash` | 读取 Flash 数据 |
| `version` | 读取烧录器自身固件版本（`--all` 显示历史，`--raw` 原始输出） |
| `vofa` | VOFA+ 实时变量观测（支持 `--visualize`） |
| `symbols` | 从 ELF/AXF 列出 RAM 变量（默认内置 pyelftools） |
| `typeinfo` | 从 AXF DWARF 查询类型/结构体/枚举 |
| `watch` | 按变量名读取快照（支持 `struct.field`） |
| `superwatch` | 时间戳连续采样（支持 `--visualize`、`--dump-mem`） |
| `hardfault` | 解码 Cortex-M Fault 寄存器与异常栈帧 |
| `memmap` | 分析 AXF 段表（RAM/Flash 占用） |
| `rtt-integrate` | 集成 RTT 源码到 Keil/IAR 项目 |
| `systemview` | 一站式 SystemView RTOS 跟踪（实时解码任务切换/ISR） |
| `systemview-integrate` | 集成 SEGGER_SYSVIEW 到 RT-Thread 项目（先 rtt-integrate） |
| `systemview-analyze` | 采集并打印 RTOS 运行态分析（CPU%/切换/ISR/异常） |
| `systemview-report` | 采集并生成自包含 HTML 可视化分析报告（浏览器打开） |
| `rtt-find <map>` | 从 MAP 文件查找 RTT 地址 |
| `rtt_storage_mode=1` | 静态 RTT 编译（详见 [references/rtt-static-mode.md](references/rtt-static-mode.md)） |
| `copy-flm` | 拷贝 profile/工程指定的 FLM 到 MICROKEEN 磁盘 |
| `keil-parse` / `iar-parse` | 解析 Keil/IAR 工程文件 |
| `discover` | 发现 MKLink 端口 |
| `test --port COM6` | 测试连接 |
| `modbus` | Modbus RTU 调试（scan/read/write/poll/monitor/dashboard/pointmap） |
| `serial` | 通用 UART 串口调试 |
| `resources` / `resource` | 本地资源管理（释放 stale 串口/MKLink 锁；不需要 FastAPI） |

## 模块路由（渐进式披露 — MCP 与 CLI 共用方法论）

| 用户意图 / 关键词 | 读取文档 |
|------------------|----------|
| 安装、pip、readelf、Rust、Tauri | [references/install.md](references/install.md) |
| 烧录、RTT、project-init、Keil/IAR | [references/commands-flash-rtt.md](references/commands-flash-rtt.md) |
| RTT 静态编译、rtt_storage_mode、MKLINK_RTT_STATIC、.ARM.__at_0xADDR、CB 固定地址 | [references/rtt-static-mode.md](references/rtt-static-mode.md) |
| flush-memory 边界、12KB 分块策略、推荐用法 | [references/flush-memory.md](references/flush-memory.md) |
| RAM、VOFA、watch、HardFault、AXF | [references/commands-memory.md](references/commands-memory.md) |
| Modbus、RS485、点表、dashboard | [references/commands-modbus.md](references/commands-modbus.md) |
| 串口、UART、协议 profile | [references/commands-serial.md](references/commands-serial.md) |
| serve、gui、Tauri、桌面应用、远程调试 | [references/commands-remote-gui.md](references/commands-remote-gui.md) |
| 「用户说 X 我该跑什么」 | [references/triggers.md](references/triggers.md) |
| 新项目首次烧录、RTT 集成、故障排查 | [references/workflows.md](references/workflows.md) |

## 快速开始

**MCP 方式**（Claude Code，推荐）：直接调用 `mcp__mklink__*` tool，例如 `connect` → `flash` → `read_variable` → `rtt_start`。

**CLI 方式**（兜底 / 跨 harness）：

```bash
python -m pip install -e ".[gui]"   # 首次安装（GUI/MCP 依赖）
python -m mklink project-init
python -m mklink flash
python -m mklink rtt --duration 10
```

首次使用与依赖详见 [references/install.md](references/install.md)。

## 输出格式

- **MCP tool**：返回结构化 JSON（dict/list），错误经 MCP error 通道（含清晰 message）
- **CLI 成功**: `[OK] 操作描述`
- **CLI 失败**: `[FAIL] 错误原因`
- **CLI 警告**: `[WARN] 警告信息`
- **CLI 自动操作**: `[AUTO] 自动执行的操作`
- **RTT 输出**: 实时流式显示原始数据
