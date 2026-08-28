# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-28T08:34:22+08:00`
- 分支：`codex/v0.1.9-development`
- HEAD：`68dde8a（本次维护流程更新前的已推送基线；最终提交号以 Git 为准）`
- 远端 HEAD：`更新前已 fetch 并确认 origin/codex/v0.1.9-development 与本地 68dde8a 一致；维护流程修改随本提交保存并按新规则推送。master 未改动。`
- 工作树：持续维护 codex/v0.1.9-development，不再为每个问题创建分支或工作树。每个完成的问题验证、更新交接后单独提交并立即推送 GitHub；.build 仍忽略，缓存复用。
- 当前任务：维护者已要求改用预发布分支持续维护，并长期授权每修复一个问题即提交推送。AGENTS.md 与维护 Skill 已同步；Web GUI 18% 问题已在真实浏览器复现（错误 MIME + 原端口旧缓存），接下来在现有 0.1.9 分支修复，不新建修复分支。
- 状态：`prerelease-continuous-maintenance-web-mime-fix-pending`

## 里程碑

- **v0.1.9 开发准备** — `complete`。从 a42f9ed 创建 codex/v0.1.9-development；本地和 origin/v0.1.8-development 已删除。Python、Tauri、Site Agent、插件和打包版本统一为 0.1.9，发布历史未改。新增受 Git 忽略的集中构建目录和统一入口，缓存复用、临时目录清理及非系统盘约束均已验证。
- **串口自定义波特率 / PR #4** — `complete`。5ebe1b7 移植 a2160823797-wq 的数字输入＋常用值候选实现，保留 Co-authored-by；补测负数、非安全整数、运行中自定义值回显。PR #4 在功能提交推送后关闭，未向 master 合并。
- **自动升级安装修复** — `complete`。2978f02 撤掉自定义安装前卸载，交由 Tauri 原生覆盖升级；新文件写入后仅修正匹配旧用户级路径的已有快捷方式。保留用户主动删除/修改的快捷方式及旧目录。隔离 NSIS 夹具已复现历史缺陷并验证修复；实际签名包升级验收仍待完成。
- **v0.1.8 已发布功能基线** — `complete`。固件升级不依赖先连接调试会话，可读取 MICROKEEN U 盘并进入 Bootloader；连接先返回串口成功，目标 MCU IDCODE 后台同步读取；配置页显示已连接 COM 号；移除重复的串口自动搜索按钮，保留刷新串口和端口名称手动修改/恢复。安装版 sidecar 默认工程根目录改为用户可写的 %LOCALAPPDATA%\com.microkeen.mklink-ai-probe\workspace。
- **HPM 真机闭环** — `complete`。HPM ROM API 烧录跳过 FLM；修复烧录后通用 reset 会停住 RISC-V 的问题。SDK FreeRTOS 工程完成 RAM/符号/RTT/故障注入与 ROM 重烧恢复验证。
- **普通用户发布内容隔离** — `complete`。公开 Skill 由明确运行时白名单构建，不包含 _maintainer、docs/ai、测试、桌面源码、固件或维护 Skill；更新器还会删除旧安装遗留的维护目录和构建垃圾。

## 验证证据

- **0.1.9 GUI / 受影响 Python**：GUI 全量 57 文件、584 项通过；生产构建通过。实际 Edge 加载 gui/dist 验证非法值禁用、250000 整数提交、连接后回显锁定及关闭后恢复控件；串口传输使用模拟接口，不是真机。最终相关 Python（Tauri 构建、固件、发布归档和项目记忆）68 项通过。
- **Python 全量限制**：整套尝试未全绿；一次全量 1393 passed、15 failed、1 skipped。排除其中 600 秒 pip 安装超时项后复跑 1394 passed、13 failed、1 skipped、1 deselected；剩余包括 12 项 WinError 1314 符号链接权限和 1 项依赖线上版本的固件夹具。固件夹具随后隔离线上索引并在最终 68 项中通过。不能宣称全量门禁通过。
- **NSIS 升级流程**：使用 Tauri 实际生成模板与当前钩子、隔离注册身份/目录/测试可执行文件：历史钩子＋延迟卸载夹具复现新程序和图标丢失；修复后的 0.1.7/0.1.8 同目录升级、跨目录快捷方式迁移、已删除/另有目标快捷方式共 5 场景通过，配置及 /R 重启标记保留。这不是正式产品签名包或 UAC/真机验收。
- **存储与清理**：此前约 4.74 GiB 已清理、6.27 GiB Cargo 缓存集中保留；本轮移除无独有源码的旧工作树约 116 MiB。用户手动清理的四目录确认均不存在。本轮测试仅写 .build，含目录链接和一个占用文件的 3 个 runs 留待手动清理，路径在本机 reports/manual-cleanup.txt；未绕过权限或执行策略。
- **0.1.8 历史安装包验证**：0.1.8 已正式发布，GitHub Release 的七项资产仍在。历史候选安装验证包括 /api/health=ok、配置持久化、无 Python 子进程且关闭后 8765 释放；不视为 0.1.9 安装包验收。
- **0.1.8 历史 HPM 固件升级**：本地 HPMLink_V4.3.8.uf2（SHA-256 D295858F...A7E3FA8）从探针 V4.3.7 自动升级成功；升级后 readme.txt 含 HPM Firmware Build Date 与 V4.3.8，REST 结果为 updated/verified_version V4.3.8。
- **0.1.8 历史 HPM SDK 真机**：hpm5301evklite IDCODE 0x1000563D；demo.bin 以 hpm.program 在 0x80000400 烧录成功，运行计数持续增长，RTT 5 秒输出和 1600/800 rpm 动态响应正常，alarm_code=0。故意非法指令得到 trap_state=2、mcause=2、mtval=0xFFFFFFFF，随后 ROM API 重烧恢复。
- **SystemView 限制**：systemview-analyze 已使用 output/demo.elf 符号源，但 HPM 示例 2 秒产生 24296 事件并 target buffer overflow，任务区间为 0，未形成可信 CPU 统计；记录为示例固件/SDK trace 限制，不宣称完整通过。

