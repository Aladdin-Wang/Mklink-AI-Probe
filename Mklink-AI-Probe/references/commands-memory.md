# 内存、VOFA 与 AXF 调试

> 触发词：read-ram、read-reg、dump-memory、flush-memory、vofa、watch、superwatch、hardfault、typeinfo、symbols、memmap
> 返回索引：[SKILL.md](../SKILL.md)

## 内存操作

### 共享变量与 C 布局（0.3.0）

变量访问使用后台当前符号目录。C 布局覆盖后，读取、写入、搜索及 SuperWatch 使用
覆盖字段的地址和类型；删除的字段不再回退到原 DWARF。覆盖的一维标量数组可以
分页浏览和选择快照范围。C 布局必须完整落在目录已识别的可写内存范围内。

普通变量读取可读取已解析的 Flash 标量，但不会将它加入可写目录。变量写入复用
目录的类型编码与范围检查；未知字段、不可写地址及不合法的类型值返回 422。
共享 `write_variable` 仍接收整数参数；布尔、浮点和其他类型的 GUI/MCP 写入使用
既有 SuperWatch 类型化写入。AXF 内容变化或丢失返回 409，不自动重解析或重放。


### 读取 RAM

#### `python -m mklink read-ram --addr <地址> [--size <字节数>] [--port COM6] [--save <文件名>]`
读取目标芯片 RAM 数据，输出十六进制 dump。RAM 读取不需要 FLM 算法。
`--size` 限制为 **1..4096 字节**；更大范围改用 `dump-memory`，不要把大段文本
hexdump 返回给 AI。MCP 同样限制 `read_memory` 为 4096B；同时读取多个变量时用
`read_memory_regions`（最多 16 项、总计 4096B），连续或重叠区域会自动合并为一次读取。

```
python -m mklink read-ram --addr 0x20000000 --size 256
python -m mklink read-ram --addr 0x20000000 --size 128 --save ram.bin
```

`--save` 将数据保存到 MKLink U 盘文件，重启下载器后可见。

### 读取内存映射寄存器

#### `python -m mklink read-reg <寄存器名> [--width 32] [--count 1] [--format both] [--port COM6]`
读取外设、SCB、NVIC、CoreDebug 等内存映射寄存器，底层仍是 `cmd.read_ram(<addr>, <size>)`。

```
python -m mklink read-reg SCB.CFSR
python -m mklink read-reg SCB.HFSR --format hex
python -m mklink read-reg --addr 0xE000ED28 --width 32
```

注意：`read-reg` 读取的是内存映射寄存器地址；R0/R1/MSP/PSP/LR/PC 这类 CPU 核心寄存器不是普通内存地址，不能直接用 `cmd.read_ram` 当作地址读取。HardFault 自动栈帧解析需要用户提供异常栈帧地址 `--sp`。

### 外设目录、字段与采集（0.2.1 开发分支）

CLI、MCP 和 Web 的外设目录共用同一解析与位提取逻辑，无需 AXF。
先指定项目和实际型号；选择保存在项目 `.mklink/peripheral-selection.json`。
三端必须使用同一 `project_root`。Web 重连会恢复选择；停止采集后再换型号。
多个 Pack 提供同名型号时，使用 `targets` 返回的精确 `--target-id`，不会猜第一个 SVD。

```powershell
python -m mklink peripherals targets --query HPM --project-root .
python -m mklink peripherals select --chip HPM5301 --project-root . --query UART0.GPR
python -m mklink peripherals list --query UART0.GPR --project-root .
python -m mklink peripherals read UART0.GPR.DATA --project-root .
python -m mklink peripherals capture UART0.GPR.DATA --duration 3 --period 0.001 --project-root .
python -m mklink read-reg UART0.GPR.DATA --project-root . --format dec
```

