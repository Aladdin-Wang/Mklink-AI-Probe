# 0.3.0 共享 CDC 后台与多下载器

本页对应 0.3.0 开发分支的第六阶段实现；现有正式安装版不会自动变成此版本。
底层仍使用 CDC。单通道兼容旧固件；多通道 RTT 与 SuperWatch 并行需配套 `MUX_TARGET=1` 的 V4 开发固件。

## 连接与选择

每个物理下载器拥有一个后台进程，GUI、MCP、共享 Python SDK 和已迁移的 CLI 命令复用它。
两台下载器使用不同后台、设备连接、采集管理器和工程上下文。
同一下载器的多个窗口共享工程、符号和采集设置，不是独立硬件会话。
建议不同目标选择不同工程目录，避免同时编辑同一份工程配置文件。

工程目录在后台进程生命周期内固定，旧 `PUT /api/project-root` 已删除。已有后台
会继续使用启动时的工程；切换工程需先停止采集、分离 AI/CLI/SDK 客户端并关闭
其他 GUI 窗口，再执行 `runtime stop --probe <设备> --confirm`，然后用
`gui --probe <设备> --project-root <新工程>` 启动。新后台重建符号、外设目录和
重连记录，其他下载器的后台保持运行。启动会等待旧进程释放现有实例锁，
不会因 HTTP 已关闭而抢在设备清理结束前启动第二个后台。

配置页修改 SWD 时钟会立即提交一次保存；提交期间禁用相关输入。网络失败显示
“保存未确认”，不会自动重发，需刷新页面核对已保存配置后再决定下一步。
共享采集期间修改在线时钟会被拒绝，先显式停止采集。共享后台的目标调试租约
不会抢占已有 GUI/AI 所有者；采集线程仍在退出时也须等待其完全停止。

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

`get_power(probe=设备ID或别名)` 只读取下载器电压/电流遥测，无需先连接目标。
省略 probe 时使用当前已附着的下载器，未附着时须只有一只可选下载器；显式查询
其他下载器不切换当前会话。查询走对应共享后台，不改变供电或初始化目标。
CDC 采集期间返回 busy，需显式停止后查询；不会为查询停止流或自动恢复连接。

GUI 已在采集时，AI 使用以下能力：

- `superwatch_start` 携带空参数：订阅现有采集，不重启；`superwatch_values`
  读取最后一行及通道元数据、序号、样本时间（毫秒）与缓存年龄。
- `superwatch_snapshot_select` 使用 `name/start_index/count` 选择数组快照，`superwatch_snapshot_clear` 清除选择；它们修改共享视图，不自动启动采集。MCP 对应 `superwatch(action="snapshot_select"/"snapshot_clear")`。
- `superwatch_snapshot` 读取已有数组快照；`rtt_history`、`systemview_history`
  读取后台已有历史。
- 一次性内存/变量读写和寄存器读取在持续采集时返回 busy。旧 SuperWatch
  inspector 会重新读取硬件，共享采集期间同样拒绝；请读取已有快照。
  不得通过独占工具或循环读取绕过。

内存读写限制为 1..4096 字节且不能越过 32 位地址范围。`write_memory` 使用
偶数位十六进制字符串；`write_variable` 只接受整数。采集期间需要修改变量时，
使用已有的类型化 `superwatch(action="write")`：参数为 `path`、`value` 和
从 `gui_call("symbol_status")` 取得的 `generation`，执行实时写入及校验。
RTT 输入限制为 1..256 字节；旧映射模式拒绝保留的停止命令，新多路复用模式支持二进制。

MCP 的 `systemview_decode(hex_bytes=...)` 和 `systemview_analyze_events(events=...)`
可离线调用，无需 `connect` 或选择下载器；运行中的 GUI 采集也不会被打断。
分析已有共享跟踪数据时，将 `systemview(action="history")` 返回的 `points` 事件列表传给
分析工具。离线解码使用调用方提供的字节，不启动或读取目标通道。