## 架构决策

- 2026-08-28 维护者指定在当前预发布分支持续维护（现为 codex/v0.1.9-development），不再创建单问题分支/工作树。每个完成的修复在相关验证和记忆更新后单独提交并及时推送 GitHub origin，已长期授权，不必重复询问推送；合并 master、签名、发布、标签、更新指针和 Gitee 仍需另行授权，完整发布门禁保持不变。
- USB 端口名称保持按设备实例写入 FriendlyName；不使用常驻 SYSTEM 轮询，不引入未签名 Extension INF。配置页保留手动修改和恢复按钮。
- Windows 端口命名必须严格识别 VID_0D28/PID_0202、复合设备父子关系、ContainerId 和 MI；V4 才识别 MI_06。
- HPM 目标使用设备端 ROM API，不加载 FLM；VCC 输出仍需每次获得明确电压确认。
- HPM ROM API 已负责 RISC-V reset/resume，Device.flash 的 HPM 分支不得再调用通用 SWD reset。
- 普通用户 Skill 只发布运行时白名单；维护者项目记忆、测试、维护 Skill、固件和构建产物不进入归档，更新时删除旧版遗留内容。
- 默认不提交固件、Pack、FLM、日志、截图、硬件标识或构建缓存；本轮维护者明确例外授权将本地 HPMLink_V4.3.8.uf2 升级包及 V4.3.7 替换提交到开发分支，434bf79 已完成；不代表固件通道发布。
- 维护者指定所有构建/测试临时内容集中在主工作区 .build，通过 scripts/build_workspace.ps1 运行；禁止 C 盘/系统盘输出、禁止提交或上传构建数据，保留可复用缓存。权限或目录链接不确定时报告路径供用户手动处理。
- 维护者确认自定义波特率采用数字输入＋常用候选，不新增后端接口；接受正安全整数，非法值不得启动串口；实际支持速率仍由驱动/设备决定。
- 维护者确认自动升级取消自定义强制卸载，成功写入后迁移匹配的旧快捷方式，不自动删除旧目录；测试限 E 盘隔离身份，不改动当前正式安装。详见 docs/ai/windows-upgrade.md。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4；交接不记录端口号或完整探针标识。
- **target**：实际 STM32F103RE 可用于固件编译、下载和调试闭环；工程目录中的 STM32F103RC 为历史命名。
- **permission**：此前安装/串口验证使用隔离夹具和模拟接口；本轮 Web MIME 复现只启动隔离本地服务并查看浏览器，没有连接设备、烧录、串口收发或 VCC 操作。正式安装未改动。

## 下一动作

1. 发布前另行授权实际签名候选包，完成 0.1.7/0.1.8→0.1.9 的下载、签名、UAC、安装、快捷方式、后端健康和退出闭环；不能用夹具测试代替。
2. 在具备目录符号链接权限且依赖安装可完成的环境补齐 Python 全量门禁；不要静默跳过失败项。
3. 接入可用 USB 串口后完成自定义波特率打开/关闭及必要收发真机验收；驱动不支持的速率应保留实际错误。
4. 用户可按本机 .build/reports/manual-cleanup.txt 清理本轮 3 个保留目录；不跟随链接删除外部目标。
5. 优先在当前预发布分支修复 Web MIME 与坏缓存恢复，验证原端口无需清缓存即可加载配置页/仪表盘和浏览器会话；每个修复完成即提交推送。所有构建测试继续经 build_workspace.ps1 使用 E 盘 .build，不发布正式版本。

## 已知限制

- 端口名称修改依赖管理员权限和 Windows 设备节点；更换另一只下载器后会产生新的设备实例，需要再次执行手动修改。
- 安装时未连接下载器只能完成命名初始化，不能提前修改未来尚不存在的设备实例。
- 当前 Windows 账户没有目录 symlink 权限，少量 Python 安全测试在该环境会失败；这不是本版本功能回归。
- HPM SDK 示例的 SystemView 高频 ECall 事件会导致目标缓冲溢出，当前不能提供可信任务 CPU 占用。
- 串口 TX/RX、RS485 和部分 VCC 场景没有稳定的自动化真机回环条件，不能用单元测试替代硬件验证。
- 正式安装包尚未完成 Windows Authenticode/驱动签名发布流程；当前签名仅为 Tauri updater 签名。
- 0.1.9 仅开发分支；签名安装包全链路升级、UAC 和 USB 自定义波特率真机仍待验收。跨 Windows 账号提权迁移需单独测试，已卸载到无法启动的旧用户需手动重装修复版本。
- Python MCP 隔离依赖安装超时，12 项目录符号链接测试缺少权限；完整门禁未满足。本轮 .build/runs 中 3 个目录保留供手动清理，具体路径仅在本机 reports/manual-cleanup.txt，不强删。

## 延续协议

- 开始前校正 Git、进程和硬件状态。
- 不把未验证的硬件现象写成 PASS；记录真实环境限制。
- 结束前更新本文件并重新生成 CURRENT_HANDOFF.md。
