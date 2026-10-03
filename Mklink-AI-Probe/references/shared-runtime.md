# 0.3.0 共享 CDC 后台与多下载器

本页对应 0.3.0 开发分支的第三阶段实现；现有正式安装版不会自动变成此版本。
底层仍使用原有 CDC，不需要更新下载器固件。

## 连接与选择

每个物理下载器拥有一个后台进程，GUI、MCP 和已迁移的 CLI 命令复用它。
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

MCP 提供发现/连接、设备状态、内存和整数变量读写、寄存器读取、符号搜索、
`runtime_status`、RTT、SuperWatch 和 SystemView 工具。`connect` 的
`client_name` 可用于管理页识别不同 AI 客户端。
`gui_call` 只接受 `ping` 声明的能力，不支持任意 REST、Python 方法或原始命令。

GUI 已在采集时，AI 使用以下能力：

- `superwatch_start` 携带空参数：订阅现有采集，不重启；`superwatch_values`
  读取最后一行及通道元数据、序号、样本时间（毫秒）与缓存年龄。
- `superwatch_snapshot` 读取已有数组快照；`rtt_history`、`systemview_history`
  读取后台已有历史。
- 一次性内存/变量读写和寄存器读取在持续采集时返回 busy。旧 SuperWatch
  inspector 会重新读取硬件，共享采集期间同样拒绝；请读取已有快照。
  不得通过独占工具或循环读取绕过。

内存读写限制为 1..4096 字节且不能越过 32 位地址范围。`write_memory` 使用
偶数位十六进制字符串；`write_variable` 只接受整数。采集期间需要修改变量时，
使用已有的类型化 `superwatch(action="write")`：参数为 `path`、`value` 和
从 `gui_call("symbol_status")` 取得的 `generation`，执行实时写入及校验。
RTT 输入限制为 1..256 个 UTF-8 字节，拒绝保留的停止命令。

停止采集要求拥有启动权且没有其他 AI 订阅者。AI `disconnect`、关闭 GUI、关闭
桌面代理均不停止后台。断线会话在 120 秒后过期；过期不自动重放命令或停止采集。
配置页的“后台管理”显示绑定设备、当前端口、工程、GUI/AI/CLI 客户端、采集订阅
和当前操作。四种操作分开执行：

- 结束会话：只撤销所选 AI/CLI 会话，保留设备与采集。
- 停止采集：仍有 AI/CLI 订阅者时拒绝；先结束对应会话。
- 释放下载器：必须先结束 AI/CLI 会话并停止所有采集；后台与窗口保留。
- 退出后台：还要求没有其他 GUI 窗口。意外关闭的窗口最多 45 秒后从列表移除。

设备消失或已连接设备的 COM 口变化时，拒绝新的硬件操作，不会选择另一台设备。
结束旧会话、停止采集并释放旧连接后，显式选择原设备身份重连；不自动重放命令。

命令行还保留显式停止整个后台的管理入口：

```powershell
python -m mklink runtime stop --probe "电机板" --confirm
```

`runtime status` 的 clients 是 AI/CLI 会话数，不包含 GUI 窗口数。显式停止会关闭
该下载器后台及其采集；不影响其他下载器。异常后的操作结果可能未知，不能把
请求超时当成硬件命令已取消，也不能自动重试写操作。

## 常用 CLI

`read-ram`、`write-ram`、`read-variable`、`write-variable`、`device-status`、
`rtt`、`superwatch`、`systemview` 默认通过共享后台运行，支持 `--probe` 设备 ID
或别名；多设备时必须明确选择。

```powershell
python -m mklink device-status --probe "电机板"
python -m mklink read-variable counter --probe "电机板"
python -m mklink read-ram --addr 0x20000000 --size 16 --probe "电机板"
python -m mklink superwatch --probe "电机板" --duration 10
```

未指定工程/符号时采用后台当前配置。`write-ram` 在同一次共享操作内写入并回读
校验，校验不一致时报告失败，不重试。捕获命令输出开始状态，并在结束时返回有界
缓存/最新样本；实时显示用 `--visualize` 打开共享 GUI。已有采集只订阅，不能借
启动参数重配；CLI 结束时只解除订阅。CLI 自行启动的采集会尝试停止，若其他客户端
已订阅则保留运行并提示。历史缓存不保证覆盖整个请求时长。