自备 SVD 可用 `peripherals select --svd <文件>`，ARM 型号从已安装 CMSIS-Pack 的
PDSC 精确映射发现。`superwatch --chip/--target-id/--svd` 也使用此目录；省略选择参数时恢复项目选择。
已选芯片后，不在该目录里的寄存器名或裸地址不会回退到其他芯片的定义。
显式裸内存操作仍由 `read-ram` / `dump-memory` 提供，不受 SVD 副作用过滤保护。

MCP 对应 `peripheral_targets(project_root, query)`、连接后
`select_peripherals(chip=...)`、`list_peripherals(query=...)`、
`read_register(name=...)`、`capture_peripherals(names=[...], duration=3, period=0.001)`。
采集返回通道名称、设备时间戳、位提取后的数值以及完整性计数；最长 30 秒、最多
15 个寄存器区域、最多 100000 行。同一寄存器多个字段共用一次读取，不跨邻接寄存器合并。

当前共享目录只接受对齐的 **32 位、小端** 寄存器访问。位字段读取整个所属寄存器后
执行移位和掩码，保留位不会混入字段值。当前探针 ARM 实现的 16 位读取拆为两个字节事务，
因此不模拟窄寄存器访问，也不扩大读取范围；真正支持半字事务需另行修改探针协议/固件。
已声明的只写、读取清除/弹出、替代寄存器组等不进入目录；SysTick CSR/CTRL 也不参与轮询。
未标注的副作用、时钟关闭、封装差异仍需依据对应芯片资料判断。
ARM 内置寄存器名仅用于未选择目录的兼容快照入口，不应套用到 HPM。

目录支持 SVD 的继承、cluster、寄存器/字段数组、字母索引和 bitRange。
型号覆盖取决于本地描述文件；本机 HPM SDK 1.11.0 的 43 个型号描述已验证可加载，
不代表每个外设都已做实板验证。GUI 波形传输为 Float32，大整数曲线可能舍入；
需要精确寄存器值时使用单次 `read` / `read_register`。

### 写入 RAM

#### `python -m mklink write-ram --addr <地址> <字节1> <字节2> ... [--port COM6]`
写入数据到 RAM 并自动回读验证，单次最多 4096B。CLI 使用 `Device.write_memory` 的
`flush_memory` 分块/重复字节折叠路径，不再直接依赖旧 `cmd.write_ram` 的命令回显。
RAM 写入不需要 FLM 算法。

```
python -m mklink write-ram --addr 0x20001000 0xDE 0xAD 0xBE 0xEF
```

**多地址写入**:PikaScript 不支持 list/tuple 展开为多地址参数,`cmd.write_ram([a,b],[v1,v2])` 会被解释为单 arg,数据写到临时区。**正确方式:多次调用**,每次 47ms 开销:

```python
# ❌ 错误 — list/tuple 语法被忽略,写到 0x0009c5xx 临时区
cmd.write_ram([0x20001080, 0x20001090], [0x11, 0x22])

# ✅ 正确 — 两次连续调用
cmd.write_ram(0x20001080, 0x11)
cmd.write_ram(0x20001090, 0x22)
# 两次共 ~95ms,无串行开销
```

直接调用旧固件 `cmd.write_ram` 时仍受 Pika 位置参数上限约束；CLI 已不走该入口。
V4.3.8 在 STM32H743 上实测旧入口、bytes 字面量、重复字节折叠及 Device 路径均可完成
`11 22 33 44 -> 00 00 00 00` 并回读。为防旧固件或偶发静默失败，自动化写入必须以回读
一致作为成功条件，不能只看 `>>>` 或命令回显。

**避免覆盖活跃内存区**:写入前先核对 `build/keil/List/rt-thread.map` 与 AXF 符号:
- `0x20000000..0x200000DC`: `.mklink_res` (test fixture 控制块, magic 0x4D4B5245 "ERKM")
- `0x20000200..0x20001374`: `.data`
- `0x20001374..0x20001774`: `s_tf_data_buf` (test fixture 数据缓冲,**20ms 周期被覆写**)
- `0x200017F8..0x200018F8`: `rt_thread_stack` (256B, RT-Thread 主线程栈,**绝不可覆盖**)
- `0x20001908+`: `_heap` (RT-Thread 堆起点, **运行时向上增长**, .bss 之后未必真空闲)
- `0x20001774..0x2000FAB0`: `.bss` (含 dbcortex 参数库 1600B 等活跃变量)
- `0x2001F800..0x20020000`: 主线程栈 (2KB)

