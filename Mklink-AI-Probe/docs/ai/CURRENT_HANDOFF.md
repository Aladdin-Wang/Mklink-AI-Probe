# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-11T19:03:30+08:00`
- 分支：`master`
- HEAD：`master@c9a40be 已合并桌面启动动画、版本记录精简、MCU 复位入口和复位资源互斥修复。`
- 远端 HEAD：`origin/master@c9a40be 已接收功能合并；本交接提交仅同步最终验证与清理状态。`
- 工作树：最终交接提交后保持干净；本地真机日志、构建缓存和 .mklink 运行数据不进入 Git。已合并旧分支已清理，保留有未提交工作的 worktree 和未合并分支。
- 当前任务：桌面启动动画、精简版本记录、MCU 复位入口和复位前 Dashboard 退出已完成真机验证、合并与 GitHub 推送。
- 状态：`desktop_startup_reset_complete`

## 里程碑

- **产品与分发基线** — `complete`。v0.1.6 已统一 Python、Skill、Tauri 主程序和 Web GUI；标准 NSIS 使用内置 sidecar，可在没有 Python 的安装环境运行。
- **烧录与文件刷新** — `complete`。在线/脱机烧录、HPM ROM API、CMSIS-Pack/FLM、自定义算法和浏览器/桌面文件加载已实现；同路径重载、重编译自动刷新、HPM 复合端口和 CST92F41 相对扇区已修复。
- **调试与高吞吐数据流** — `complete`。符号、内存、HardFault、RTT、SuperWatch、SystemView、VOFA、串口和 Modbus 已集成；串口/RTT 终端使用独立轻量通道，日志模式可保存本地文件。
- **资源互斥与多下载器** — `complete`。Dashboard、Memory 和烧录操作共享资源管理；每个桌面实例拥有独立 sidecar、动态后端端口和 CMD 端口锁，自动发现可并发连接不同下载器。
- **远程 Site Agent** — `complete`。主 GUI 与独立便携 Agent 支持认证的直连和 LAN STCP；本地 GUI、远程 Agent 和托盘服务共用后端与探针资源，凭据由 Windows DPAPI 保护。
- **桌面启动体验** — `complete`。静态启动页在 Vue 和后端端点初始化之前显示下载器主图，并按端点发现、工作区加载和应用挂载更新进度；实际 Tauri 窗口已完成桌面和窄屏检查。

## 验证证据

- **v0.1.6 本地分发**：master 合并提交 43ec353，Web 资源提交 1b7f57a。本地安装版、Skill 和 Web GUI 已更新并通过健康检查；安装包 SHA-256 为 403E80A75EDF6F38A2D7968A4CF34598B692AAA42327B0937AA8830D1354FE21，Skill 包 SHA-256 为 28427FCCDE408E21E597B6FACECD2CB3E7851377EAFB8935D76453903BD85AB0。
- **桌面多实例与双下载器**：一个 Web Entry 占用首选端口时，两个安装版桌面实例选择不同后端端口；关闭一个不影响另一个。V3 与 V4 真机同时自动连接到不同 CMD 接口，非 CMD 串口的伪提示被唯一命令握手拒绝。
- **桌面隔离最终自动门禁**：Python 聚焦测试 120 项通过；完整 Python 为 1263 passed、1 skipped，仅有 12 个已知 Windows 符号链接权限失败；GUI 为 52 个文件、508 项测试通过；vue-tsc、Vite 生产构建、Tauri Rust 12 项测试和 git diff 检查通过。
- **GUI、资源互斥与低编号串口**：STM32F103 真机验证 RTOS Trace 与 Memory 自动互斥；Windows 单位数虚拟串口验证 serial_ 前缀锁。GUI 为 52 个文件、507 项测试通过，完整 Python 为 1253 passed、1 skipped。
- **固件加载与芯片兼容**：HPM6E00 最新 BIN 已通过 ROM API 编程、校验和回读；桌面同路径 HEX 重载由用户确认；CST92F41 客户 HEX 已通过 Pack、FLM 最终化和 Web 扇区解析，未对 CST 目标执行烧录。
- **串口与 RTT 数据流**：HPM6E00 串口终端完成 10 分钟约 7.22 MB 数据流，后端批次零丢弃且浏览器保持响应；日志模式保留 5000 条并弹出本地保存窗口。下载器 V2/V3/V4 的 UART/RTT/VOFA DMA 与并发队列修复已完成真机验证。
- **桌面启动、复位入口与 HPM5301 在线烧录**：下载器主图、阶段进度和深色启动背景已在实际 Tauri 窗口验证；仪表盘连接与复位操作在默认窗口保持可见。HPM5301 EVK Lite 的 35164 字节 BIN 完成 connect、program、verify、reset、disconnect，count 连续采样由 252 增长至 535，确认烧录后自动运行。源码后端真机复位先停止 SuperWatch，再发送 cmd.set_reset()；count 由 13185 回到 50 且会话保持停止。GUI 53 个文件、512 项测试和 Rust 12 项测试通过；完整 Python 为 1262 passed、1 skipped，另有 12 个既有 Windows 符号链接权限失败和 3 个缺少 mklink-stcp.dll 的打包错误；前端与 Tauri release 构建通过，NSIS 生成后因未提供维护者签名私钥未执行签名。

