# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-21T12:37:19+08:00`
- 分支：`fix/systemview-timeline-smooth-refresh`
- HEAD：`SystemView 后端保持约 30 FPS 交付；前端时间轴使用可调 60 FPS 连续渲染和平滑跟随，已移除旧的立即跳转条件。`
- 远端 HEAD：`origin/fix/systemview-timeline-smooth-refresh 将同步本轮 Timeline 立即跳转遗漏修复；尚未合并 master。`
- 工作树：仅保留 SystemView 前后端节奏源码、回归测试和项目记忆；生产 gui/dist、固件和本地测试前置均不纳入提交。
- 当前任务：修复 Timeline 遗留的立即窗口跳转；新数据只更新跟随目标，由 60 FPS 连续帧推进显示范围。
- 状态：`systemview_follow_jump_fixed`

## 里程碑

- **v0.1.7 运行时** — `complete`。首次连接、在线读取回烧、RTT/SuperWatch 保存、RTOS Trace、固件升级、托盘和响应式界面修复完成；读取数据回烧现可显示真实字节进度并在完成后保持烧录状态。
- **桌面与 Web 一致性** — `complete`。共享 Vue 前端和 FastAPI 能力；Tauri 使用内置 sidecar，客户端生命周期与端口互不干扰。
- **固件分发** — `complete`。V3.3.7/V4.3.6 作为 GitHub v0.1.6 Release 资产托管，不提交 UF2 到 Git；自动升级失败后可由 Web/Tauri 保存对应 UF2。

## 验证证据

- **最终自动化门禁**：本轮 Timeline、调度器和环形缓冲聚焦测试 33 项通过；此前 GUI 56 文件/558 项和 Vite 生产构建通过，Python 基线门禁未受影响。
- **安装包真机读写**：标准 NSIS 覆盖安装后 health 与探针接口正常，进程树无 Python。V3/STM32F103RC 完成 512 KiB 读取、256 个 2 KiB 扇区解析、擦除、编程、全量 verify、复位和断开；读取 7.581 秒，作业 27.544 秒。
- **桌面保存与界面修复**：Chrome Web GUI 8766 连接真实 V3/STM32F103RC，按器件默认范围读取 256 KiB（128 个 2 KiB 分块），原样擦除、编程、校验、复位并断开成功；运行中显示 PROGRAMMING/44% 和真实 [PROGRAM] 字节日志，结束后保持烧录完成/100%。读取弹窗已确认使用向上图标。
- **实时调试**：Chrome 5173 复测发现上一版仍有立即跳转；修复后页面源码已确认删除旧条件，真实截图中显示范围由帧循环推进，事件表折叠后泳道高度稳定。需维护者继续观察主观流畅度。
- **远程固件**：真实 8770 API 从 GitHub 下载 V3.3.7 共 771072 字节，SHA-256 与本地完全匹配；回归测试确认 GitHub 文件成功时不访问 Gitee，失败时才查询并下载同版本 Gitee 资产。
- **固件人工下载界面**：Chrome 连接真实探针后安全释放；隔离测试实例实际显示自动升级未完成、最新 V4.3.6 和下载固件按钮，截图确认布局无重叠。Web 使用文件保存选择器，Tauri 复用原生保存框。
- **分发候选**：基于 ddcb6c3 的标准 NSIS 已覆盖安装验证，SHA-256 为 F89C6AD3B63C7F16F349482C37EB52FAB0A6AB4CFCB9D0C34A6CEE881BAFBE99；本轮新增店铺链接和版本文案由最新 GUI 全量门禁覆盖，未发布正式资产。

## 架构决策

- 每个独立问题完成验证后单独提交并推送，方便按问题回退。
- HPM 目标只使用 ROM API；ELF/DWARF 默认使用内置 pyelftools。
- AI CLI、Web GUI 和 Tauri 各自持有连接与后端生命周期，关闭一个客户端不影响其他客户端。
- SystemView Timeline 以最新事件为右边界连续滚动；后端按约 30 FPS 交付且底层流读取最多等待 10 ms，前端 RenderScheduler 帧率可配置，RTOS Trace 默认 60 FPS continuous，时间轴用 100 ms ease 插值；新数据只更新跟随目标，不能直接覆盖显示范围，泳道容量只增不减；拖拽才退出跟随。
- 固件升级优先 GitHub；GitHub 文件下载失败后才查询并切换 Gitee，同版本远程 UF2 使用 Release 资产且不进入 Git 历史。
- 自动升级未完成且已识别型号时必须返回最新版本、文件名和人工下载能力；下载端点只接受 V3/V4，不接收任意 URL。
- GUI 不提供 VCC 控件；AI 设置任意电压都需本次明确确认，5V 还需额外确认。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4；交接不记录端口或完整设备标识。
- **target**：STM32F103RC 测试工程可用于破坏性烧录闭环；HPM 与其他 ARM 板按任务选择。
- **permission**：维护者确认按方案 1 修复，并要求每个问题独立提交和推送；本轮不发布 v0.1.7、不签名、不打标签、不更新 latest.json、不同步 Gitee。

## 下一动作

1. 审查并按需合并 fix/systemview-timeline-smooth-refresh；合并前若 master 前进，需更新分支并重跑最终门禁。
2. 后续在干净 Windows 和 Linux/macOS 环境扩大安装更新与 USB Web Entry 验证。

## 已知限制

- 当前 Windows 账户不能创建目录符号链接，12 个上传路径重定向安全测试无法运行 symlink 分支；junction 分支通过。
- 安装包原生保存已由维护者手动验收；本轮 Web 文件选择器由自动化覆盖。
- Gitee v0.1.6 Release 当前没有 V3.3.7/V4.3.6 UF2 资产；代码会尝试 Gitee 并明确报错，但真实 Gitee 下载要等维护者同步同版本资产。
- V4.3.6 已完成远程发现、下载和哈希验证，但本轮未连接 V4 做 Bootloader 升级。
- 高事件率 SystemView 仍可能溢出目标 RTT 缓冲。

## 延续协议

- 开始前用 Git、进程和硬件状态校正项目记忆。
- 项目记忆只保留当前事实；历史证据使用 Git 提交查询。
- 不提交固件、Pack、FLM、日志、硬件标识、凭据或构建缓存。
- 结束前执行全量门禁、render、validate 和 git diff --check。
