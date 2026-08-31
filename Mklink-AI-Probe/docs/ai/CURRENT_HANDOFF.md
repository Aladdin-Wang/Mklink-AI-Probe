# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-31T16:50:13+08:00`
- 分支：`master`
- HEAD：`0.1.9 release content is prepared and verified; publication commit IDs are fork-specific.`
- 远端 HEAD：`Reconcile the canonical upstream master before each maintenance change.`
- 工作树：Keep the checkout clean; build output belongs in MKLINK_BUILD_ROOT or the ignored .build directory.
- 当前任务：0.1.9 application, public Skill, Site Agent and V3/V4 firmware updates are verified and prepared for upstream review.
- 状态：`v0.1.9-upstream-review`

## 里程碑

- **0.1.9 桌面端与 WebGUI** — `complete`。修复覆盖升级、WebGUI 启动、AXF 全局符号、Pack 导入刷新；完成器件联想、烧录算法展示、串口 YMODEM、Modbus 工作台与快捷键。
- **SuperWatch 与流式性能** — `complete`。使用批量直接解码、动态批量、Worker 单一历史和事务成本地址合并；修复暂停/停止后历史消失，并完成采样周期补偿。
- **AI Skill/MCP 安全边界** — `complete`。普通用户 Skill 与维护流程分离；同一探针强制串行，限制读取、写入、批量、flush、dump_memory 和采集时长，超时后隔离会话。
- **0.1.9 发布候选** — `complete`。标准 NSIS、updater 签名、普通用户 Skill 和 Site Agent 便携包已生成；新增 MicroLink V3.3.8/V4.3.9 UF2 已通过发布预检。

## 验证证据

- **STM32F103RE 真机 HIL**：烧录、调试读写、16 路 SuperWatch、RTT/SystemView、串口/YMODEM、在线烧录、MCP 越界拒绝均通过；详情见 docs/verification/v0.1.9-stm32f103re-release-hil.md。
- **SuperWatch**：V4.3.9 下 16×float、1ms 请求得到 4690 样本，中位周期 1000us；暂停/停止后历史仍可查看。
- **自动化与构建**：GUI 626 项通过；Python 1675 passed、12 failed、1 skipped，12 项均为当前 Windows 账户无目录 symlink 权限导致的 WinError 1314；标准生产构建和 NSIS 成功。
- **发布运行时**：发布程序在仅系统 PATH 下启动内置 sidecar，无 Python 回退，关闭后释放 8765；fork 的 v0.1.9 应用、Skill、Site Agent 与固件资产已完成哈希回读。

## 架构决策

- 预发布分支持续维护，每个问题独立提交并及时推送；不再创建临时修复分支。
- 构建、测试、日志、临时脚本和可复用缓存统一位于 MKLINK_BUILD_ROOT 或主工作区忽略的 .build，并经 scripts/build_workspace.ps1 运行；不上传构建目录。
- 普通用户 Skill 只包含运行时能力、安全边界和按需参考，不加载源码维护、构建或发布流程；U 盘 HTML 使用跨平台 Skill Web handler。
- SuperWatch 连续采样使用 dump_memory；最多 15 region。MCP direct read/write≤4096B、batch≤16项/4096B、flush≤8项/12288B、capture≤30秒。
- 串口、YMODEM、Modbus 和硬件控制共用单一 I/O 所有权；同一下载器不得并行调用，超时后先检查状态并重建会话。
- 应用发布与探针固件发布相互独立；正式索引必须在所有资产上传并校验后最后更新。

## 真机环境

- **probe**：主要 ARM 回归夹具为 MKLink V4，发布前验证固件为 V4.3.9；交接不记录本机端口号。
- **target**：使用独立 STM32F103RE 测试工程完成编译、烧录和调试闭环；测试工程不纳入本仓库。
- **permission**：真机写入和危险输出必须由维护者针对当前测试明确授权。

## 下一动作

1. 后续问题在下一预发布分支持续小步修复、验证并及时推送。
2. HPM 系列回归、下载器固件深层问题和官方手册重构继续拆分推进。

## 已知限制

- 当前 Windows 账户缺少目录 symlink 权限，Python 全量有 12 项 WinError 1314；这不是业务测试失败。
- 0.1.9 未覆盖 Authenticode/驱动签名、跨账号安装和 0.1.7 实包升级；per-machine 安装验证需要 UAC。
- Modbus 真机只验证安全读取；GD32E517 线圈 0–3 控制真实功率功能，未执行危险写入。
- V4 + STM32H743 的 16×float 连续采样约 9.54k samples/s，不能承诺 16 变量稳定 10kHz 或 20kHz。

## 延续协议

- 开始前校正 Git、端口、目标固件和运行进程；硬件操作保持串行。
- 不把环境失败或未覆盖场景写成 PASS；关键证据写验证报告，交接只保留结论。
- 结束前更新 project-memory.json、渲染 CURRENT_HANDOFF.md，并保持工作树与远端同步。
