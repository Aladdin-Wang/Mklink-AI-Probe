---
name: mklink-ai-probe
description: 使用 MKLink/MicroLink 进行固件烧录、RAM/寄存器与 AXF 调试、RTT/VOFA/SuperWatch、SystemView、Modbus/串口、本地 Web GUI 或 VPN/局域网远程调试；也用于安装、更新和排查使用问题。不用于维护 MKLink 本体源码、构建安装包或发布版本。
---

# MKLink 使用入口

本 Skill 面向设备使用者。安装、烧录、调试和 GUI 使用不需要读取仓库交接、
Git 状态、维护 Skill 或发布流程。仅按本次任务读取下表对应参考，不预读全部文档。
修改用户的目标 MCU 工程仍是使用任务；修改 MKLink 本体才属于仓库维护。

## 中间文件存放

首次需要写文件时固定一个工作根目录：用户指定位置优先，否则用目标项目的
`.mklink/`，不可用 Skill 安装目录或偶然的当前目录代替。Windows 不默认写 C 盘/
系统盘；项目在系统盘或没有项目时，先请用户指定非系统盘目录，并报告实际路径。
辅助脚本和临时文件放 `work/<本次任务>/`，日志放 `logs/`，报告放 `reports/`，
可复用缓存放 `cache/`；复用已选位置，不散落到项目根、桌面或系统临时目录。
产生日志/文件前按[工作目录与清理](references/work-files.md)设置实际输出参数、
采集预算和保留方式；不为集中输出改变目标工程或连接。结束时清理本次可再生临时
文件，保留缓存、用户资料和必要证据，报告保留位置；不得整目录删除 `.mklink`。

## 工具与首次使用

有可调用的 MKLink MCP tool 就优先使用，不按 AI 客户端品牌区分；没有 MCP 或
工具未覆盖时用 `python -m mklink <command>`。参数查工具 schema/`--help`，
找不到入口时再读 [操作速查](references/tool-index.md)。可用短脚本组合已有 SDK，
不要重写已有协议或绕过安全校验。固件下载的后端顺序见下方约束。

每会话首次实际使用时，读取 MCP `ping` 的 `update` 字段，或执行
`python <skill-root>/scripts/skill_update.py check --json`，二选一，不重复检查。
检查有 24 小时缓存，离线不阻塞任务，也不得打断已开始的烧录/调试。
发现更新时说明版本和发布说明；只有用户明确同意后才按
[安装与更新](references/install.md)执行安装。更新后需新会话加载 Skill。

### 远程场景的两端角色

现场机只运行官方独立 Site Agent ZIP/EXE，不读取 Skill，也不需要 AI 客户端、
源码或全局工具链；工程师机使用本 Skill 的 remote CLI/SDK/MCP。
远程操作先读 [直连远程调试](references/commands-remote.md)，包括部署、认证和
高风险操作确认。非回环监听须 `--allow-lan` 和 token；token 只来自环境变量或
owner-only secret file，不写入命令、URL、日志、项目配置或回答。

## Agent 核心约束

- **固件下载**：先读下载优先级参考。普通 MCU 默认 IDE 原生命令行 → pyOCD
  在线烧录 → MKLink 脱机 API；原生 `flash` 串口/FLM 路径只在用户显式要求时用。
  只有不适用或能力不可用才进入下一后端；作业开始后失败，停止并报告原因，
  经用户同意才换后端。
- **目标数据**：内存、变量、寄存器、符号、RTT 和 HardFault 先用 MKLink MCP/CLI。
  仅在明确连接失败、固件不支持或可复现读取错误后，报告原因并用 pyOCD 只读兜底。
- **单探针边界**：先读 `ping.limits`，一次连接复用到任务结束，同一下载器不得并行调用。
  多变量快照优先 `read_memory_regions`；不要绕过工具的大小、区域数和 30 秒采集限制。
  命令超时后只查一次 `device_status`，不得原样重试；流结束先断开再做普通命令。
- **AXF/ELF**：默认使用内置 pyelftools；`readelf_available:false` 不阻止操作。
  仅在用户明确指定 `elf_backend=external` 时调用 readelf/addr2line，内置失败不得静默切换。
- **未知 MCU**：先 `detect_mcu_profile` / `mcu-detect`，不能直接改成 `custom`。
  FLM 自动发现依次考虑内置 Pack、内置 DAPLink、已安装 Pack、自定义算法；
  多内部候选请用户选择，显式算法优先。缺少算法时停止并提示所需 Pack。
- **HPM 例外**：`HPM*` 只用设备端 ROM API，不找 Pack、不加载 FLM、不追加通用
  SWD reset。烧录提供 `.bin`、精确 `target_part`、`base_address` 和 `board`
  （推荐）或四字 `hpm_flash_cfg`；结果应为 `algorithm_source: "hpm-rom-api"`。
- **串口**：同一 COM 口禁止并行访问；Modbus 点表先 detect 汇报确认，再 generate。
- **供电**：`set_power_on` 仅允许 1800/3300/5000 mV，每次先确认具体电压并传
  `confirm_user=True`，不得复用历史确认。5000 mV 还须确认原理图、供电路径与负载
  耐受 5 V，并传 `confirm_5v=True`；误接可能永久损坏硬件。
- **复位**：`reset` 复位目标 MCU；`reboot_probe` 重启探针，会断开会话、释放锁，
  等 USB 重新枚举后再连接。

## 模块路由

| 本次任务 | 按需读取 |
|---|---|
| 下载固件、IDE/pyOCD/脱机后端选择 | [下载优先级](references/firmware-download-priority.md) |
| 烧录、项目初始化、RTT 集成/捕获 | [烧录与 RTT](references/commands-flash-rtt.md) |
| 静态 RTT、固定 CB 地址、MKLINK_RTT_STATIC | [RTT 静态模式](references/rtt-static-mode.md) |
| SystemView RTOS 跟踪、分析与报告 | [SystemView](references/systemview-rtthread.md) |
| RAM、变量、VOFA/SuperWatch、AXF、HardFault | [内存与符号](references/commands-memory.md) |
| flush-memory、多地址/分块写入 | [静默写边界](references/flush-memory.md) |
| Modbus、RS485、点表 | [Modbus](references/commands-modbus.md) |
| 串口 UART、协议 profile | [串口](references/commands-serial.md) |
| VPN/局域网远程调试、远程烧录、Site Agent | [直连远程](references/commands-remote.md) |
| 本地 Web GUI/API、桌面应用 | [本地 GUI](references/commands-remote-gui.md) |
| 安装、更新、运行依赖故障 | [安装与更新](references/install.md) |
| U 盘/桌面 HTML 快速启动、web-entry | [Web 入口](references/web-entry.md) |
| Windows USB 端口名称修改/恢复 | [端口命名](references/windows-port-names.md) |
| 复杂任务编排或故障排查 | [工作流](references/workflows.md) |

## 快速开始

已安装时直接使用对应工具，无需重装或编译 MKLink。首次安装读安装参考，完成
运行依赖与 Web assets 自检，再生成快速启动入口；不能只复制本文件就报告安装成功。
