# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-24T14:26:41+08:00`
- 分支：`master`
- HEAD：`59fd92b docs: qualify guarded HIL v0.2 sync`
- 远端 HEAD：`origin/master`
- 工作树：su5176/master 的 HIL 元数据 guard 与 v0.2 只读插件已选择性同步到 master；本地死亡进程锁回收和连接前安全校验保持有效。
- 当前任务：HIL v0.2 只读插件与跨客户端锁 guard 已选择性同步并合并 master，通过自动化门禁和 HPM5301 真机只读闭环。
- 状态：`hil-v02-upstream-sync-merged`

## 里程碑

- **v0.1.7 运行时** — `complete`。首次连接、在线读取回烧、RTT/SuperWatch 保存、RTOS Trace、MicroLink/HPMLink 固件升级、托盘和响应式界面修复已完成。
- **桌面与 Web 一致性** — `complete`。Web 与 Tauri 共享 Vue 前端和 FastAPI 能力，客户端连接与后端生命周期互不干扰。
- **SystemView Timeline** — `complete`。连续跟随、首屏稳定刷新、缩放跟随和可见区间累计缓存已在最新修复分支实现。

## 验证证据

- **HIL v0.2 上游同步**：选择性移植 su5176/master 的 fbaac61 与 9cba616，不导入上游项目记忆；acquire/release/renew 统一进入元数据 guard，同时保留同机死亡进程锁回收。无人值守协议只开放 observe/debug.read，memory/register/variable 在连接前验证目标参数和 VID/PID/序列号/locator。HIL/探针控制聚焦 27 项通过；Python 全量 1371 项通过、1 项跳过，12 项仅因 Windows 无目录 symlink 权限失败；GUI 57 文件/582 项及 TypeScript/Vite 生产构建通过。真机完成 identify/capabilities/health/safe_state/plugin-version、HPM5301 只读 4 字节、身份不匹配拒绝和锁释放闭环。
- **Skill 上下文隔离**：维护与 Tauri 构建 Skill 在 OpenAI 配置中禁止隐式调用；跨模型公开 Skill 归档使用运行时内容白名单，拒绝维护内容混入。相关 Python 19 项通过；Python 全量 1351 项通过、1 项跳过，12 项仅因 Windows 无目录 symlink 权限失败；GUI 57 文件/582 项及 TypeScript/Vite 生产构建通过。白名单归档约 3.15 MB，相比 v0.1.6 发布包减少 44.6%。本地替换后可发现 Skill 从 3 个降为 1 个：发现元数据从 476 降至 359 o200k tokens（-24.6%），全部可加载 Skill 正文从 7,711 降至 5,385（-30.2%），额外维护 Skill 2,286 tokens 和维护说明语料 6,640 tokens 均完全移除；用户运行 Skill 正文仍保留 5,385 tokens。
- **真机闭环**：安装包 sidecar 真机闭环：在线烧录完成擦除/编程/校验/复位；脱机 U 盘下载返回 completed；Memory 读取返回 16 字节；HardFault 返回 null；SuperWatch 数组快照 64 点、序号持续递增。为闭环验证 RTT/SystemView，STM32F103RC 测试固件已启用持续 RTT 心跳和 SystemView 任务，按新 AXF 的 _SEGGER_RTT 地址读取：RTT 解析 33 行，SystemView 5 秒收到 18,758 个事件并识别 14 个任务。
- **HPMLink V4 固件升级**：HPMLink_V4.3.7.uf2 为 1,520,128 字节、2,969 个合法 UF2 块；V4.3.6 HPM 下载器的 MICROKEEN 盘检测到 STARTUP_ANIMATION.zhrgb 后只选择 HPMLink_V4.3.7.uf2，自动进入 Bootloader、复制、重新枚举并回读 V4.3.7，返回 updated。升级后 FastAPI 实际连接/升级/断开路径返回 up_to_date 且固件仍为 HPMLink。Python 固件升级 14 项、GUI 相关 34 项、GUI 全量 582 项及生产构建通过；Python 全量 1357 项通过、1 项跳过，12 项仅因 Windows 无目录 symlink 权限失败。
- **HPM 真机读取**：V4.3.6/HPM5301 连续读取 32 KiB、64 KiB、512 KiB 成功；直连后端和 FastAPI Web API 返回长度、SHA-256、首尾数据一致。目标空白区域返回 FF 属于实际 Flash 内容。
- **主分支安装包与启动入口**：提交 338ff90 的 0.1.7 NSIS 候选包归档于 release/2026-08-23_1435_338ff90；SHA-256 复核通过并覆盖安装。安装后 WebView 构建指纹为 338ff90b8920，健康与探针枚举正常、无外部 Python 子进程，正常关闭后 MKLink 进程和 8765–8799 端口全部释放。
- **SuperWatch 数组快照范围**：支持一维标量数组按起始索引和数量读取，最大 4096 个元素；数组快照已接入普通 FIELDS 曲线体系，图例、隐藏、分离/合并与普通变量共用。catalog generation 在停止/重绑竞态下会自动刷新并重试展开；完整 GUI 579 项、数组相关 Python 64 项和生产构建通过。STM32F103RC 测试固件包含 64 点正弦、谐波和三角波叠加数组，真机采样持续更新。
- **串口生命周期回归**：Python 40 项、GUI 57 文件/580 项和 Skill 更新器 11 项通过；Web 最后一个浏览器会话、Tauri 关闭窗口、MCP stdio 退出均释放 Device/sidecar。最终 master 生成 0.1.7 x64 NSIS 候选包到工作区外层 release；本地 Skill 的包/插件版本均为 0.1.7，来源提交和 GUI/MCP 依赖验证通过。