**安全测试区**:`0x20001000..0x20001374`(.data 之前的空闲区, 896 字节) 是稳定的。

`.bss` 之后的 `0x2000FA10..0x2001F800` (~65KB) **理论上是空闲的**,但**实际不可信**——RT-Thread 堆可向上分配到此处。务必先用 `python -m mklink symbols --source <axf> --filter "heap"` 看运行时堆的实际位置;或在写入前用 `vofa` / `superwatch` 读一段确认未被业务覆写。**血泪教训:不查就直接写,会撞 heap 元数据导致 HardFault → 整机重启**。

#### `python -m mklink dump-memory <region> [<region> ...] [--period SEC] [--frames N] [--duration SEC] [--save FILE] [--json]`
公共高速内存 dump，直接调用固件 `cmd.dump_memory(addr1, size1, ..., period)` 并解析 `MPMDMPMD` 二进制帧。别名：`python -m mklink dump ...`。

`<region>` 格式：`ADDR:SIZE`，可重复传入多个区域。默认 `--period 0 --frames 1 --duration 2`，即只采集 1 个完整样本，避免命令意外长期占用串口流模式。

```
# 单次读取 16 字节 RAM
python -m mklink dump-memory 0x20000000:16

# 同时读取两个区域，逐帧 JSON 输出
python -m mklink dump-memory 0x20000000:16 0x20001000:4 --json

# 连续采样 10 个样本，周期 10ms
python -m mklink dump-memory 0x20000000:16 --period 0.01 --frames 10

# 按时长采集并保存 region payload 到本地文件
python -m mklink dump-memory 0x08000000:256 --frames 0 --duration 1 --save flash_payload.bin
```

- `--save` 保存的是已解析出的 region payload，不是包含 magic/CRC 的原始协议帧。
- **最多 15 个 region**。固件数据结构容量虽为 16，但 16 组 `(addr,size)` 加 period
  正好占满 Pika 的 33 参数上限；V4.3.8 实测会使 REPL 失去响应。不得用 SDK 或串口
  绕过。16 个常见连续变量应合并为一个区域；离散快照用 MCP `read_memory_regions`。
- CLI 还限制 `--duration <= 300`、`--frames <= 100000`；AI 发起的单次采集进一步
  限制为 **30 秒**，需要更长观察时分段并在每段后确认设备状态。
- `total_size <= 2048` 走 OLD 帧；`total_size > 2048` 走 B1 分块帧，CLI 会等到 B1 最后一块后计为 1 个完整样本。
- 单次 `cmd.dump_memory()` 总长度默认 **512 KiB**（固件 V4.3.3 实测整片 Flash 稳定，256 个 B1 块全 `flags=0x0000`）。**老固件**（pre-V4.3.3，BUG-5：>64 KiB 末块截尾 512B）请传 ≤32 KiB 的 `ADDR:SIZE` region 规避。
- 如果没有解析到任何帧，CLI 会打印设备返回的可见文本，常见原因是固件未暴露 `cmd.dump_memory` 或设备仍处于异常流模式。

#### `python -m mklink dump-benchmark <ADDR:SIZE> ... [--probe ID] [--duration 3] [--period 0.000001] [--speed PROFILE]`

通过共享后台测量完整 dump 样本的频率、有效载荷吞吐和采样间隔。
活动 MCP 使用 `measure_dump_memory`，共享 SDK 使用同名 `call`；
都复用既有采样会话和完整样本组装器。GUI 正在采集时返回忙，不抢停。

- 1..15 个地址/大小区域，合计不超过 4096 字节；时长 0.5..30 秒，周期 1 微秒至 100 毫秒。
- 首个完整样本最多等待 2 秒；之后开始计算时长，其中前 200 ms 为预热，
  不计入统计。频率和分位数来自下载器时间戳，不代表主机界面刷新率。
