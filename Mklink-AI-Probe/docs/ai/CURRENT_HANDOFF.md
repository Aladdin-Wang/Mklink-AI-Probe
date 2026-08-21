# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-21T23:59:00+08:00`
- 分支：`fix/systemview-timeline-smooth-refresh`
- HEAD：`SystemView Runtime 统计按保留环形历史累计，Timeline 视口更新保留连续数据边界；Overflow 丢包边界不再伪造长任务区间。`
- 远端 HEAD：`origin/fix/systemview-timeline-smooth-refresh 尚未同步本轮 Runtime/Timeline 累计修复；尚未合并 master。`
- 工作树：Runtime/Timeline 源码、测试和记忆已提交；保留本地生产 gui/dist 构建产物未纳入提交。
- 当前任务：修复 SystemView Runtime 随可见窗口重算，以及 Timeline 随视口响应重置时间边界的问题。
- 状态：`systemview_cumulative_runtime_verified`

## 里程碑

- **v0.1.7 运行时** — `complete`。首次连接、在线读取回烧、RTT/SuperWatch 保存、RTOS Trace、固件升级、托盘和响应式界面修复完成；读取数据回烧现可显示真实字节进度并在完成后保持烧录状态。
- **桌面与 Web 一致性** — `complete`。共享 Vue 前端和 FastAPI 能力；Tauri 使用内置 sidecar，客户端生命周期与端口互不干扰。
- **固件分发** — `complete`。V3.3.7/V4.3.6 作为 GitHub v0.1.6 Release 资产托管，不提交 UF2 到 Git；自动升级失败后可由 Web/Tauri 保存对应 UF2。

## 验证证据

- **最终自动化门禁**：Timeline/调度器/页面聚焦测试 51 项通过；GUI 56 文件/563 项和 Vite 生产构建通过。Python 1328 项通过、1 项跳过；仅 12 项因当前 Windows 账户无目录 symlink 权限失败，junction 分支通过。
- **安装包真机读写**：标准 NSIS 覆盖安装后 health 与探针接口正常，进程树无 Python。V3/STM32F103RC 完成 512 KiB 读取、256 个 2 KiB 扇区解析、擦除、编程、全量 verify、复位和断开；读取 7.581 秒，作业 27.544 秒。
- **桌面保存与界面修复**：Chrome Web GUI 8766 连接真实 V3/STM32F103RC，按器件默认范围读取 256 KiB（128 个 2 KiB 分块），原样擦除、编程、校验、复位并断开成功；运行中显示 PROGRAMMING/44% 和真实 [PROGRAM] 字节日志，结束后保持烧录完成/100%。读取弹窗已确认使用向上图标。
- **实时调试**：新增修复：SystemView 流按 Worker 确认串行投递帧，visible-range 请求可插入高事件率数据流，不再被数千个帧请求堵塞。GUI 56 文件/566 项和生产构建通过；Chrome/HPM 真机事件持续增长且 Timeline 不再空白。
- **Overflow 处理**：确认 HPM 目标端 SEGGER SystemView 使用 10 KiB RTT 上行缓冲，而探针 systemView.c 每次最多搬运 1024 字节；高事件率下 Overflow 是目标缓冲溢出，不是 StreamHub 或浏览器丢包。解析器收到 Overflow 后清除缓存任务上下文，GUI 单独显示 Target Overflow；Python 解析器 6 项、Worker/SystemView 页面 84 项聚焦测试通过。Chrome 通过 COM55 重启最新构建后，使用已验证 RTT 地址 0x00087100，Events 从 12,925 持续增长到 243,745，Timeline 持续更新；Target Overflow 从 496 增长到 9,357。错误的自动搜索地址 0x20000ad0 会导致 Recorder 握手超时。
- **Runtime/Timeline 累计修复**：Worker Context 汇总改为遍历整个保留 interval ring，不再按 visible range 裁剪；SvTimeline 对可见区间响应保留累计 tMin/tMax、任务元数据和已有数据状态，空视口响应也不会触发下一帧首次定位。GUI 56 文件/570 项测试、Vite 生产构建通过；Chrome + COM55 + HPM 真机 Runtime Idle 调度从 14,094 增长到 62,533、MTimer 从 14,092 增长到 62,507，Timeline 泳道高度保持 326px 且时间轴持续推进。
- **远程固件**：真实 8770 API 从 GitHub 下载 V3.3.7 共 771072 字节，SHA-256 与本地完全匹配；回归测试确认 GitHub 文件成功时不访问 Gitee，失败时才查询并下载同版本 Gitee 资产。
- **固件人工下载界面**：Chrome 连接真实探针后安全释放；隔离测试实例实际显示自动升级未完成、最新 V4.3.6 和下载固件按钮，截图确认布局无重叠。Web 使用文件保存选择器，Tauri 复用原生保存框。