`configuration_description(part_number=...)` 和 `configuration_script(part_number=..., changes=...)`
离线生成字段说明和已支持的配置脚本，无需连接下载器，生成不会执行脚本。
`read_configuration(part_number=..., model="V4")` 通过已连接的共享后台读取受限配置快照，
须先停止 CDC 采集；保留芯片身份、容量与字段范围校验，不改变保护状态或写入 OTP。

`set_debug_speed(profile="low")` 通过同一后台修改调试速度，支持
low/medium/high/ultra；持续采集期间拒绝，需先显式停止采集。成功后保存工程配置，
同一下载器的所有客户端共享该速度。`gui_call("debug_speed")` 读取后台缓存的时钟和
可用档位，采集期间也可调用；这是后台记录值，不是独立硬件测量。

停止采集要求拥有启动权且没有其他 AI 订阅者。AI `disconnect`、关闭 GUI、关闭
桌面代理均不停止后台。断线会话在 120 秒后过期；过期不自动重放命令或停止采集。
浏览器将页面暂存到往返缓存后，返回页面会重新登记窗口存在性；这不会重连下载器或
重新启动采集。窗口完全关闭后停止登记，后台与其他客户端继续运行。
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

旧 `/api/session/acquire`、`release`、`status` 已删除，不提供兼容转发。
程序接入使用共享客户端的 connect/close；资源占用查询统一使用 `/api/resources/status`。

## 跨进程端口锁

CMD、通用串口和 Modbus 共用同一端口锁，按端口分别互斥。默认注册目录在当前用户的
应用数据目录下（Windows 通常为 `%LOCALAPPDATA%/Mklink AI Probe/locks`），不随
TEMP、工程目录或 `MKLINK_RUNTIME_DIR` 改变。`resources status --port COM口 --json`
可以看到下载器后台的持有者 PID。文件存在不代表端口仍被占用；进程退出会释放系统锁。

普通资源清理保留活跃持有者，只在取得系统锁后清空失效 PID，保留锁文件本身。
`--force` 仍表示明确结束持有进程，会影响该后台的所有客户端，不能用来绕过共享准入。
隔离测试可设置绝对路径 `MKLINK_LOCK_DIR`；访问同一端口的所有进程必须使用同一配置。
此锁只约束采用该实现的进程，不替代操作系统的串口占用检查或 USB/MSC 身份绑定。

本次后台协议为 7。升级时先从旧后台的管理页正常退出，再启动新版本；协议 6 后台会被
新客户端拒绝，不自动接管。旧版工具仍可能使用 TEMP 中的旧锁目录，不能假定新旧进程
混用具备同样的跨进程协调能力。旧全局锁的诊断/清理代码和返回字段已删除，不扫描旧 TEMP。

## 常用 CLI

`read-ram`、`write-ram`、`read-variable`、`write-variable`、`device-status`、
`rtt`、`superwatch`、`systemview`、`halt`、`resume`、`step`、`read-flash`、`read-reg`、`hardfault`、`break`，以及下文的
`flash`、`erase`、`reset`、`debug-speed`、`power-read`、`version`、`configuration read`、`peripherals`（离线 targets 除外）、`dump-memory`（别名 `dump`）、`flush-memory`、`dump-benchmark`、`watch`、`vofa` 均通过共享后台运行，共 28 类命令，支持 `--probe` 设备 ID
或别名；多设备时必须明确选择。

```powershell
python -m mklink device-status --probe "电机板"
python -m mklink read-variable counter --probe "电机板"
python -m mklink watch counter,samples[0] --probe "电机板" --period 1
python -m mklink read-ram --addr 0x20000000 --size 16 --probe "电机板"
python -m mklink superwatch --probe "电机板" --duration 10
python -m mklink read-flash --addr 0x08005000 --size 16 --probe "电机板"
python -m mklink halt --probe "电机板"
python -m mklink step --probe "电机板"
python -m mklink resume --probe "电机板"
python -m mklink debug-speed low --probe "电机板"
python -m mklink debug-speed medium --probe "电机板" --save
python -m mklink power-read --probe "电机板" --json
python -m mklink version --probe "电机板" --raw
python -m mklink configuration read --chip STM32F103RET6 --probe "电机板"
python -m mklink peripherals targets --project-root <工程目录> --query STM32F103RE
python -m mklink peripherals select --target-id <目录ID> --probe "电机板"
python -m mklink peripherals list --query GPIOB --probe "电机板"
python -m mklink peripherals read GPIOB.IDR GPIOB.12 --probe "电机板"
python -m mklink peripherals capture GPIOB.IDR GPIOB.12 --duration 1 --period 0.01 --probe "电机板"
```

