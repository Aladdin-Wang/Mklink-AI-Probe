# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-16T11:57:41+08:00`
- 分支：`master`
- HEAD：`本地 master 已从 origin/master 8f6a094 选择性合入 FLM 查找修复 8da2d2d；立芯 GUI 与 HIL 锁提交均未合入。`
- 远端 HEAD：`origin/master 仍为 8f6a094；本次只授权本地合并，未授权推送或发布。`
- 工作树：FLM 修复只改动 mcu_detect.py 与 mcu_profiles.json；验证产生的构建和临时文件不纳入 Git，切换分支前已有未跟踪生成目录保持不变。
- 当前任务：device 级 PDSC algorithm 查找修复已选择性合入本地 master；立芯 GUI 与 HIL 锁提交仍留在原分支。
- 状态：`flm_discovery_fix_merged_local_master`

## 里程碑

- **产品与分发** — `complete`。Python、Skill、Web GUI 和 Tauri 版本统一为 v0.1.6，标准 NSIS 使用内置 sidecar。
- **烧录与兼容性** — `complete`。在线/脱机烧录、HPM ROM API、Pack/FLM、固件刷新、复合探针和扇区解析已集成。
- **调试与数据流** — `complete`。Memory、RTT、SystemView、VOFA、串口和 Modbus 共用资源仲裁与轻量流通道。
- **多实例与远程** — `complete`。每个桌面实例使用独立后端和探针连接；Site Agent 支持认证直连与 LAN STCP。

## 验证证据

- **FLM 查找修复选择性合并**：从 origin/master 8f6a094 创建 fix/pdsc-device-algorithm，仅摘取原提交 68d4e4f 为 8da2d2d；差异只有 mklink/mcu_detect.py 与 mklink/mcu_profiles.json，无 GUI 或 HIL 锁文件。真实 D:\Keil_v5\ARM\PACK 中 Keil.STM32F4xx_DFP.pdsc 对 STM32F411CEUx/RETx 均命中 device 级 CMSIS/Flash/STM32F4xx_512.FLM。Python 全量先得 1282 passed、1 skipped，环境性失败随后逐项联网复跑通过；GUI 54 文件/521 项、Vite 生产构建、Tauri cargo check 均通过。Site Agent 打包补入与当前 stcp_bridge 源码哈希一致的本地 DLL 后 3 项通过，DLL 与测试产物均不提交。
- **v0.1.6 运行时**：GUI 518 项、配置页 22 项和连接后端 12 项通过；Python 可比门禁 1262 项通过、1 项跳过。真实 Chrome、独立 Web 后端、下载器和 HPM5301 完成自动搜索、错误端口回退和再次连接闭环。
- **烧录与数据流**：HPM 在线烧录自动运行、重复固件加载、浏览器文件刷新和客户 HEX 解析已验证；串口/RTT 高吞吐与下载器 V2/V3/V4 数据完整性完成真机验证。
- **v0.1.6 正式分发**：七项资产哈希复算通过；正式 NSIS 已覆盖安装，健康与探针接口、内置 sidecar、零 Python 子进程、正常退出和动态端口释放通过。本地 Skill 指向 2f65f92c98；GitHub/Gitee Release、标签和 updates/latest.json 已核对一致。
- **浏览器后端生命周期**：真实 Chrome 双标签验证：关闭一个标签时后端继续运行；关闭最后标签后约 3 秒正常退出，8765 可立即重绑定。关闭前下载器保持连接，随后新后端能重新连接同一下载器，确认 CMD 串口和 Device 已释放。GUI 521 项、生产构建和 Tauri cargo check 通过；Python 1274 项通过、1 项跳过，12 项仅因 Windows 缺少符号链接权限失败。
- **源码与本地 Skill 同步**：Aladdin-Wang GitHub/Gitee master 与 su5176 PR #10 已同步；用户级 Skill、完整 GUI/MCP 依赖导入和 Skill 校验通过，快速启动网页已写入当前 MICROKEEN 卷。su5176 PR #10 于 2026-08-12 合并为 2f8e902。
- **PR #10 合并门禁复核**：GitHub 合并前状态 CLEAN、MERGEABLE，头 4d7d617 相对基线 6360843 前进 35 个提交且未落后；仓库未配置远端状态检查。本机隔离复核通过 GUI 54 文件/521 项、Vite 生产构建、Tauri Rust 12 项与 cargo check。首次 Python 全量得到 1284 passed、1 skipped；3 项仅因隔离 worktree 缺少未入库 mklink-stcp.dll 报错，在补入与 PR 完全相同 stcp_bridge 源码树生成且 SHA-256 一致的 DLL 后定向 3 项全通过。旧 Device 连接测试仍 mock 已移除的 _resolve_port，已改为 mock 当前 load_config 入口以消除本地项目配置依赖；修正后的最终 Python 全量为 1288 passed、1 skipped。PR 中既有真实 Chrome 双标签、下载器重连和 HPM/串口/RTT 真机闭环继续作为实机证据。

## 架构决策

- 历史端口是软偏好，可回退自动发现；当前会话手选端口首次保持严格约束，失败后切回自动搜索。
- 运行时修改在 fix/feature 分支完成全量测试、生产构建、项目记忆和真机闭环后合并。
- HPM 目标只使用 ROM API；ELF/DWARF 默认使用内置 pyelftools。
- Dashboard 与烧录/调试操作共用资源租约；复位前停止 RTT、SuperWatch、VOFA 和 SystemView。
- 串口和 RTT 终端使用独立 Worker 与有界缓冲；终端模式不维护隐藏日志。
- 每个 Tauri 实例拥有独立 sidecar、动态端口和探针锁；正式发布默认只生成标准 NSIS。
- 由命令主动打开的浏览器 GUI 使用标签页会话租约；最后标签消失后正常关闭后端并释放资源，显式 --no-browser 和 Tauri sidecar 保持常驻。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4 下载器；交接不记录端口或完整设备标识。
- **target**：ARM 与 HPM 真机可用；部分客户芯片仅完成 Pack/HEX 软件验证。
- **permission**：维护者已明确授权本次 su5176 PR #10 合并与必要收口；发布、Gitee 同步和破坏性烧录仍需单独授权。

## 下一动作

1. 监控 v0.1.6 用户反馈，运行时修复从新的 fix/feature 分支开始。
2. 下次正式发布前修正发布器的默认 GitHub/Gitee 仓库参数。
3. 需要扩大分发证据时，在干净 Windows 环境复测安装更新和 USB Web Entry。

## 已知限制

- 高事件率 SystemView 仍可能溢出目标 RTT 缓冲。
- V4 脱机首次触发的瞬时空失败仍需冷启动复现。
- 部分客户芯片修复缺少物理目标板编程证据。
- 先楫定制店铺尚无权威链接，菜单项保持禁用。
- USB Web Entry 和安装更新仍需更多平台与干净 Windows 验证。
- 发布器默认仓库参数仍含旧备用名；下次发布前应修正或继续显式传入两端 Aladdin-Wang 仓库。

## 延续协议

- 开始前用 Git、进程和硬件状态校正项目记忆。
- 不提交安装包、日志、硬件标识、凭据或构建缓存。
- 结束前执行 render、validate、diff 检查并保持工作树干净。