## 架构决策

- AGENTS.md 与仓库维护 Skill 是开发和发布流程的权威来源。运行时修改必须使用 fix/feature 分支，通过完整 Python、GUI、生产构建、git diff、项目记忆和受影响真机闭环后才能合并。
- 不得推断发布授权。推送、标签、GitHub Release、updates/latest.json、Gitee 同步和正式签名发布分别需要维护者明确授权。
- 产品版本 0.1.6 在 Python、插件、主 Tauri、独立 Tauri、便携包和 GUI 版本历史中保持一致。
- 每个 Tauri 实例拥有唯一 sidecar 标识和动态 loopback 端口；只终止自己创建且仍持有的进程。Web Entry 同样只停止自己拥有的服务。
- 自动恢复的探针端口是软偏好，可在跨进程发现锁内选择另一合法 CMD；用户显式选择的端口是严格约束。CMD 身份必须通过唯一命令输出行验证，通用提示符或回显不够。
- Dashboard 会话和一次性调试/烧录操作使用串行资源租约。用户操作可在同步停止 Dashboard 所有者后接管，但不能抢占另一用户操作；MCU 复位必须先停止 RTT、SuperWatch、VOFA 和 SystemView，HPM 在线烧录还必须关闭共享 Device。
- HPM 目标只使用专用 ROM API，不使用 FLM。ELF/DWARF 默认使用内置 pyelftools，外部 GNU 工具仅为显式兼容后端。
- 浏览器固件文件在支持时保留 File System Access 只读句柄并轮询重编译元数据；普通文件输入每次选择后清空。桌面端选择同一路径也必须显式重新解析。
- PDSC Flash 区域与 FLM 地址不重叠时，仅当完整 FLM 范围能装入所属区域，才允许按区域相对地址重定位；运行时必须复制 FLM 元数据。
- 串口和 RTT 的日志/终端订阅使用独立 Worker 与有界缓冲。终端模式不构造或同步隐藏日志 DOM；日志模式最多保留 5000 条并只保存当前保留内容。
- Site Agent 在主 Tauri 中复用现有 sidecar、Device 和 ResourceManager。非 loopback 监听必须显式 allow-lan 并配置令牌；敏感凭据不得进入命令行或前端状态。
- CURRENT_HANDOFF.md 只由 project-memory.json 生成。交接保持精简，不追加会话流水；具体历史、旧哈希和已完成计划从 Git 查询。

## 真机环境

- **probe**：维护机可同时连接 V3、V4 下载器；具体序列号和 COM 号不写入交接。
- **target**：可用 STM32F103、HPM6E00/HPM5301 和其他既有测试板。CST92F41 仅有客户 Pack/HEX 软件验证，暂无目标板。
- **permission**：本次 HPM5301 在线烧录、校验、复位和只读 count 采样已由任务授权完成；后续破坏性操作仍需对应任务明确需要。

## 下一动作

1. 复现 V4 脱机首次空失败并增加设备输出诊断。
2. 使用更大目标 RTT 缓冲完成 SystemView 可持续事件率验证。
3. 在 macOS/Linux 验证 USB Web Entry，并在第二台干净 Windows 机器验证安装与更新。

## 已知限制

- 高事件率 SystemView 仍可能溢出目标 RTT 缓冲；主机无法恢复目标端已经丢失的事件。
- V4 脱机首次触发曾出现一次瞬时空失败，重试成功；仍需冷启动复现和设备输出诊断。
- CST92F41 修复没有物理目标板擦除/编程/校验证据。
- 先楫定制店铺尚未提供权威链接，因此菜单项保持禁用。
- USB Web Entry 尚需 macOS/Linux 验证；NSIS 与旧客户端更新仍需第二台干净 Windows 机器验证。
- npm audit 有一个仅开发依赖的高危传递项 brace-expansion；运行时依赖审计正常。

## 延续协议

- 开始工作前验证项目记忆，并用 live Git、进程和硬件状态纠正任何过期内容。
- 保持修改范围最小，保留用户文件和本地硬件数据；只清理明确生成的缓存和构建产物。
- 结束前更新 project-memory.json，执行 render、validate、git diff 检查，并按维护者授权决定提交、合并或推送。