- B1 样本使用第一块的时间戳，所有块及区域完整后才计数；周期 `dump-memory`
  也使用这一时间戳语义。CRC、区域、顺序或停止确认失败则整次请求失败，不重试。
- 到时停止可能留下一个不完整样本，结果用 `incomplete_tail` 标记并排除该样本；
  `integrity` 保留协议统计。`parser_dropped_bytes` 可包含命令回显，不能单独当作丢帧数。
- 省略 `--speed` 保持后台当前时钟；显式指定会改变共享下载器的当前时钟，不写工程配置。
  测量只保留间隔计数，不积累全部原始样本；完成后确认恢复命令模式再返回。

#### `python -m mklink flush-memory <item> [<item> ...] [--probe ID] [--no-verify] [--repeat N] [--interval-ms MS]`

通过所选下载器的共享后台写 RAM。CLI、活动 MCP 的 `flush_memory` 和
`SharedDevice.call('flush_memory', ...)` 使用同一校验、分包及执行实现。
GUI 正在 RTT/VOFA/SuperWatch/SystemView 采集时返回忙；由采集方显式停止后再写，
无需关闭 GUI 或 AI 会话。

- 单批最多 **12 KiB / 8 个地址项**；每次请求 1..8 个不重叠区域，
  地址为 32 位整数，合计 1..12288 字节。
- 所有输入先检查，非法后项不会导致前项先写。非重复数据自动拆成至多 30 字节，
  每条命令不超过 230 字符；重复字节使用 `bytes([byte])*count`。
- 默认逐批回读并逐字节比较，单次回读不超过 4096 字节。
  `--no-verify` 只检查固件响应，不证明目标内容；MCP 对应 `verify=false`。
- 硬件异常、非预期文本（包括裸 `flush fail`）、缺失回读或数据不符立即停止。
  不重试、不发送剩余批次、不回滚；此前的批次可能已经写入。
- `--repeat` 为 1..100，`--interval-ms` 为 0..30000；只在前次成功后发送下一次。
  每次单独申请已有后台准入；间隔中 GUI 开始采集时，后续写会被拒绝。

item 支持 `ADDR:BYTE,BYTE` 或 `ADDR:BYTE*N`，地址/字节按十六进制解释，
重复次数为十进制。PowerShell 中用单引号包裹 item。下面地址仅为格式示例，
使用前必须根据目标工程确认专用、稳定且可写的区域。

```powershell
python -m mklink flush-memory '0x20002000:DE,AD,BE,EF' --probe <probe-id>
python -m mklink flush-memory '0x20002000:A5*64' --probe <probe-id> --repeat 2 --interval-ms 50
```

结果包含 `ok`、计划批次数 `batches`、请求字节数 `total_bytes`、
已执行批次 `results`，启用回读时另有 `verified`。
CLI 失败返回非零退出码；共享 MCP/SDK 调用方必须检查 `ok`/`verified`。
没有接收到响应时，不能假定写入未发生；应先检查目标，不自动重放请求。

移除了旧拼写 `flush-memroy` 以及将错误响应降为成功 WARN 的兼容逻辑。
详细固件约束见[静默写边界](flush-memory.md)。

### 读取 Flash

#### `python -m mklink read-flash [--addr <地址>] [--size <字节数>] [--port COM6] [--save <文件名>]`
读取 Flash 数据。自动从 `.mklink/` 配置加载 FLM 算法（Flash 读取需要 FLM）。

```
python -m mklink read-flash --addr 0x08000000 --size 128
python -m mklink read-flash --addr 0x08005000 --size 4096 --save flash_dump.bin
```

### VOFA+ 共享实时变量观测（0.3.0）

VOFA CLI、WebGUI、SDK 和 MCP 复用所选下载器的共享后台。后台用现有
`dump_memory` 二进制采集，通过有界历史和 WebSocket 分发波形；客户端不打开
CDC、不启动另一台网页服务，也不使用旧 `vofa.send` / JustFloat 路径。无需修改
目标程序或下载器固件。详见 [共享后台](shared-runtime.md)。

