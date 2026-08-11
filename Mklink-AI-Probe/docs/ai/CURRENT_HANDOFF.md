# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-08-11T22:30:45+08:00`
- 分支：`master`
- HEAD：`v0.1.6 标签固定于 2f65f92c98；master 仅追加发布后交接。`
- 远端 HEAD：`GitHub master、v0.1.6 标签和正式 Release 已同步。`
- 工作树：仅保留当前主工作树；发布资产位于工作区 release 目录且不进入 Git。
- 当前任务：v0.1.6 已完成构建、安装验证和正式发布。
- 状态：`v016_released`

## 里程碑

- **产品与分发** — `complete`。Python、Skill、Web GUI 和 Tauri 版本统一为 v0.1.6，标准 NSIS 使用内置 sidecar。
- **烧录与兼容性** — `complete`。在线/脱机烧录、HPM ROM API、Pack/FLM、固件刷新、复合探针和扇区解析已集成。
- **调试与数据流** — `complete`。Memory、RTT、SystemView、VOFA、串口和 Modbus 共用资源仲裁与轻量流通道。
- **多实例与远程** — `complete`。每个桌面实例使用独立后端和探针连接；Site Agent 支持认证直连与 LAN STCP。

## 验证证据

- **v0.1.6 运行时**：GUI 518 项、配置页 22 项和连接后端 12 项通过；Python 可比门禁 1262 项通过、1 项跳过。真实 Chrome、独立 Web 后端、下载器和 HPM5301 完成自动搜索、错误端口回退和再次连接闭环。
- **烧录与数据流**：HPM 在线烧录自动运行、重复固件加载、浏览器文件刷新和客户 HEX 解析已验证；串口/RTT 高吞吐与下载器 V2/V3/V4 数据完整性完成真机验证。
- **v0.1.6 正式分发**：七项资产哈希复算通过；正式 NSIS 已覆盖安装，健康与探针接口、内置 sidecar、零 Python 子进程、正常退出和动态端口释放通过。本地 Skill 指向 2f65f92c98；GitHub/Gitee Release、标签和 updates/latest.json 已核对一致。

## 架构决策

- 历史端口是软偏好，可回退自动发现；当前会话手选端口首次保持严格约束，失败后切回自动搜索。
- 运行时修改在 fix/feature 分支完成全量测试、生产构建、项目记忆和真机闭环后合并。
- HPM 目标只使用 ROM API；ELF/DWARF 默认使用内置 pyelftools。
- Dashboard 与烧录/调试操作共用资源租约；复位前停止 RTT、SuperWatch、VOFA 和 SystemView。
- 串口和 RTT 终端使用独立 Worker 与有界缓冲；终端模式不维护隐藏日志。
- 每个 Tauri 实例拥有独立 sidecar、动态端口和探针锁；正式发布默认只生成标准 NSIS。

## 真机环境

- **probe**：维护机可使用 V2/V3/V4 下载器；交接不记录端口或完整设备标识。
- **target**：ARM 与 HPM 真机可用；部分客户芯片仅完成 Pack/HEX 软件验证。
- **permission**：维护者已明确授权本次 v0.1.6 GitHub/Gitee 正式发布；破坏性烧录仍需单独授权。

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
