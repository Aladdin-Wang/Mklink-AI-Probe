# 0.3.0 共享 CDC 后台与多下载器

本页对应 0.3.0 开发分支的第六阶段实现；现有正式安装版不会自动变成此版本。
底层仍使用原有 CDC，不需要更新下载器固件。

## 连接与选择

每个物理下载器拥有一个后台进程，GUI、MCP、共享 Python SDK 和已迁移的 CLI 命令复用它。
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
配置页的“后台管理”显示绑定设备、当前端口、工程、GUI/AI/CLI/SDK 客户端、采集订阅
和当前操作。四种操作分开执行：

- 结束会话：只撤销所选 AI/CLI/SDK 会话，保留设备与采集。
- 停止采集：仍有 AI/CLI/SDK 订阅者时拒绝；先结束对应会话。
- 释放下载器：必须先结束 AI/CLI/SDK 会话并停止所有采集；后台与窗口保留。
- 退出后台：还要求没有其他 GUI 窗口。意外关闭的窗口最多 45 秒后从列表移除。

设备消失或已连接设备的 COM 口变化时，拒绝新的硬件操作，不会选择另一台设备。
结束旧会话、停止采集并释放旧连接后，显式选择原设备身份重连；不自动重放命令。

命令行还保留显式停止整个后台的管理入口：

```powershell
python -m mklink runtime stop --probe "电机板" --confirm
```

`runtime status` 的 clients 是 AI/CLI/SDK 会话数，不包含 GUI 窗口数。显式停止会关闭
该下载器后台及其采集；不影响其他下载器。异常后的操作结果可能未知，不能把
请求超时当成硬件命令已取消，也不能自动重试写操作。

## 常用 CLI

`read-ram`、`write-ram`、`read-variable`、`write-variable`、`device-status`、
`rtt`、`superwatch`、`systemview`、`halt`、`resume`、`step`、`read-flash`、`read-reg`、`hardfault`、`break`，以及下文的
`flash`、`erase`、`reset` 均通过共享后台运行，共 18 类命令，支持 `--probe` 设备 ID
或别名；多设备时必须明确选择。

```powershell
python -m mklink device-status --probe "电机板"
python -m mklink read-variable counter --probe "电机板"
python -m mklink read-ram --addr 0x20000000 --size 16 --probe "电机板"
python -m mklink superwatch --probe "电机板" --duration 10
python -m mklink read-flash --addr 0x08005000 --size 16 --probe "电机板"
python -m mklink halt --probe "电机板"
python -m mklink step --probe "电机板"
python -m mklink resume --probe "电机板"
```

未指定工程/符号时采用后台当前配置。`write-ram` 在同一次共享操作内写入并回读
校验，校验不一致时报告失败，不重试。捕获命令输出开始状态，并在结束时返回有界
缓存/最新样本；实时显示用 `--visualize` 打开共享 GUI。已有采集只订阅，不能借
启动参数重配；CLI 结束时只解除订阅。CLI 自行启动的采集会尝试停止，若其他客户端
已订阅则保留运行并提示。历史缓存不保证覆盖整个请求时长。

共享模式不接受 `--save` 探针文件写入、私有外设目录覆盖或非默认的独立可视化
host/port/chart 参数。外设目录应先在 GUI 选择，图表使用共享 GUI 配置。

`read-flash` 现在读取目标内存映射 Flash，每次 1..4096 字节，输出 JSON 中的
`data_hex`/`data_base64`；不再加载 FLM 或把快照写到下载器磁盘。需要原生 Flash
算法专用读取的非映射存储器不属于此入口。`halt/resume/step` 返回 `halted` 状态，
会影响同一目标的执行；持续采集或独占任务进行时拒绝，不抢占采集。

## 寄存器、故障快照与断点

`read-reg`、`hardfault`、`break` 已改为共享 CLI，支持 `--probe`，没有直连回退。
MCP `gui_call` 和 SDK `call` 对应 `register_snapshot`、`fault_snapshot`、`breakpoints`。
三者均受采集、独占任务及同探针硬件操作的互斥控制；忙时拒绝，不排队或自动重试。

```powershell
python -m mklink read-reg SCB.VTOR --probe "电机板" --format hex
python -m mklink hardfault --probe "电机板"
python -m mklink break --status --probe "电机板"
python -m mklink break main --probe "电机板"
python -m mklink break --clear 0 --probe "电机板"
```

寄存器读取支持 32 位、1..1024 项，保留 hex/dec/bin/both 格式；`--raw` 现在输出
解码后的十六进制字节，不包含 CDC 提示符或命令回显。已选外设目录时只接受一个
命名寄存器/字段，沿用目录的可读限制；批量原始内存用 `read-ram`。