```powershell
# 按当前 AXF/ELF 的标量类型采集，支持字段和数组元素
python -m mklink vofa rt_tick "g_config.speed" "samples[0]" --probe "电机板" --period 0.01
# 裸地址必须给出类型；相邻通道会合并为对齐读取
python -m mklink vofa 0x20000030 uint16_t 0x20000034 float --probe "电机板" --names adc,filtered
# 连续 1..16 个 float；符号数组仍检查元素类型与边界
python -m mklink vofa 0x20000030 3 --probe "电机板" --duration 60
# 已有采集：不提供通道/周期，订阅它而不改变设置
python -m mklink vofa --probe "电机板" --duration 10
```

新采集默认周期 0.001 秒；`--period` 要求有限正数、不超过 60 秒，实际最小值为
1 us。请求周期不等于实际采样率，状态返回 `actual_rate`、`completed_samples`、
`read_errors` 和 `stream_integrity`。首次 start 成功只证明命令送达；CLI 结束前
检查实际完整样本，空流、终止错误或停止确认失败会非零退出。

通道上限 64，地址按 4 字节边界合并后最多 15 个读取分组，完整 REPL 命令最多
511 UTF-8 字节。超过限制会拒绝，不退回主机逐变量轮询。支持 float、bool、
int8/16/32_t、uint8/16/32_t，以及 char/uchar、short/ushort、int/uint、fp32 等别名。
符号类型由当前目录确定，显式类型须匹配；double、64 位整数和整体结构/数组不能
作为单个通道。读取非原子快照；对齐读取的邻接地址也必须可安全读取，不宜猜测
带读取副作用的外设地址。

`--source` 可在首次连接时指定 AXF/ELF；省略时采用后台当前目录。符号通道保留
路径，每次显式启动重新解析；源内容变化时拒绝沿用旧描述，不自动切换工程或
抢停其他采集。裸地址通道始终按用户指定地址处理。

`--duration` 默认 30 秒，0 表示运行到 Ctrl+C。创建采集的 CLI 在正常结束时
尝试停止一次；若另一个 AI/SDK 仍在订阅，后台拒绝停止，CLI 提示保留采集后
只解除自己。借用已有采集的 CLI 始终只解除自己。删除了旧 `--stop`；不要用新
临时客户端代替创建者强停，可先让订阅者退出，再从创建者或 GUI 显式停止。

GUI 已移除 VOFA+ 入口和独立页面；实时曲线使用仪表盘 SuperWatch。
VOFA 第三方兼容协议和后台能力保留。`--visualize`、`--no-browser`、旧 `--host`、
`--port-http`、`--max-points` 和自定义私有 HTML 服务入口已删除。

MCP 使用 `gui_call` 的 `vofa_start/stop/pause/resume/status/history` 能力；
共享 SDK 使用同名 `call`，不增加专门的 MCP 服务。`vofa_history` 最多保留 500
个样本。浏览器波形使用 Float32，大于 2^24 的整数可能失去低位精度；精确判断
请读取历史或停止采集后用内存/变量接口。非有限浮点在图表/历史中替换为 0。
有限缓冲和断线不保证无损。

### AXF/DWARF 调试增强

#### `python -m mklink typeinfo --source <firmware.axf> [--var 名称 | --struct 名称 | --enum 名称 | --list-structs | --list-enums]`
默认使用随 MKLink 内置的 `pyelftools` 解析 DWARF 类型信息，不依赖用户工具链。

```
python -m mklink typeinfo --source path/to/firmware.axf --var g_appState
python -m mklink typeinfo --source path/to/firmware.axf --struct AppConfig
python -m mklink typeinfo --source path/to/firmware.axf --enum AppMode
```

#### `python -m mklink symbols --source <firmware.axf> [--filter <正则>]`
从 ELF/AXF 列出 RAM 全局变量。`--filter` 为正则，用于缩小符号列表。只有用户明确传 `--elf-backend external` 时才调用本机 `readelf`。

