# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-20T23:39:48+08:00`
- 分支：`fix/systemview-live-zoom`
- HEAD：`f3785e8 包含 v0.1.7 修复、先楫淘宝入口和简短版本说明；等待交接精简提交及合并。`
- 远端 HEAD：`origin/fix/systemview-live-zoom 已推送至 f3785e8；origin/master 与本地 master 一致，尚未合并。`
- 工作树：运行时代码已提交；保留维护者的 V3.3.7/V4.3.6 固件替换、生产 gui/dist、Cargo 换行及本地构建产物，不纳入源码提交。
- 当前任务：v0.1.7 修复和最终门禁完成，远程固件资产可用；精简交接后合并并推送 master。
- 状态：`v0.1.7_merge_ready`

## 里程碑

- **v0.1.7 运行时** — `complete`。首次连接、在线读取回烧、RTT/SuperWatch 保存、RTOS Trace、固件升级、托盘和响应式界面修复完成。
- **桌面与 Web 一致性** — `complete`。共享 Vue 前端和 FastAPI 能力；Tauri 使用内置 sidecar，客户端生命周期与端口互不干扰。
- **固件分发** — `complete`。V3.3.7/V4.3.6 作为 v0.1.6 Release 资产托管，不提交 UF2 到 Git。

## 验证证据

- **最终自动化门禁**：GUI 55 文件/547 项、Vite 生产构建、Rust 12 项与 cargo check 通过。Python 为 1319 passed、1 skipped；另 12 项仅因当前 Windows 账户无目录符号链接权限（WinError 1314）无法建立测试前置条件。
- **安装包真机读写**：标准 NSIS 覆盖安装后 health 与探针接口正常，进程树无 Python。V3/STM32F103RC 完成 512 KiB 读取、256 个 2 KiB 扇区解析、擦除、编程、全量 verify、复位和断开；读取 7.581 秒，作业 27.544 秒。
- **桌面保存与界面修复**：维护者在覆盖安装版确认 SuperWatch CSV 与原始日志均可保存。组件回归覆盖连接错误关闭、在线读取后烧录、基地址窄窗布局、清空用户文件和读取向上箭头。
- **实时调试**：真实 V3 数据流验证 RTOS Trace 持续滚动、缩放后实时刷新、泳道高度稳定；RTT 停止恢复与 CMD 残留命令清理均完成真机闭环。
- **远程固件**：GitHub latest Release 可发现 V3.3.7/V4.3.6，远程下载大小与 SHA-256 均匹配本地。覆盖安装版连接真实 V3 后正确返回 current/latest V3.3.7 的 up_to_date，并主动断开。
- **分发候选**：基于 ddcb6c3 的标准 NSIS 已覆盖安装验证，SHA-256 为 F89C6AD3B63C7F16F349482C37EB52FAB0A6AB4CFCB9D0C34A6CEE881BAFBE99；本轮新增店铺链接和版本文案由最新 GUI 全量门禁覆盖，未发布正式资产。

## 架构决策

- 每个独立问题完成验证后单独提交并推送，方便按问题回退。
- HPM 目标只使用 ROM API；ELF/DWARF 默认使用内置 pyelftools。
- AI CLI、Web GUI 和 Tauri 各自持有连接与后端生命周期，关闭一个客户端不影响其他客户端。
- SystemView Timeline 以最新事件为右边界连续滚动，30 FPS 上限，泳道容量只增不减；拖拽才退出跟随。
- 固件升级优先 GitHub、失败回退 Gitee 和本地 MK-Firmware；远程 UF2 使用 Release 资产，不进入 Git 历史。
- GUI 不提供 VCC 控件；AI 设置任意电压都需本次明确确认，5V 还需额外确认。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4；交接不记录端口或完整设备标识。
- **target**：STM32F103RC 测试工程可用于破坏性烧录闭环；HPM 与其他 ARM 板按任务选择。
- **permission**：维护者授权推送当前修复分支、上传 V3.3.7/V4.3.6 固件资产并合并推送 master；未授权发布 v0.1.7、签名、打标签、更新 latest.json 或同步 Gitee。

## 下一动作

1. 提交精简交接，快进合并到 master 并推送 GitHub。
2. 仅在维护者明确授权后创建 v0.1.7 标签、Release、签名资产并更新 latest.json/Gitee。
3. 后续在干净 Windows 和 Linux/macOS 环境扩大安装更新与 USB Web Entry 验证。

## 已知限制

- 当前 Windows 账户不能创建目录符号链接，12 个上传路径重定向安全测试无法运行 symlink 分支；junction 分支通过。
- Chrome 控制无法验证 localhost 管理策略，Computer Use native pipe 不存在；安装包原生保存由维护者手动验收。
- V4.3.6 已完成远程发现、下载和哈希验证，但本轮未连接 V4 做 Bootloader 升级。
- 高事件率 SystemView 仍可能溢出目标 RTT 缓冲。

## 延续协议

- 开始前用 Git、进程和硬件状态校正项目记忆。
- 项目记忆只保留当前事实；历史证据使用 Git 提交查询。
- 不提交固件、Pack、FLM、日志、硬件标识、凭据或构建缓存。
- 结束前执行全量门禁、render、validate 和 git diff --check。