未指定工程/符号时采用后台当前配置。`write-ram` 在同一次共享操作内写入并回读
校验，校验不一致时报告失败，不重试。捕获命令输出开始状态，并在结束时返回有界
缓存/最新样本；实时显示用 `--visualize` 打开共享 GUI。已有采集只订阅，不能借
启动参数重配；CLI 结束时只解除订阅。CLI 自行启动的采集会尝试停止，若其他客户端
已订阅则保留运行并提示。历史缓存不保证覆盖整个请求时长。

`debug-speed` 复用后台调速，GUI 采集期间拒绝。未指定 `--save` 时只改变当前后台
连接的速度，CLI 退出不会还原；带 `--save` 则在调速成功后保存到后台当前工程，
供后续连接使用。结果中的 `saved` 表示是否保存。所有附着客户端看到同一速度，
不会另开 CDC、停止他人采集或重试失败命令。

`peripherals select/list/read/capture` 使用后台工程和 GUI 的目录选择入口；选择
支持一个 `--target-id`、`--chip` 或 `--svd`，其余动作只使用已选目录。更改目录前
其他 AI/SDK 客户端须解除附着，SuperWatch 须完全停止；调用方自己可以保留会话。
目录枚举 targets 是离线操作，使用 `--project-root`，不接受 `--probe/--port`。
MCP 同名 peripheral_targets 也离线；已连接时可通过
`gui_call('peripheral_targets', {'q': 'STM32F103RE'})` 枚举后台工程目录。
活动 MCP 提供 select_peripherals、list_peripherals、capture_peripherals，
共享 SDK 可直接调用相应能力及 read_peripherals。

外设短时采样需要空闲 CDC，最多 64 个通道、15 个区域、30 秒、100000 个结果行；
首帧最多等待 2 秒，再开始计算采样时长，结束后恢复命令模式。寄存器/字段解码
复用已有 SVD 和 dump-memory 算法，过滤已标注的读副作用；读取不是多变量原子快照，
轮询可能漏短脉冲。GUI 采集时可读取目录元数据，硬件读/短时采样会拒绝，且不重试。

共享内存读取不接受 `--save` 探针文件写入；读/采集命令不接受临时私有外设目录覆盖。
外设目录应先在 GUI 或通过 `peripherals select` 选择。独立可视化的非默认
host/port/chart 参数不受支持，图表使用共享 GUI 配置。

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

`read_memory_regions([(address, size), ...])` 返回按输入顺序排列的 bytes 列表。
一次最多 16 个区域、总计 4096 字节；地址/长度必须是整数，范围在 32 位地址空间内。
连续或重叠区域复用底层一次读取，离散区域分别读取，不读取地址间隙；因此不保证
所有值来自同一时刻。失败或短响应直接报错，没有自动补读。GUI 持续采集时拒绝调用。
MCP 同名工具与 `gui_call('read_memory_regions', {'regions': [...]})` 使用同一能力；
JSON 每个区域格式为 `{"address": 536870912, "size": 4}`。这属于显式原始地址读取，
不会替用户筛除 MMIO 读副作用；读取外设描述中的安全字段可用 `read_peripherals`。

MCP `dump_memory` 和 SDK `call('dump_memory', arguments)` 已共享；参数为 regions、
sample_count（1..64）、每样本 timeout（0.001..60 秒）及可选 speed_profile。
最多 8 个区域，整数地址/长度限定在 32 位地址空间，所有样本的原始数据合计不超过 512KiB。复用既有二进制
解析和完整性校验，每个样本只发一次读取，失败不补发。所有样本结束且停止身份应答
确认后返回；停止失败也报错，不把连接强行标成可用。HTTP 等待预算包含显式采样
与停止确认，用户端请求中断不表示硬件已取消。GUI 采集或独占任务忙时拒绝。
显式 speed_profile 会改变当前共享探针速度（不保存工程配置）；省略则保持当前速度。
这是有界单次样本集合。周期 CLI 使用下面的 `capture_dump` 能力。