```
python -m mklink symbols --source path/to/firmware.axf
python -m mklink symbols --source path/to/firmware.axf --filter "counter|sensor"
```

#### `python -m mklink watch <变量1,变量2> --probe <设备ID或别名> [--source <firmware.axf>] [--period 秒]`
通过共享后台批量读取 1..16 个标量，支持 typedef、`struct.field`、数组元素和当前 C 布局。
未指定工程和符号文件时使用后台当前配置；多下载器必须明确选择。周期模式用 Ctrl+C
停止并只解除自己的会话。采集冲突或读取失败会退出报错，不抢停 GUI、不重试或转为直连。
多变量读取不保证目标原子快照；高速曲线仍使用 SuperWatch。`--profile` 接受仅含
`{"variables": ["变量路径"]}` 的 JSON；原未实现的 `--struct` 参数已删除。

```
python -m mklink watch g_counter,g_sensor --probe "电机板"
python -m mklink watch g_config.setpoint,samples[1] --probe "电机板" --period 1
```

#### `python -m mklink superwatch <变量/字段/寄存器...> [--source <firmware.axf>] [--svd <device.svd>] [--visualize]`
基于 MKLink `cmd.dump_memory` 二进制帧内的设备时间戳连续采样，适合同时观察 RAM 变量、`struct.field` 路径和寄存器。变量解析依赖 AXF/DWARF；寄存器可使用内置寄存器表，或通过 `--svd`/Keil Pack 自动发现 CMSIS-SVD 后支持外设寄存器名。未加 `--visualize` 时输出采样 JSON；加 `--visualize` 时启动 Web 看板，可搜索/添加 AXF 符号或寄存器。

`read_ram`/`read_memory` 只用于单次 RAM 快照、变量详情和 AI 故障分析，不用于 SuperWatch 曲线采样，也不作为固件或连接不支持二进制流时的后备方案。此时 SuperWatch 会明确报错并停止。

常用参数：
- `--period 0.1`：采样周期，单位秒
- `--duration 30`：运行时长，`0` 表示持续运行到手动停止
- `--port COM6`：指定 MKLink 串口；省略时自动检测
- `--host 127.0.0.1 --port-http 0`：Web 看板监听地址和端口，`0` 表示随机端口
- `--no-browser`：启动 Web 服务但不自动打开浏览器
- `--max-points 500`：图表保留的最大点数

```bash
python -m mklink superwatch g_counter,g_sensor --source path/to/firmware.axf --period 0.1 --duration 30
python -m mklink superwatch g_config.setpoint,SCB.CFSR --source path/to/firmware.axf --visualize --period 0.1
python -m mklink superwatch TIM2.CNT,ADC1.DR --svd path/to/device.svd --visualize --duration 0
```

**Dump Memory 连续采样协议**

调试时钟分为 `low`（4 MHz）、`medium`（10 MHz，默认）、`high`（20 MHz）、`ultra`（30 MHz）。SuperWatch 的“采样调试速率”与 CLI/MCP 使用同一组档位；原 `high` 配置继续表示 20 MHz。它调整调试链路时钟，实际采样率应以 dump 时间戳测量。

CLI 使用 `python -m mklink debug-speed ultra --project-root <工程目录>`；加 `--save` 可保存供后续连接使用。`dump-memory` 和 `dump-benchmark` 的 `--speed ultra` 可为本次采样选择 30 MHz。MCP 使用 `set_debug_speed(profile="ultra")`，或 `measure_dump_memory(..., speed_profile="ultra")`。

ARM SWD 和 HPM JTAG 使用相同的 4/10/20/30 MHz 档位；20/30 MHz 必须由配套探针固件明确确认相应接口与内核，旧固件仅回显设置时钟不算确认。确认失败会恢复 1 MHz 并报错。档位回执不证明任意目标或接线稳定，应按对应板卡和固件的实测结果选择。CLI/MCP 切档前先停止流；Web 应用档位会先停止当前采集。默认保持 10 MHz。

