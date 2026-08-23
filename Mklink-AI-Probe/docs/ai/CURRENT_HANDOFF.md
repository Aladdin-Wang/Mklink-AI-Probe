# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-23T13:45:00+08:00`
- 分支：`master`
- HEAD：`1e97790 fix-sync-skill-plugin-version`
- 远端 HEAD：`origin/master`
- 工作树：桌面/Web/MCP 串口生命周期和 Skill 版本一致性修复已合并并推送 master；已合并修复分支已清理，主分支安装包与本地 Skill 已更新。
- 当前任务：已完成 master 合并、修复分支清理、0.1.7 NSIS 候选包重建和本地 Skill 同步。
- 状态：`master-lifecycle-package-skill-synced`

## 里程碑

- **v0.1.7 运行时** — `complete`。首次连接、在线读取回烧、RTT/SuperWatch 保存、RTOS Trace、固件升级、托盘和响应式界面修复已完成。
- **桌面与 Web 一致性** — `complete`。Web 与 Tauri 共享 Vue 前端和 FastAPI 能力，客户端连接与后端生命周期互不干扰。
- **SystemView Timeline** — `complete`。连续跟随、首屏稳定刷新、缩放跟随和可见区间累计缓存已在最新修复分支实现。

## 验证证据

- **自动化门禁**：GUI 57 文件/579 项和 Vite 生产构建通过；数组采样相关 Python 回归 64 项通过；Python 全量测试在当前 Windows symlink 权限用例处因当前 Windows symlink 权限场景长时间无输出而中止。
- **真机闭环**：安装包 sidecar 真机闭环：在线烧录完成擦除/编程/校验/复位；脱机 U 盘下载返回 completed；Memory 读取返回 16 字节；HardFault 返回 null；SuperWatch 数组快照 64 点、序号持续递增。为闭环验证 RTT/SystemView，STM32F103RC 测试固件已启用持续 RTT 心跳和 SystemView 任务，按新 AXF 的 _SEGGER_RTT 地址读取：RTT 解析 33 行，SystemView 5 秒收到 18,758 个事件并识别 14 个任务。
- **HPM API 源码审查**：cmd.read_flash 与 cmd.dump_memory 最终都调用 riscv_debug_sysbus_read_mem；前者每 16 字节输出文本并延时 1 ms，后者以 512 字节读取、2048 字节分块和 CRC 二进制帧输出。
- **HPM 真机读取**：V4.3.6/HPM5301 连续读取 32 KiB、64 KiB、512 KiB 成功；直连后端和 FastAPI Web API 返回长度、SHA-256、首尾数据一致。目标空白区域返回 FF 属于实际 Flash 内容。
- **HPM 在线烧录**：HPM ROM 擦除状态延迟到首个有效编程进度后收尾；校验显示分块进度；Python 在线烧录回归测试 139 项通过。
- **主分支安装包与启动入口**：master 合并提交 8fd428a 已推送 GitHub；NSIS 安装包覆盖安装并由独立 sidecar 健康检查通过；U 盘 G: 的 MKLink Web GUI.html 已更新并打开。
- **SuperWatch 数组快照范围**：支持一维标量数组按起始索引和数量读取，最大 4096 个元素；数组快照已接入普通 FIELDS 曲线体系，图例、隐藏、分离/合并与普通变量共用。catalog generation 在停止/重绑竞态下会自动刷新并重试展开；完整 GUI 579 项、数组相关 Python 64 项和生产构建通过。STM32F103RC 测试固件包含 64 点正弦、谐波和三角波叠加数组，真机采样持续更新。
- **串口生命周期回归**：Python 40 项、GUI 57 文件/580 项和 Skill 更新器 11 项通过；Web 最后一个浏览器会话、Tauri 关闭窗口、MCP stdio 退出均释放 Device/sidecar。最终 master 生成 0.1.7 x64 NSIS 候选包到工作区外层 release；本地 Skill 的包/插件版本均为 0.1.7，来源提交和 GUI/MCP 依赖验证通过。

## 架构决策

- 每个独立问题单独提交并推送，便于回退。
- Web-entry 遇到 API-only 端口必须跳过并继续扫描，不能误杀 AI 或其他 GUI 后端。
- HPM 目标使用设备端 ROM API，不加载 FLM；HPM Flash 映射基址为 0x80000000。
- HPM 在线读取推荐采用 cmd.dump_memory 的一次性二进制帧模式；cmd.read_flash 保留为旧固件兼容回退或诊断路径。
- dump_memory 必须由上位机封装为有限范围的一次性读取，按目标边界分块、校验 CRC/region error，并显式退出流模式。
- AI CLI、Web GUI 和 Tauri 各自持有连接与后端生命周期。
- NSIS 候选构建临时使用 zlib，避免 LZMA mmap 在系统盘空间紧张时失败。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4；交接不记录端口或完整探针标识。
- **target**：STM32F103RC 可用于破坏性烧录闭环；HPM 工程用于后续真实读取验证。
- **permission**：维护者要求每个问题独立提交；本轮合并主分支并覆盖本地安装，不发布正式 v0.1.7。

## 下一动作

1. 正式发布仍需维护者明确授权。

## 已知限制

- 当前 Windows 账户不能创建目录 symlink，相关安全测试需在有权限环境复测。
- HPM 旧固件若不支持 dump_memory，将按一次请求回退到较慢的 cmd.read_flash 文本读取；当前 V4.3.6 使用二进制路径。
- 高事件率 SystemView 仍可能造成目标 RTT 缓冲 Overflow；前端不能恢复目标已丢失事件。

## 延续协议

- 开始前校正 Git、进程和硬件状态。
- 不提交固件、Pack、FLM、日志、截图、硬件标识或构建缓存。
- 结束前执行全量门禁、project-memory render/validate、git diff --check，并保持工作树干净。