## 架构决策

- 每个独立问题单独提交并推送，便于回退。
- Web-entry 遇到 API-only 端口必须跳过并继续扫描，不能误杀 AI 或其他 GUI 后端。
- HPM 目标使用设备端 ROM API，不加载 FLM；HPM Flash 映射基址为 0x80000000。
- HPM 在线读取优先采用有限范围的 cmd.dump_memory 一次性二进制帧，按目标边界分块、校验 CRC/region error 并显式退出；cmd.read_flash 只作旧固件回退或诊断。
- AI CLI、Web GUI 和 Tauri 各自持有连接与后端生命周期。
- NSIS 候选构建临时使用 zlib，避免 LZMA mmap 在系统盘空间紧张时失败。
- 普通用户只获得 mklink-ai-probe 运行时 Skill；维护与桌面构建 Skill 保留在源码仓库且只允许显式调用。
- 正式 Skill 发布包必须由 prepare_release.py 从来源提交按公开白名单生成；外部预制包也必须通过同一白名单校验。
- 探针固件选择必须同时匹配硬件代际和产品族：仅 V4 且 MICROKEEN 根目录存在 STARTUP_ANIMATION.zhrgb 时使用 HPMLink；其他情况继续使用 MicroLink。
- HIL 锁的所有权校验、回收、创建、续租和释放由同一 guard 串行化并保留同机死亡进程回收；v0.2 无人值守面只开放 lifecycle 与 observe/debug.read，无效动作、目标、参数或设备身份必须在连接前拒绝。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4；HPMLink V4 下载器已升级并回读 V4.3.7。交接不记录端口或完整探针标识。
- **target**：STM32F103RC 可用于破坏性烧录闭环；HPM5301 已完成 HIL 插件 4 字节只读闭环。
- **permission**：维护者已授权选择性同步上游 master 的 HIL v0.2 功能、执行只读真机闭环、合并 master 并推送 GitHub；不发布正式 Release。

## 下一动作

1. 正式发布时把 HPMLink_V4.3.7.uf2 作为可下载固件资产。
2. 正式发布仍需维护者明确授权。

## 已知限制

- 当前 Windows 账户不能创建目录 symlink，相关安全测试需在有权限环境复测。
- HPM 旧固件若不支持 dump_memory，将按一次请求回退到较慢的 cmd.read_flash 文本读取；当前 V4.3.6 使用二进制路径。
- 高事件率 SystemView 仍可能造成目标 RTT 缓冲 Overflow；前端不能恢复目标已丢失事件。

## 延续协议

- 开始前校正 Git、进程和硬件状态。
- 不提交固件、Pack、FLM、日志、截图、硬件标识或构建缓存。
- 结束前执行全量门禁、project-memory render/validate、git diff --check，并保持工作树干净。