`dump-memory` / `dump` 已改用共享后台，支持 `--probe`、`--project-root`。
`--period 0` 读取一个样本；多样本须使用正周期。正周期保留 `--frames`（0..100000）
和 `--duration`（0..300 秒）两种停止条件，先到者结束；两者不能同时为零。
首个完整样本最多等待 2 秒，然后开始计算时长；只按数量采集也最多持续 300 秒。
最多 15 区域，每样本不超过现有设备上限。完整样本的 JSON 合计上限 16MiB，
超过则报错且不保存；持续时间边界上的不完整末尾样本不返回，`incomplete_tail`
明确标记。缺块、CRC 或停止确认失败直接报错，不把最后一个块当作完整样本。

```powershell
python -m mklink dump-memory 0x20000000:16 --probe "电机板" --period 0.01 --frames 10 --save samples.bin --json
```

`--save` 写入当前 CLI 所在电脑，按样本、区域的输入顺序拼接已校验字节；后台不接收
输出路径。`--json` 在采集完成后输出一个完整 JSON 结果，不再输出未组装的逐块数据。
MCP 使用 `gui_call('capture_dump', {...})`，SDK 使用 `call('capture_dump', {...})`，
参数为 regions、period、frames、duration、可选 speed_profile。省略速度保持后台当前值。
采集占用同探针 CDC，GUI 的持续采集需要先显式停止；其他探针独立运行。
完整样本不代表目标多区域原子快照。关闭客户端不等同于立即取消后台的有界操作。

`start_job(action, request_id=..., confirm=True, arguments=...)` 提交独占任务后立即
返回记录，使用 `job_status(job_id)` 查询。SDK close 后仍可查询该后台的任务结果，
但普通硬件调用需要重新显式 connect；close 不释放整个设备，也不取消任务。
SDK 会话在后台管理页标记为 `sdk`，适用相同的会话续期、订阅与结束会话规则。
此阶段后台协议为 7，使用新源码前需要显式退出旧开发后台。

## 变量快照

`watch` 一次解析全部路径后复用后台批量读取，返回 `name/address/type/size/value`。
SDK 使用 `device.watch(['counter', 'samples[0]'])`；MCP 使用
`gui_call(capability='watch', arguments={'names': ['counter']})`。最多 16 个唯一标量，
只读 Flash 标量可读，指针/结构体整体不可猜成整数；C 布局覆盖以当前目录为准。

稀疏 DWARF 的 MAP 回退只支持基本 C 全局标量。加载目录时冻结同名 MAP（或旧工程的
demo.map）及明确工程根目录内的 C/H 内容；未给工程根目录时只查符号文件所在目录，
不逐级扫描父目录，不跟随源码目录链接。总内容上限 16 MiB、源码 4096 文件、遍历
20000 项，超限只禁用 MAP 回退，已有 DWARF 仍可用。缺失类型、重复定义、冲突类型、
指针、数组及宏生成的声明需要补充可靠 DWARF，不能猜测。MAP 回退描述始终只读。

读取前后校验 AXF 以及实际使用的 MAP/C 内容，改变或删除返回 409。新增文件或原先
不匹配的声明不会在已有目录中自动生效，需通过共享准入显式重解析；此规则冻结解析
依据，不证明源码已与目标固件匹配。复杂预处理/ABI 推断不在此基本回退范围内。

## 兼容边界

0.3.0 已删除 GUI、MCP 和已迁移 CLI 的 `--direct` 入口、重复的直连实现，以及
Web 快捷入口的旧进程接管逻辑。这些入口统一通过共享后台使用 CDC。
其余 CLI（包括串口/Modbus、分析工作流）、独立远程 Agent 和低层 Python `Device`
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

## VOFA 共享采集