共享模式不接受 `--save` 探针文件写入、私有外设目录覆盖或非默认的独立可视化
host/port/chart 参数。外设目录应先在 GUI 选择，图表使用共享 GUI 配置。

## 兼容边界

0.3.0 已删除 GUI、MCP 和已迁移 CLI 的 `--direct` 入口、重复的直连实现，以及
Web 快捷入口的旧进程接管逻辑。这些入口统一通过共享后台使用 CDC。
其余 CLI（包括独立 dump/watch/分析工作流）、独立远程 Agent 和 Python `Device`
仍有直接操作设备的实现，尚未迁移。使用它们之前必须显式释放对应后台，不能因为
共享能力尚未覆盖就自动退回直连。底层 CDC 驱动仍供共享后台使用，不属于待删除的旧模式。

Windows 共享后台的磁盘发现按 USB 设备祖先的 VID/PID/序列号核对，只接受唯一的
MICROKEEN 卷，写入使用卷 GUID 路径，不依赖盘符顺序或同名卷标。配置页“核对
下载器磁盘”可查看绑定结果；不能证明对应关系时拒绝，不能用环境变量覆盖选择。
此绑定覆盖原生烧录文件复制、脱机部署及磁盘查询。脱机触发的命令口也必须属于
当前设备。Mac/Linux 的共享 MSC 操作暂未支持。探针固件升级会重新枚举为 Bootloader，
尚未绑定升级后身份，因此共享模式仍拒绝该操作；独占维护须明确保证唯一设备。

CMSIS-DAP 在线操作必须选择与窗口绑定设备相同的序列号，后台持续检查已有在线
任务，任务结束前禁止 CDC 操作、启动新采集或退出后台。别名不会改 USB 设备名、
Windows 驱动或固件版本。跨电脑 Agent、WinUSB、自动崩溃重连、完整 MCP 工具迁移
及长时间稳定性验收属于后续阶段。共享模式暂时禁用旧内嵌 Site Agent，防止其直接
调用 Device 绕过共享仲裁；独立远程工作流仍须独占设备，不能与对应共享后台并用。

## 烧录、擦除与复位任务

共享 GUI 的目标烧录/擦除/复位、CLI `flash`/`erase`/`reset` 和 MCP `start_job`
统一提交独占任务。先显式停止采集，空闲客户端可以保持连接；有正在执行的硬件
操作时直接拒绝，不排队，也不抢占采集。CLI `flash` 必须显式提供固件路径，沿用
后台当前工程/芯片配置，写后校验；不再隐式从另一工程挑选固件。

```powershell
python -m mklink flash --probe "电机板" --hex <固件文件>
python -m mklink reset --probe "电机板"
python -m mklink runtime jobs --probe "电机板"
python -m mklink runtime jobs --probe "电机板" --job <任务ID>
```

MCP `start_job(action, request_id, confirm=true, arguments)` 接受 `flash`、`erase`、
`reset`；flash 参数为 `firmware`、`verify`、`reset_after`。调用前仍须按用户授权
确认具体目标和操作。提交后用 `job_status(job_id, probe)` 查询；查询不连接硬件，
可按原设备 ID 查询拔下后的已有后台。CLI 打印请求 ID 和任务 ID，`--request-id`
允许复查同一提交；同一请求 ID 携带不同参数会被拒绝。

状态为执行中、成功、失败或结果未知。失败不表示目标从未被修改；连接丢失、后台
中断等情况不能据此重试。关闭窗口/退出 AI 不取消任务，当前硬件任务没有强制取消
入口。后台重启会把中断任务标为未知，不重放命令；先检查目标状态，再决定下一操作。

每台后台保留最近 64 个任务及其去重记录，管理页显示最近 8 个。记录淘汰后不再
提供去重保证，找不到旧任务不能解释为任务失败。CLI 的 Ctrl+C 只结束等待，任务
可能仍在执行。当前任务记录覆盖原生 CDC flash/erase/reset；CMSIS-DAP 继续使用
原有在线任务页面，脱机流式触发保持现有输出接口，不属于这份持久任务历史。
