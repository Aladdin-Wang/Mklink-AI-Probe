# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-11T21:30:58+08:00`
- 分支：`fix/device-connect-auto-search`
- HEAD：`修复分支基于 master@d4d25e2，设备连接自动搜索修复已完成自动化、生产构建和真实 Chrome/HPM5301 闭环。`
- 远端 HEAD：`origin/master 仍为 d4d25e2；本次修复尚未提交、合并或推送。`
- 工作树：仅包含设备连接自动搜索源码、回归测试、生成 Web 资源和本交接记录；既有其他工作树未改动。
- 当前任务：修复无有效端口或历史端口失效时，连接设备不会自动搜索且重复点击持续报错的问题。
- 状态：`device_connect_auto_search_verified_unmerged`

## 里程碑

- **产品与分发** — `complete`。Python、Skill、Web GUI 和 Tauri 均为 v0.1.6；标准 NSIS 内置 sidecar，可在无 Python 环境运行。
- **烧录与兼容性** — `complete`。在线/脱机烧录、HPM ROM API、CMSIS-Pack/FLM、同路径固件刷新、复合探针和相对扇区解析已集成。
- **调试与数据流** — `complete`。Memory、Symbols、HardFault、RTT、SuperWatch、SystemView、VOFA、串口和 Modbus 共用资源仲裁与轻量流通道。
- **多实例与远程** — `complete`。每个桌面实例使用独立动态后端和探针连接；Site Agent 支持认证直连与 LAN STCP。

## 验证证据

- **设备连接自动搜索**：配置页 22 项聚焦测试覆盖无端口、历史端口和手选端口失败后的自动搜索回退；GUI 全量 518 项和生产构建通过，底层连接相关 12 项通过。Python 全量 1262 项通过、1 项跳过，剩余 12 个符号链接权限失败及 3 个缺失 STCP 测试库错误均为既有环境门禁。真实 Chrome、独立 Web 后端、下载器和 HPM5301 已完成闭环：初始自动搜索可连接，手选非下载器串口失败后回到自动搜索，再次点击可重新发现并连接。
- **最新桌面与复位闭环**：启动动画已在真实 Tauri 窗口验证；复位前会停止冲突 Dashboard，真实 HPM 目标确认发送 cmd.set_reset() 后重新运行。完整 GUI、Python、Rust 和生产构建门禁已通过，环境性符号链接权限用例单独记录。
- **烧录与高吞吐数据流**：HPM 在线烧录可自动运行；重复固件加载、浏览器文件刷新和客户 HEX 扇区解析已验证。串口/RTT 终端长时高吞吐与下载器 V2/V3/V4 数据完整性已完成真机验证。
- **v0.1.6 本地分发**：标准 NSIS、updater 签名和 x64 STCP 运行库由当前 master 重建；覆盖安装后动态健康接口、探针枚举、内置 sidecar、零 Python 子进程、正常退出和端口释放均通过，本地 Skill 同步到同一源码提交。

## 架构决策

- 配置页恢复的历史端口是软偏好，可在同一次连接中回退自动发现；当前会话明确手选的端口首次保持严格约束，避免多下载器误连。任何连接失败都会让当前实例切回自动搜索，但不清除可能由其他实例共享的历史偏好。
- 运行时修改必须在 fix/feature 分支完成全量测试、生产构建、项目记忆和受影响真机闭环后再合并。
- v0.1.6 在 Python、插件、Tauri、Web GUI 和 Skill 中保持一致；默认只生成标准 NSIS。
- Dashboard 与一次性调试/烧录操作共用资源租约；MCU 复位前必须停止 RTT、SuperWatch、VOFA 和 SystemView。
- HPM 目标只使用专用 ROM API；ELF/DWARF 默认使用内置 pyelftools。
- 浏览器和桌面端必须重新读取同路径固件；FLM 相对重定位仅在完整算法范围可装入目标区域时允许。
- 串口和 RTT 终端使用独立 Worker 与有界缓冲；终端模式不维护隐藏日志，日志模式可保存当前保留内容。
- 每个 Tauri 实例拥有独立 sidecar、动态端口和探针锁；Site Agent 复用同一实例的 Device 与 ResourceManager。
- CURRENT_HANDOFF.md 只由 project-memory.json 生成，不保存会话流水和过期构建哈希。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4 下载器；交接不记录具体序列号和端口。
- **target**：可用 ARM 与 HPM 真机；部分客户芯片仅完成 Pack/HEX 软件验证。
- **permission**：破坏性烧录和外部发布仍需对应任务明确授权；本次仅执行连接与断开验证。

## 下一动作

1. 复现 V4 脱机首次空失败并增加设备输出诊断。
2. 使用更大目标 RTT 缓冲完成 SystemView 可持续事件率验证。
3. 完成 USB Web Entry 跨平台和干净 Windows 安装验证。

## 已知限制

- 高事件率 SystemView 仍可能溢出目标 RTT 缓冲。
- V4 脱机首次触发的瞬时空失败仍需冷启动复现。
- 部分客户芯片修复缺少物理目标板编程证据。
- 先楫定制店铺尚无权威链接，菜单项保持禁用。
- USB Web Entry 尚需 macOS/Linux 验证，安装与更新仍需第二台干净 Windows 机器验证。

## 延续协议

- 开始工作前用 live Git、进程和硬件状态校正项目记忆。
- 保持修改范围最小，不提交本地硬件路径、日志、安装包或凭据。
- 结束前执行 render、validate、git diff 检查，并按授权决定提交、推送或发布。