`vofa_start` 空参数订阅已有流；新采集可传 `channels`（目录 `path` 或裸 `addr/type`）
和 `interval`。所有入口复用同一管理器、CDC 租约及停止事务。其他客户端还在订阅
时禁止停止、后台暂停和改周期；停止确认失败返回错误，不重放停止命令。错误采样
会终止并通过状态/历史公开原因。客户端退出只解除自身，不替别人释放下载器。

`vofa --visualize` 打开共享 WebGUI 的独立波形页；复用现有二进制绘图组件，未新建
服务器。旧直连、JustFloat、私有服务及 host-polling 回退已删除。通道定义与限制见
[VOFA 命令](commands-memory.md#vofa-共享实时变量观测030)。

## WebGUI 释放与恢复

共享模式的 flash/erase/reset 必须提交到任务入口；直接调用旧 REST 写接口会被拒绝。
CLI 与管理页遵守同一退出规则：先结束客户端会话、关闭其他窗口并停止采集。
释放 CDC 或访问 MCU 不要求停止独立 UART/Modbus；退出整个后台仍要求先停止它们。
共享窗口仅登记自身存在性，不再启动旧浏览器的“最后窗口关闭即释放设备”租约。

后台管理中释放下载器后，页面会立即刷新连接状态。再次快捷连接时按原 USB 身份
选择当前命令端口，并恢复该后台上次的 AXF、芯片和 ELF 后端；不会用旧 COM 号
覆盖身份选择。已连接的后台保留当前符号，AI 显式要求不同符号时仍会拒绝。

RTT 页面停止被其他订阅者拒绝时，显示和本地暂停状态继续保留。可到后台管理结束
指定会话后再显式停止采集；关闭一个窗口不会替其他窗口或 AI 停止采集。

MCP 服务正常结束时主动解除自己的会话，即使没有调用 disconnect，也不会替 GUI
关闭设备或停止采集。强制终止进程、后台不可达时仍由会话 TTL 兜底，不能视为即时释放。

页面失去后台连接时会显示提示，保留的数据不能视作当前实时状态。同一个后台恢复
可达后，健康检查自动恢复；“重新检查”只检查连接，不负责启动后台或连接硬件。
后台进程重新启动会生成新的授权，旧页显示“当前页面授权已失效”。重新执行
`mklink gui --probe "下载器 ID 或别名"`，用新链接打开对应设备，再显式连接。
不要把另一只下载器的窗口当作原设备的恢复入口。

进程重启不会保留仅通过 SDK/MCP 临时指定的 AXF。连接后核对“配置 → 文件来源”
的当前符号，必要时选择原 AXF 并解析，再让 AI 附着；要求不同符号的客户端仍会
被拒绝。后台不会自动重启采集或重放硬件任务。此流程已验证正常退出后重启，
不等于运行中拔插、进程崩溃或系统休眠恢复已经验收。

## 符号文件变化

共享后台发现 AXF/MAP 内容变化后，先保留待处理记录。CDC 采集、AI/SDK 会话、
连接过程或硬件任务仍在使用后台时，不会自动停止采集或切换符号。RTT 页显示等待
重载的提示，当前地址与数据流保持不变。停止采集、结束客户端会话并等待任务完成后，
后台才重载；采集仍需显式重新启动。手动解析 AXF、重解析或修改 C 布局也遵守这些限制。

会话绑定当前符号目录的版本和内容指纹。同一路径重新解析或修改布局后，旧会话不能
继续发起调用或硬件任务，需要显式重新连接。心跳不会替会话接受新的符号布局。
解析失败时，同一份内容不会每秒重试；修正文件内容后重新检测，或显式重连处理。

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


## SystemView 分析与报告

`systemview-analyze` 与 `systemview-report` 通过所选探针的共享后台采集，
沿用后台当前工程、符号与任务名解析，不再单独打开 CDC 或切换符号文件。

```powershell
python -m mklink systemview-analyze --probe "电机板" --duration 6
python -m mklink systemview-report --probe "电机板" --duration 6 --out report.html --no-browser
```

已有采集从订阅时的末尾开始读取，退出不停止其他客户端的采集。自己新建的采集
结束时只请求一次停止；其他订阅者阻止停止时保留采集并提示。时长须为正有限秒数。
暂停、停止、后台/会话变化或历史缺口会报错，不输出截断的新报告。
目标自身丢包仍受原始跟踪协议和分析器能力限制，不保证无损。

`gui_call("systemview_capture_history", {})` 建立当前末尾游标；之后传入
`session`、`after=next_seq` 与可选 `limit`（1..500）增量读取 `points`。
同一历史供多个读者独立读取，`dropped` 表示本页跨过的缺失事件数；会话更换返回409，
不能把新采集接到旧报告中。该接口复用既有100000事件/60秒历史；CLI持续分页收集
本次事件供本地分析，报告进程内存随实际收集量增长，不提供无限时长采集保证。


## 多通道 RTT 与 SuperWatch（协议 49 开发版）

配套固件检测到 CMSIS-DAP 调试改变目标后，会停止原 RTT/SuperWatch 采集，
丢弃旧的 RTT 游标写入并报告失效原因。调试结束后需要显式重新启动采集，
不能把旧地址和待发送数据自动重放到新固件。此行为尚待真机验收。

配套 V4 固件报告 `MUX_TARGET=1` 后，GUI/CLI/MCP 自动使用同一个 CDC 帧通道。
仍然只有后台打开串口和读取 USB，客户端读取后台缓存。外部串口助手的旧 RTT
映射仍保留；它与后台不能同时打开命令口。

- GUI 的 RTT 页填写 `0,1` 等通道列表，所有通道同等支持日志、终端、HEX、曲线与发送；多通道
  查看区可独立选通道并切换 HEX/文本，下行可选择已订阅且实际活动的 DownBuffer。
- MCP `rtt_start(addr=..., channels=[0,1], channel=0)` 创建采集；已运行时用不带参数
  的 `rtt_start()` 订阅，不能替其他客户端重新配置。
- `rtt_read_channel(channel=1, cursor=0)` 返回原始 `data_hex`、`session`、`cursor`、
  `lost_bytes`。后续传回 session/cursor；`reset=true` 表示已换采集会话。
  每通道保留 64 KiB、每次最多返回 16 KiB，各客户端游标独立，不会互相取走数据。
  查看 `rtt_status.transport_stats` 区分传输队列丢失与客户端缓存覆盖。
- MCP `rtt_write(text, channel=0)` 或 `rtt_write_hex(data_hex, channel=0)` 一次最多
  256 字节，失败或结果未知时不得整条重发。已被 RTT 环形缓冲接受不等于目标应用
  已处理，目标协议仍应自行确认。
- CLI `python -m mklink rtt --probe <设备> --channels 0 1 --addr <RTT地址> --duration 3`
  创建有限采集；读取已有采集可用 `runtime call rtt_read_channel --probe <设备>
  --arguments '{"channel":1}'`。共享 Python SDK 使用相同的 `call()` 能力。
- 多路复用 RTT、SuperWatch 可并行；内存/变量及外设寄存器读写、批量内存读取可
  同时发命令。烧录、复位、调试控制、修改时钟、独立 SystemView/VOFA 仍需先停流。
- SuperWatch 最多 15 个物理区域、每区 128 字节；大区域会拆分并计入 15 区预算。
  最短固件采样周期为 2 ms。多区域依次读取，不是原子快照。
- 任一超时/CRC/会话错误关闭本次协议会话，不重放未知写入，也不自动降级原始命令。
  后台异常退出后，显式重连可恢复本机记录的帧模式。

本轮验证为本机 STM32 短测。HPM、八个实体 RTT 通道、跨主机远程链路和长时间采集
未据此验收；已安装的旧程序需更新配套主机版本才会出现新界面。

GUI RTT 按采集通道并排显示，每路复用相同的日志/终端/HEX/曲线/发送组件。收起或切换显示模式不销毁历史，暂停仅作用于当前面板。日志最多5000行，HEX保留64KiB，曲线Worker每路最多25000样本；缓冲有界，不保证无限无损。
