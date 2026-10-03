# 0.3.0 共享 CDC 后台与多下载器

本页对应 0.3.0 开发分支的第一阶段实现；现有正式安装版不会自动变成此版本。
底层仍使用原有 CDC，不需要更新下载器固件。

## 连接与选择

每个物理下载器拥有一个后台进程，GUI、MCP 和 `runtime call` 复用它。
两台下载器使用不同后台、设备连接、采集管理器和工程上下文。
同一下载器的多个窗口共享工程、符号和采集设置，不是独立硬件会话。
建议不同目标选择不同工程目录，避免同时编辑同一份工程配置文件。

```powershell
python -m mklink probes list
python -m mklink probes alias <设备ID或COM口> "电机板"
python -m mklink gui --probe "电机板" --project-root <工程目录>
python -m mklink runtime status
python -m mklink runtime call device_status --probe "电机板"
```

设备 ID 来自 VID、PID 和 USB 序列号，COM 编号变化不影响身份。多个下载器同时
插入时必须明确选择，GUI 可先显示选择页面，再为选定下载器打开独立窗口。
配置页支持本机别名，MCP 支持 `discover_probes`、`set_probe_alias`。
别名不区分大小写地检查重名；空字符串清除别名。缺少或重复序列号时只提供临时
位置身份，拒绝持久别名。不得用某个临时身份假定设备换口后仍是同一台。

别名保存在当前用户的后台数据目录 `aliases.json`，不写入固件。换电脑后需要
重新设置。若需要携带式别名，应另行设计固件 NVM 接口，仍保留不可变 USB 序列号。

## AI 与 GUI 共存

`python -m mklink mcp` 默认连接共享后台。先读取 `ping.capabilities`，调用
`connect(probe=设备ID或别名)`；省略工程与 AXF 表示采用后台当前配置。显式冲突
会返回错误，不替换 GUI 的工程、设备或符号。

第一阶段工具是 `ping`、`discover_probes`、`set_probe_alias`、`connect`、
`disconnect`、`device_status`、`read_memory`、`read_variable` 和 `gui_call`。
`gui_call` 只接受 `ping` 声明的能力，不支持任意 REST、Python 方法或原始命令。

GUI 已在采集时，AI 使用以下能力：

- `superwatch_start` 携带空参数：订阅现有采集，不重启；`superwatch_values`
  读取最后一行及通道元数据、序号、样本时间（毫秒）与缓存年龄。
- `superwatch_snapshot` 读取已有数组快照；`rtt_history`、`systemview_history`
  读取后台已有历史。
- 一次性 `read_memory`（最多 4096 字节）和 `read_variable` 在持续采集时返回
  busy。不得通过独占工具或循环读取绕过。

停止采集要求拥有启动权且没有其他 AI 订阅者。AI `disconnect`、关闭 GUI、关闭
桌面代理均不停止后台。断线会话在 120 秒后过期；过期不自动重放命令或停止采集。
要释放后台持有的 CDC，先结束会话，再显式执行：

```powershell
python -m mklink runtime stop --probe "电机板" --confirm
```

`runtime status` 的 clients 是 AI/CLI 会话数，不包含 GUI 窗口数。显式停止会关闭
该下载器后台及其采集；不影响其他下载器。异常后的操作结果可能未知，不能把
请求超时当成硬件命令已取消，也不能自动重试写操作。

## 兼容边界

旧工具全量接口仍可通过 `mcp --direct`、`gui --direct` 使用；普通旧式 CLI
设备命令和 Python `Device` 仍是独占接口。使用它们之前必须显式释放对应后台，
不能因为共享能力尚未覆盖就自动退回独占模式。当前只把共享 CLI 收口到
`runtime call`，没有宣称旧 CLI 全部迁移完成。

多下载器场景下，U 盘式固件升级和脱机部署/触发暂不支持身份绑定，后台会拒绝。
CMSIS-DAP 在线操作必须选择与窗口绑定设备相同的序列号。别名不会改 USB 设备名、
Windows 驱动或固件版本。跨电脑 Agent、WinUSB、自动崩溃重连、完整 MCP 工具迁移
及长时间稳定性验收属于后续阶段。共享模式暂时禁用旧内嵌 Site Agent，防止其直接
调用 Device 绕过共享仲裁；远程工作流继续使用明确的独占兼容入口。