`fault_snapshot` 读取五个 Cortex-M 架构故障寄存器，仅显式提供 `sp` / `--sp` 时
读取 32 字节异常帧，并用后台当前 AXF 定位。它不发出 halt/resume，也不会自动
寻找 MSP/PSP。多次读取持有一个后台租约，但运行中的目标仍可改变这些值，因此
不保证目标级原子快照。现有 `hardfault` 能力/GUI 详细诊断仍保留原来的暂停分析行为。

`breakpoints` 参数为 `action`（status/list/set/clear/clear_all）；set 需要 `target`
（0x 地址或函数名）及可选整数 `slot`，clear 必须提供 slot。函数按后台 AXF 解析；
当前只支持 Cortex-M FPBv1、低于 0x20000000 的偶数字节地址。设置只能使用空闲
槽位，已有断点需显式清除后替换；设置和清除都读回校验，失败后先检查状态。
`break` 输出 JSON，同一探针的所有客户端共享物理断点；客户端退出保留断点，
任何客户端显式清除都会影响其他客户端。`--clear` 不带槽位明确表示清除全部。

## Python 共享 SDK

共享接口作为 `SharedDevice` / `connect_shared` 导出，客户端通过本机 HTTP 调用
后台，自己不打开 CDC。运行环境需安装 GUI 后台依赖（例如 `pip install .[gui]`），
或使用 MKLink 已配置好的运行环境。它不是低层 `Device` 的完整替代实现。

```python
from mklink import connect_shared

with connect_shared(probe="电机板", name="测试脚本") as device:
    print(device.call("device_status"))
    print(device.read_register("SCB.CPUID"))
    # GUI 已启动 RTT 时，此调用只订阅；退出 with 不停止其采集。
    device.call("rtt_start")
    history = device.call("rtt_history")
```

省略工程/AXF 时复用后台配置；显式冲突会被拒绝。调用应按顺序执行；后台忙时
返回错误，没有自动重试或直连回退。`read_memory` 返回 bytes，`write_memory`
默认同次操作内回读校验，失败会抛出异常。`halt/resume/step` 与 GUI 使用相同准入。

`start_job(action, request_id=..., confirm=True, arguments=...)` 提交独占任务后立即
返回记录，使用 `job_status(job_id)` 查询。SDK close 后仍可查询该后台的任务结果，
但普通硬件调用需要重新显式 connect；close 不释放整个设备，也不取消任务。
SDK 会话在后台管理页标记为 `sdk`，适用相同的会话续期、订阅与结束会话规则。
此阶段后台协议为 6，使用新源码前需要显式退出旧开发后台。

## 兼容边界

0.3.0 已删除 GUI、MCP 和已迁移 CLI 的 `--direct` 入口、重复的直连实现，以及
Web 快捷入口的旧进程接管逻辑。这些入口统一通过共享后台使用 CDC。
其余 CLI（包括独立 dump/watch/分析工作流）、独立远程 Agent 和低层 Python `Device`
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

## WebGUI 释放与恢复

后台管理中释放下载器后，页面会立即刷新连接状态。再次快捷连接时按原 USB 身份
选择当前命令端口，并恢复该后台上次的 AXF、芯片和 ELF 后端；不会用旧 COM 号
覆盖身份选择。已连接的后台保留当前符号，AI 显式要求不同符号时仍会拒绝。

RTT 页面停止被其他订阅者拒绝时，显示和本地暂停状态继续保留。可到后台管理结束
指定会话后再显式停止采集；关闭一个窗口不会替其他窗口或 AI 停止采集。

页面失去后台连接时会显示提示，保留的数据不能视作当前实时状态。同一个后台恢复
可达后，健康检查自动恢复；“重新检查”只检查连接，不负责启动后台或连接硬件。
后台进程重新启动会生成新的授权，旧页显示“当前页面授权已失效”。重新执行
`mklink gui --probe "下载器 ID 或别名"`，用新链接打开对应设备，再显式连接。
不要把另一只下载器的窗口当作原设备的恢复入口。

进程重启不会保留仅通过 SDK/MCP 临时指定的 AXF。连接后核对“配置 → 文件来源”
的当前符号，必要时选择原 AXF 并解析，再让 AI 附着；要求不同符号的客户端仍会
被拒绝。后台不会自动重启采集或重放硬件任务。此流程已验证正常退出后重启，
不等于运行中拔插、进程崩溃或系统休眠恢复已经验收。

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
