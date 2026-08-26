# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-26T14:12:00+08:00`
- 分支：`master`
- HEAD：`v0.1.8 release squash（当前提交）`
- 远端 HEAD：`origin/master 尚未包含本次 v0.1.8 正式合并；发布器将验证后推送`
- 工作树：应用变更已 squash 合并；HPMLink V4.3.8 仅作为独立固件发布输入，未纳入 Git
- 当前任务：用户已验收 v0.1.8 候选并授权合并 master、正式发布应用 0.1.8 与 HPMLink V4.3.8；发布前清理历史候选和维护者上下文。
- 状态：`v0.1.8-release`

## 里程碑

- **v0.1.8 当前开发基线** — `complete`。固件升级不依赖先连接调试会话，可读取 MICROKEEN U 盘并进入 Bootloader；连接先返回串口成功，目标 MCU IDCODE 后台同步读取；配置页显示已连接 COM 号；移除重复的串口自动搜索按钮，保留刷新串口和端口名称手动修改/恢复。安装版 sidecar 默认工程根目录改为用户可写的 %LOCALAPPDATA%\com.microkeen.mklink-ai-probe\workspace。
- **USB 端口命名** — `complete`。使用管理员权限按 USB 设备实例写入 FriendlyName。MI_02 为 MKLink USB to UART，MI_04 为 MKLink Python Console，V4 的 MI_06 为 MKLink USB to RS485；V2/V3 不添加 MI_06。安装器会无条件执行一次初始化，但未连接设备时不会伪造不存在的 PnP 实例。
- **HPM 固件升级策略** — `complete`。HPM 系列改由 readme.txt 的 HPM Firmware Build Date 标识识别，STARTUP_ANIMATION.zhrgb 不再参与判断；本地 HPMLink_V4.3.8 候选可覆盖线上 V4.3.7。
- **HPM 真机闭环** — `complete`。HPM ROM API 烧录跳过 FLM；修复烧录后通用 reset 会停住 RISC-V 的问题。SDK FreeRTOS 工程完成 RAM/符号/RTT/故障注入与 ROM 重烧恢复验证。
- **普通用户发布内容隔离** — `complete`。公开 Skill 由明确运行时白名单构建，不包含 _maintainer、docs/ai、测试、桌面源码、固件或维护 Skill；更新器还会删除旧安装遗留的维护目录和构建垃圾。

## 验证证据

- **GUI 与 Tauri**：GUI 全量 57 个测试文件、583 项通过；Tauri Rust 16 项通过；Python 等效全量 1393 passed、1 skipped，剩余 12 项为当前 Windows 账户无目录 symlink 特权；Skill 更新聚焦测试 14 项及先前偶发快照测试单独通过。
- **安装包**：开发分支标准 NSIS 已在最终清理改动后重建，包含独立 Python sidecar、STCP 资源并生成 updater signature；此前覆盖安装已验证 /api/health=ok、配置持久化、无 Python 子进程且关闭后 8765 释放。正式资产将在 master 上重新生成。
- **真机证据**：指定 STM32F103RC 工程实际解析为 STM32F103RE/Keil AC5；探针 V4.3.7、IDCODE 0x1BA01477、Keil 编译/下载、Flash 回读、AXF 符号、RAM/SCB 读取、RTT、VOFA、SuperWatch、SystemView 和安全值 RAM 写回均通过。串口 TX/RX、RS485、Modbus 物理回环及 VCC 激励未在无明确回环/电压确认时执行。
- **HPM 固件升级**：本地 HPMLink_V4.3.8.uf2（SHA-256 D295858F...A7E3FA8）从探针 V4.3.7 自动升级成功；升级后 readme.txt 含 HPM Firmware Build Date 与 V4.3.8，REST 结果为 updated/verified_version V4.3.8。
- **HPM SDK 真机**：hpm5301evklite IDCODE 0x1000563D；demo.bin 以 hpm.program 在 0x80000400 烧录成功，运行计数持续增长，RTT 5 秒输出和 1600/800 rpm 动态响应正常，alarm_code=0。故意非法指令得到 trap_state=2、mcause=2、mtval=0xFFFFFFFF，随后 ROM API 重烧恢复。
- **SystemView 限制**：systemview-analyze 已使用 output/demo.elf 符号源，但 HPM 示例 2 秒产生 24296 事件并 target buffer overflow，任务区间为 0，未形成可信 CPU 统计；记录为示例固件/SDK trace 限制，不宣称完整通过。

## 架构决策

- 用户已授权将 v0.1.8-development squash 合并到 master，并正式发布应用 0.1.8 与 HPMLink V4.3.8。
- USB 端口名称保持按设备实例写入 FriendlyName；不使用常驻 SYSTEM 轮询，不引入未签名 Extension INF。配置页保留手动修改和恢复按钮。
- Windows 端口命名必须严格识别 VID_0D28/PID_0202、复合设备父子关系、ContainerId 和 MI；V4 才识别 MI_06。
- HPM 目标使用设备端 ROM API，不加载 FLM；VCC 输出仍需每次获得明确电压确认。
- HPM ROM API 已负责 RISC-V reset/resume，Device.flash 的 HPM 分支不得再调用通用 SWD reset。
- 普通用户 Skill 只发布运行时白名单；维护者项目记忆、测试、维护 Skill、固件和构建产物不进入归档，更新时删除旧版遗留内容。
- 不提交固件、Pack、FLM、日志、截图、硬件标识或构建缓存。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4；交接不记录端口号或完整探针标识。
- **target**：实际 STM32F103RE 可用于固件编译、下载和调试闭环；工程目录中的 STM32F103RC 为历史命名。
- **permission**：维护者已明确授权合并 master、签名、创建 v0.1.8 标签与双平台 Release、更新发布指针并独立发布 HPMLink V4.3.8。

## 下一动作

1. 提交开发分支最终 gui/dist 和项目记忆，然后 squash 合并到 master。
2. 在干净 master 上重建 NSIS、Site Agent 和严格七项发布资产，清理旧候选与构建垃圾。
3. 发布应用 0.1.8 和独立 HPMLink V4.3.8，验证 GitHub/Gitee Release、updates/latest.json、firmware/latest.json 与公开哈希。

## 已知限制

- 端口名称修改依赖管理员权限和 Windows 设备节点；更换另一只下载器后会产生新的设备实例，需要再次执行手动修改。
- 安装时未连接下载器只能完成命名初始化，不能提前修改未来尚不存在的设备实例。
- 当前 Windows 账户没有目录 symlink 权限，少量 Python 安全测试在该环境会失败；这不是本版本功能回归。
- HPM SDK 示例的 SystemView 高频 ECall 事件会导致目标缓冲溢出，当前不能提供可信任务 CPU 占用。
- 串口 TX/RX、RS485 和部分 VCC 场景没有稳定的自动化真机回环条件，不能用单元测试替代硬件验证。
- 正式安装包尚未完成 Windows Authenticode/驱动签名发布流程；当前签名仅为 Tauri updater 签名。
- 正式发布仍需在 master 生成完整七项资产，并由发布器验证 GitHub/Gitee 资产、更新清单和哈希。

## 延续协议

- 开始前校正 Git、进程和硬件状态。
- 不把未验证的硬件现象写成 PASS；记录真实环境限制。
- 结束前更新本文件并重新生成 CURRENT_HANDOFF.md。