## 架构决策

- 每个独立问题完成验证后单独提交并推送，方便按问题回退。
- HPM 目标只使用 ROM API；ELF/DWARF 默认使用内置 pyelftools。
- AI CLI、Web GUI 和 Tauri 各自持有连接与后端生命周期，关闭一个客户端不影响其他客户端。
- SystemView Timeline 以最新事件为右边界连续滚动；Runtime/Context 统计基于 Worker 保留的完整 interval ring，只有环形缓存淘汰历史时才减少；visible-range 仅负责绘制候选，不得重置累计时间边界和任务泳道元数据。后端按约 30 FPS 交付且底层流读取最多等待 10 ms。前端只由一个 continuous 调度器绘制，按实际输出区间/事件数和实测绘制成本在 60/30/20 FPS 间自适应；Worker 可见范围请求只允许一个在途请求并合并后续最新范围，避免 HPM 高事件率积压。
- 固件升级优先 GitHub；GitHub 文件下载失败后才查询并切换 Gitee，同版本远程 UF2 使用 Release 资产且不进入 Git 历史。
- 自动升级未完成且已识别型号时必须返回最新版本、文件名和人工下载能力；下载端点只接受 V3/V4，不接收任意 URL。
- GUI 不提供 VCC 控件；AI 设置任意电压都需本次明确确认，5V 还需额外确认。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4；交接不记录端口或完整设备标识。
- **target**：STM32F103RC 测试工程可用于破坏性烧录闭环；HPM 与其他 ARM 板按任务选择。
- **permission**：维护者确认按方案 1 修复，并要求每个问题独立提交和推送；本轮不发布 v0.1.7、不签名、不打标签、不更新 latest.json、不同步 Gitee。

## 下一动作

1. 由维护者在探针固件中扩大 RTT_MAX_BUFFER_SIZE、单次批量读取并验证 USB TX ring 后重新烧录，观察 HPM FreeRTOS Overflow 计数是否归零。
2. 后续在干净 Windows 和 Linux/macOS 环境扩大安装更新与 USB Web Entry 验证。

## 已知限制

- 当前 Windows 账户不能创建目录符号链接，12 个上传路径重定向安全测试无法运行 symlink 分支；junction 分支通过。
- 安装包原生保存已由维护者手动验收；本轮 Web 文件选择器由自动化覆盖。
- Gitee v0.1.6 Release 当前没有 V3.3.7/V4.3.6 UF2 资产；代码会尝试 Gitee 并明确报错，但真实 Gitee 下载要等维护者同步同版本资产。
- V4.3.6 已完成远程发现、下载和哈希验证，但本轮未连接 V4 做 Bootloader 升级。
- 高事件率 SystemView 仍可能溢出目标 RTT 缓冲；需要在探针固件中提高单次 RTT 搬运量、批量 drain 并确认 USB TX 队列吞吐，不能由前端补回已经丢失的事件。Runtime/Timeline 累计修复已在 Chrome + COM55 + HPM 真机验证；目标 Overflow 仍属于吞吐限制。

## 延续协议

- 开始前用 Git、进程和硬件状态校正项目记忆。
- 项目记忆只保留当前事实；历史证据使用 Git 提交查询。
- 不提交固件、Pack、FLM、日志、硬件标识、凭据或构建缓存。
- 结束前执行全量门禁、render、validate 和 git diff --check。