档位设置改变探针的调试时钟，同一连接中的 RTT、SystemView 等内存访问也使用该时钟。Keil、在线烧录和脱机脚本会按各自配置重新设置时钟；不能用 SuperWatch 的档位代替下载配置。采样报告应分别注明包含批间空隙的持续速率与批内速率，不能混用。

SuperWatch 使用设备主动推送的二进制流，不以主机循环读内存代替。新版 V4 协商
CDC 多路复用微秒采样；当前开发固件设置 1 μs（`0.000001` 秒）请求全速，
更长周期按实际读取能力定时，读取超时不额外等待。早期开发固件采用过 20 μs 分界，
测全速统一使用 1 μs。RTT 独立按 1 ms 轮询。
单个对齐 4 B 变量可走批量快路径；速率依目标和区域布局而变，设置值不是速率保证。
测峰值时单独运行 SuperWatch，共存测试另测。旧固件使用
`cmd.dump_memory(addr1, size1, ..., period)` 的 `MPMDMPMD` 帧；旧 MUX 为毫秒采样。
公共 CLI `python -m mklink dump-memory ...` 自动选择协议。旧 `--dump-mem` 仍接受。

判断数据质量时分开记录：目标采样时间戳的相邻间隔、持续采样率、协议序号缺口、
传输丢弃和客户端历史覆盖。`drops=0` 仅说明相应传输/缓存层没有报告丢弃，不能
证明采样间隙内没有遗漏目标变化；未知目标信号也不能据此计算“误码率”。GUI
栅格和缩放仅改变显示，不改变设备采样周期。暂停/停止后可缩放，恢复时保留时间
窗口宽度；历史不足时只能显示已保留的数据。

```bash
python -m mklink superwatch g_counter,g_sensor --source path/to/firmware.axf --visualize --period 0.01
```

- `total_size <= 2048`: OLD 普通帧。
- `total_size > 2048`: B1 分块帧，每块最大 2048B，包含 `block_index` / `block_count` / `block_crc32`。
- SuperWatch 只合并相接或重叠的地址，不跨地址空洞多读；V4.3.8 真机测量显示跨 16B 空洞已降低采样率。
- SuperWatch 最多提交 **15 个离散 region**。固件帧虽可容纳 16 个 region，但 V4.3.8 的 Pika 文本入口在 16 组地址/长度加 period 时会超过安全参数边界。
- `build_dump_mem_command()` 默认允许单次最多 **512 KiB**（V4.3.3 实测整片 Flash 稳定）；老固件请传 ≤32 KiB region；更大范围仍应由 host 分块。
- V4.3.1 官方 API 直测（2026-06-07）：`0x08000000/256`、`0x20010200/32`、`0x08020000/2049` 均 PASS，flags=`0x0000`，B1 为 2048B + 1B 两块。
- 若 flags=`0x0004`，含义是 `Region error`，优先排查目标供电、Vref、SWD、NRST、MCU 运行/低功耗/复位状态；这不是 host parser CRC 失败。

#### `python -m mklink hardfault [--source <firmware.axf>] [--sp <异常栈帧地址>]`
读取 SCB Fault 寄存器并解码 CFSR/HFSR。提供 `--sp` 时再读取 32 字节异常栈帧，并默认通过内置 DWARF line program 映射 PC/LR；显式 external 模式才调用本机 `addr2line`。

```
python -m mklink hardfault --source path/to/firmware.axf --sp 0x20001FF0
```

#### `python -m mklink memmap --source <firmware.axf> [--json]`
解析 AXF section header，输出 Flash/RAM 占用。

```
python -m mklink memmap --source path/to/firmware.axf
python -m mklink memmap --source path/to/firmware.axf --json
```

#### 变量地址查找

变量地址可通过查看 MDK 编译生成的 `.map` 文件或使用 `rtt-find` 命令获取：

```bash
python -m mklink rtt-find "path/to/build/Project.map"
```

---
