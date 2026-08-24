# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-24T16:06:02+08:00`
- 分支：`master`
- HEAD：`5f501a5 docs: qualify v0.1.7 STM32F103RE candidate`
- 远端 HEAD：`origin/master`
- 工作树：v0.1.7 最终候选已通过；正在删除被当前报告取代的旧 PR/Task 流水账并准备正式发布提交。
- 当前任务：清理过期验证流水账，从最终 release commit 重新生成签名 NSIS、公开 Skill 和 Site Agent，并发布 GitHub/Gitee。
- 状态：`v0.1.7-release-authorized`

## 里程碑

- **v0.1.7 运行时** — `complete`。首次连接、在线读取回烧、RTT/SuperWatch 保存、RTOS Trace、MicroLink/HPMLink 固件升级、托盘和响应式界面修复已完成。
- **桌面与 Web 一致性** — `complete`。Web 与 Tauri 共享 Vue 前端和 FastAPI 能力，客户端连接与后端生命周期互不干扰。
- **SystemView Timeline** — `complete`。连续跟随、首屏稳定刷新、缩放跟随和可见区间累计缓存已在最新修复分支实现。

## 验证证据

- **v0.1.7 STM32F103RE 最终候选**：工程目录虽保留 STM32F103RC 历史名，物理芯片、Keil 和在线烧录均按 STM32F103RE 验证。Keil 0 错误 0 警告；Python 1371 项通过、1 项跳过，12 项仅因 Windows 无目录 symlink 权限失败；GUI 57 文件/582 项、生产构建和 NSIS 打包通过。真机完成原生/在线/脱机烧录、AXF 符号、RAM 读写、RTT 双向、64 点 SuperWatch、VOFA、SystemView、受控 HardFault 与恢复、固件检查、探针重启和资源释放。安装态 sidecar 无 Python 子进程，加载 4184 个符号并从 RAM 读回构建标识 20260824，关闭后进程与端口释放。候选安装包 75042164 字节，SHA-256 e7c4e05eafc671a9418fda921ab1ad1ef8d15f76807fbbc45559cc1235ef0809。
- **HIL v0.2 上游同步**：选择性移植 su5176/master 的 fbaac61 与 9cba616，不导入上游项目记忆；acquire/release/renew 统一进入元数据 guard，同时保留同机死亡进程锁回收。无人值守协议只开放 observe/debug.read，memory/register/variable 在连接前验证目标参数和 VID/PID/序列号/locator。HIL/探针控制聚焦 27 项通过；Python 全量 1371 项通过、1 项跳过，12 项仅因 Windows 无目录 symlink 权限失败；GUI 57 文件/582 项及 TypeScript/Vite 生产构建通过。真机完成 identify/capabilities/health/safe_state/plugin-version、HPM5301 只读 4 字节、身份不匹配拒绝和锁释放闭环。
- **Skill 上下文隔离**：维护与 Tauri 构建 Skill 在 OpenAI 配置中禁止隐式调用；跨模型公开 Skill 归档使用运行时内容白名单，拒绝维护内容混入。相关 Python 19 项通过；Python 全量 1351 项通过、1 项跳过，12 项仅因 Windows 无目录 symlink 权限失败；GUI 57 文件/582 项及 TypeScript/Vite 生产构建通过。白名单归档约 3.15 MB，相比 v0.1.6 发布包减少 44.6%。本地替换后可发现 Skill 从 3 个降为 1 个：发现元数据从 476 降至 359 o200k tokens（-24.6%），全部可加载 Skill 正文从 7,711 降至 5,385（-30.2%），额外维护 Skill 2,286 tokens 和维护说明语料 6,640 tokens 均完全移除；用户运行 Skill 正文仍保留 5,385 tokens。
- **HPMLink V4 固件升级**：HPMLink_V4.3.7.uf2 为 1,520,128 字节、2,969 个合法 UF2 块；V4.3.6 HPM 下载器的 MICROKEEN 盘检测到 STARTUP_ANIMATION.zhrgb 后只选择 HPMLink_V4.3.7.uf2，自动进入 Bootloader、复制、重新枚举并回读 V4.3.7，返回 updated。升级后 FastAPI 实际连接/升级/断开路径返回 up_to_date 且固件仍为 HPMLink。Python 固件升级 14 项、GUI 相关 34 项、GUI 全量 582 项及生产构建通过；Python 全量 1357 项通过、1 项跳过，12 项仅因 Windows 无目录 symlink 权限失败。

## 架构决策

- 每个独立问题单独提交并推送，便于回退。
- Web-entry 遇到 API-only 端口必须跳过并继续扫描，不能误杀 AI 或其他 GUI 后端。
- HPM 目标使用设备端 ROM API，不加载 FLM；HPM Flash 映射基址为 0x80000000。
- HPM 在线读取优先采用有限范围的 cmd.dump_memory 一次性二进制帧，按目标边界分块、校验 CRC/region error 并显式退出；cmd.read_flash 只作旧固件回退或诊断。
- AI CLI、Web GUI 和 Tauri 各自持有连接与后端生命周期。
- 普通用户只获得 mklink-ai-probe 运行时 Skill；维护与桌面构建 Skill 保留在源码仓库且只允许显式调用。
- 正式 Skill 发布包必须由 prepare_release.py 从来源提交按公开白名单生成；外部预制包也必须通过同一白名单校验。
- 探针固件选择必须同时匹配硬件代际和产品族：仅 V4 且 MICROKEEN 根目录存在 STARTUP_ANIMATION.zhrgb 时使用 HPMLink；其他情况继续使用 MicroLink。
- HIL 锁的所有权校验、回收、创建、续租和释放由同一 guard 串行化并保留同机死亡进程回收；v0.2 无人值守面只开放 lifecycle 与 observe/debug.read，无效动作、目标、参数或设备身份必须在连接前拒绝。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4；HPMLink V4 下载器已升级并回读 V4.3.7。交接不记录端口或完整探针标识。
- **target**：实际 STM32F103RE 可用于任意修改测试代码和破坏性烧录闭环；工程目录名 STM32F103RC 仅为历史命名。HPM5301 已完成 HIL 插件 4 字节只读闭环。
- **permission**：维护者已授权 v0.1.7 正式签名、标签、GitHub/Gitee Release、双端 master 同步和 updates 分支发布；VCC 仍需逐次确认具体电压。

## 下一动作

1. 完成 v0.1.7 GitHub/Gitee 正式发布并匿名复核更新清单与下载资产。
2. 如要补齐串口、Modbus 或 VCC 真机项，先提供已确认的串口/RS-485 接线或明确 VCC 电压。

## 已知限制

- 当前 Windows 账户不能创建目录 symlink，相关安全测试需在有权限环境复测。
- 串口 TX/RX 与 Modbus RTU 缺少已确认的物理回环/从站，不能把自动化测试替代为真机 PASS。
- v0.1.7 候选安装包没有 Windows Authenticode 签名；桌面辅助控制通道不可用，桌面共享前端已通过浏览器交互、安装态通过进程和 API 独立验证。
- HPM 旧固件若不支持 dump_memory，将按一次请求回退到较慢的 cmd.read_flash 文本读取；当前 V4.3.6 使用二进制路径。
- 高事件率 SystemView 仍可能造成目标 RTT 缓冲 Overflow；前端不能恢复目标已丢失事件。

## 延续协议

- 开始前校正 Git、进程和硬件状态。
- 不提交固件、Pack、FLM、日志、截图、硬件标识或构建缓存。
- 结束前执行全量门禁、project-memory render/validate、git diff --check，并保持工作树干净。
