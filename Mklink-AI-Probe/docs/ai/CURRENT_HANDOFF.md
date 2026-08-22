# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-22T14:00:00+08:00`
- 分支：`fix/systemview-timeline-smooth-refresh`
- HEAD：`SystemView Timeline 可见区间累计缓存修复已完成。`
- 远端 HEAD：`origin/fix/systemview-timeline-smooth-refresh`
- 工作树：源码和记忆可提交；gui/dist 等本地构建产物已清理。
- 当前任务：为在线下载选择 HPM Flash 读取 API；尚未修改运行时代码，等待维护者确认实施方案。
- 状态：`hpm-online-read-api-selection`

## 里程碑

- **v0.1.7 运行时** — `complete`。首次连接、在线读取回烧、RTT/SuperWatch 保存、RTOS Trace、固件升级、托盘和响应式界面修复已完成。
- **桌面与 Web 一致性** — `complete`。Web 与 Tauri 共享 Vue 前端和 FastAPI 能力，客户端连接与后端生命周期互不干扰。
- **SystemView Timeline** — `complete`。连续跟随、首屏稳定刷新、缩放跟随和可见区间累计缓存已在最新修复分支实现。

## 验证证据

- **自动化门禁**：最新分支 GUI 56 文件/574 项、Vite 生产构建和 Python 1331 项通过；12 项 symlink 用例仅受当前 Windows 权限限制。
- **真机闭环**：V3/STM32F103RC 完成 Flash 读取、擦除、编程、校验、复位和断开；Chrome Web GUI 验证 RTT/SuperWatch 保存与 SystemView 持续更新。
- **HPM API 源码审查**：cmd.read_flash 与 cmd.dump_memory 最终都调用 riscv_debug_sysbus_read_mem；前者每 16 字节输出文本并延时 1 ms，后者以 512 字节读取、2048 字节分块和 CRC 二进制帧输出。

## 架构决策

- 每个独立问题单独提交并推送，便于回退。
- HPM 目标使用设备端 ROM API，不加载 FLM；HPM Flash 映射基址为 0x80000000。
- HPM 在线读取推荐采用 cmd.dump_memory 的一次性二进制帧模式；cmd.read_flash 保留为旧固件兼容回退或诊断路径。
- dump_memory 必须由上位机封装为有限范围的一次性读取，按目标边界分块、校验 CRC/region error，并显式退出流模式。
- AI CLI、Web GUI 和 Tauri 各自持有连接与后端生命周期。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4；交接不记录端口或完整探针标识。
- **target**：STM32F103RC 可用于破坏性烧录闭环；HPM 工程用于后续真实读取验证。
- **permission**：维护者要求每个问题独立提交；本轮不发布正式 v0.1.7。

## 下一动作

1. 维护者确认 HPM 在线读取采用 dump_memory 一次性二进制方案。
2. 在独立 fix 分支实现 HPM 分块读取、CRC/错误处理、进度日志和 ARM 回归兼容。
3. 使用真实 HPM 板完成 Web/Tauri/安装包读取与保存闭环，再提交并推送。

## 已知限制

- 当前 Windows 账户不能创建目录 symlink，相关安全测试需在有权限环境复测。
- HPM 在线读取当前仍被后端显式拒绝，尚未实现 dump_memory 一次性读取适配。
- 高事件率 SystemView 仍可能造成目标 RTT 缓冲 Overflow；前端不能恢复目标已丢失事件。

## 延续协议

- 开始前校正 Git、进程和硬件状态。
- 不提交固件、Pack、FLM、日志、截图、硬件标识或构建缓存。
- 结束前执行全量门禁、project-memory render/validate、git diff --check，并保持工作树干净。
