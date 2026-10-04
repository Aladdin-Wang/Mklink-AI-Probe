# 串口调试

> 触发词：serial、UART、profile、open、send、dashboard、auto-reply
> 返回索引：[SKILL.md](../SKILL.md)

## 串口调试

通用 UART 串口调试工具，可独立于目标 MCU 使用。0.3.0 的 `send`、`log`、`monitor` 和 `open`
通过共享后台通信；独立 Dashboard 命令仍在迁移中。

共享 MCP/SDK 可用 `gui_call("serial_history", {})` 从当前尾部开始读取；后续传
`session`、`after=next_seq` 和可选 `limit`（1–256）。返回原始字节批次的 `hex`、
`size`、`port`、`direction`、`seq` 和批次发布时间 `timestamp_ns`，不需要换行。
最多保留 512 批，每批至多 4096 字节；`dropped_batches` 报告全端口被覆盖批数。
客户端先推进全局游标，再筛选端口；慢消费者不能把这当无损日志。停止后可读最后
批次，重新启动后的旧会话返回 409，需显式重新取尾部。此接口不包含 YMODEM
协议字节或 Profile 解析字段，不会打开串口或发送数据。

日志示例中的 `<LOG_DIR>` 须替换为[已选工作根目录](work-files.md)下本次任务的
日志目录绝对路径，并先创建该目录，不能直接写到当前目录。

### 列出可用端口

```bash
python -m mklink serial list
```

自动排除 MKLink 的 `MI_04` Python Console 命令口；保留 `MI_02` USB to UART，
并在 V4 上保留 `MI_06` USB to RS485，供通用串口或 Modbus 使用。

### 交互式终端

```bash
# ASCII 模式
python -m mklink serial open --port COM3 --baud 115200

# HEX 模式 + 协议解析
python -m mklink serial open --port COM3 --baud 115200 --mode hex --profile my_protocol.json

# 带日志和自动应答
python -m mklink serial open --port COM3 --baud 115200 --log "<LOG_DIR>/data.txt" --auto-reply rules.json
```

用 `--probe` 选择后台，端口参数必须匹配已有连接。空闲时创建连接，退出时停止；
借用 GUI/AI 连接只解除订阅。普通文本保留首尾空格并追加 CR LF；输入可以来自
键盘、UTF-8 管道或文件，EOF 发送最后一行后结束，`--duration` 可限制运行时间。
默认 0 表示直到退出或 EOF。输入一行最多 8192 字符，实际发送最多 4096 字节。

终端快捷键：Ctrl+C/Ctrl+Q 退出，Backspace 删除输入字符，Ctrl+F 设置过滤，
Ctrl+L 清屏。输入 `>quit` 退出、`>mode hex` / `>mode ascii` 切换显示模式，
`>filter 正则` 设置过滤，`>filter` 清除过滤。Ctrl+H 按退格处理。
`>hex AA55010300` 发送 HEX，`>file 文件路径` 发送最多 4096 字节的文件；不会把
大文件拆分重发。非法输入或发送未确认均非零退出，不自动重试。成功确认只表示
后台完成写入，不表示目标设备已经执行。接收/日志语义与共享 monitor/log 相同。

`--auto-reply` 指定的规则只在共享后台执行一份，不在每个终端各执行一次。新连接
可同时用 `--profile` 定义后台帧匹配；已有连接必须匹配显式指定的规则及 Profile，
否则在发送/日志开文件前拒绝。省略 `--auto-reply` 只借用现有配置，不关闭已有应答；
单独使用 `--profile` 只在客户端被动解码。规则和 Profile 总请求不得超过共享接口
16 KiB 限制。停止/重启或协议传输会取消待发旧应答。应答配置属于连接，终端借用者
退出不清除它；需要变更时先显式停止该连接，再重新创建。

### 单次发送

```bash
# 发送 UTF-8 文本（不展开反斜杠转义）
python -m mklink serial send --port COM3 --baud 115200 "AT"

# 发送 AT 后跟实际 CR LF
python -m mklink serial send --port COM3 --hex "41 54 0D 0A"

# 发送 HEX，重复 5 次，间隔 0.5 秒
python -m mklink serial send --port COM3 --hex --count 5 --delay 0.5 "AA550103"
```

发送复用 GUI/AI 的共享串口连接。多探针用 `--probe` 选择后台；`--baud`、
`--databits`、`--stop`、`--parity` 必须与指定端口的现有参数一致。多端口会话
只向选定端口发送，其他端口保持不变。空闲时建立连接，完成后释放；借用 GUI/AI
连接时只解除本客户端订阅，不关闭其他使用者的串口。

发送数据不能为空，次数必须为正整数，间隔为 0–3600 秒的有限数，波特率为
1–4000000 的整数。HEX 与参数在连接前验证。每次发送得到确认后打印 TX；失败
非零退出并停止后续发送，不自动重试。响应丢失或短写可能已经发出部分数据，
不能按“未打印 TX”推断从未发送。活动 YMODEM 传输期间拒绝普通发送。

### 多端口监听

```bash
python -m mklink serial monitor --port COM3 --port COM4 --baud 115200 --log "<LOG_DIR>/multi.csv"
```

监听为被动输出，不读取键盘或发送数据，可在没有 TTY 的管道/AI 进程中运行。
用 `--probe` 选择后台，`--duration 60` 监听约 60 秒，默认 0 表示直到 Ctrl+C。
可选择 1–16 个不同端口，所选端口必须全部匹配当前连接参数；其他端口不受影响。
已运行会话可以只监听其中一部分端口。

默认文本模式按端口和 RX/TX 分别增量解码 UTF-8，完整行即时显示；未换行内容在
空闲约 100 ms、达到 4096 字符或退出时显示并标记 `[partial]`。字节跨批时不会
把不同端口或方向的半字符拼起来。HEX 模式逐批显示，不等待换行。终端控制字符
转义显示，不执行设备发来的清屏等控制序列。

`--filter` 是显示过滤正则：匹配 UTF-8 显示记录、HEX 字符串或解码附注。记录因
长度/空闲边界拆分时，过滤不跨越这些显示边界。`--log` 仍记录全部选中端口的原始
数据，显示过滤不会删改日志；`--profile` 被动解析各端口的 RX，不触发自动应答。
任何选中端口出错或历史覆盖均非零退出。创建/借用、文件失败和最终批次处理与
下述共享日志语义相同；`open` 的键盘快捷键不适用于被动 `monitor`。

### 无头日志模式

```bash
python -m mklink serial log --port COM3 --baud 115200 --output "<LOG_DIR>/data.csv" --format csv --duration 60
```

### Web Dashboard

共享 WebGUI 的“串口助手 → 协议与自动应答”可导入 Profile 和应答规则、添加/删除
规则，并在打开串口时应用。运行期间显示后台实际配置，须先关闭连接再修改；
导入 Profile 不会隐式启用其内嵌应答，只有规则列表中的应答执行。
配置上限为 16 KiB，规则最多 64 条。类型与字节数不匹配或非有限缩放系数会被拒绝。

解析字段显示所选端口的最新 RX 帧，约每秒刷新，可能跳过中间帧；含时间、序号、
CRC、字段值/原始值/单位和最多 256 字节原始预览。切换端口不会混入其他端口字段。
MCP/SDK 的 `serial_status` 返回同一份 `session` / `latest_frames`；重启更换会话并
清空快照，停止保留最后一帧。设备非有限浮点显示为 `nan` / `inf` 等字符串。
需要连续原始记录时使用共享 `serial log`，不能把最新帧快照当无损抓包。

以下独立 `dashboard` 命令尚在迁移，仍直接占用串口，不能与共享连接同时打开；
旧服务存在慢 SSE 客户端阻塞 reader 的已知问题。当前优先使用共享 WebGUI。

```bash
python -m mklink serial dashboard --port COM3 --baud 115200 --profile protocol.json
```

浏览器自动打开，提供实时数据流、发送面板、命令队列、过滤器和帧解析视图。

### 本地资源释放（不需要 FastAPI）

Agent 和命令行优先使用本地 `resources` 命令释放串口资源；不需要启动 `mklink serve` 或 FastAPI。

```bash
# 查看本地 MKLink/串口锁状态
python -m mklink resources status --port COM3

# 清理指定串口的 stale 锁，并停止当前进程内的 serial dashboard manager
python -m mklink resources release-serial --port COM3

# 活进程仍占用时仅报告 PID；确认需要终止 Mklink 锁文件记录的占用进程时再显式加 --force
python -m mklink resources release-serial --port COM3 --force
```

默认模式只移除 owner PID 已不存在的 stale lock，不会杀外部串口助手、Keil 或其它仍在运行的进程。若是外部程序占用 COM 口，需要关闭外部程序；`--force` 只应在确认锁文件记录的 owner 可以终止时使用。

### 共享日志的输出与失败语义

`serial log` 可与 GUI、AI 和其他日志客户端同时运行，`--probe` 选择共享后台。
已有连接必须包含相同端口及波特率、数据位、停止位、校验位；参数不一致时退出，
不会修改其他客户端的连接。`--duration` 必须是有限非负秒数，0 表示直到 Ctrl+C。
Profile、参数和输出路径先验证，连接核对通过后才打开日志文件；打开文件会覆盖
指定输出文件。启动者停止自己创建的连接，借用者只退出；其他使用者存在时保留连接。

日志从取得当前尾部游标开始，按批次写入并刷新，包括未换行、二进制和帧尾残片。
CSV 使用固定列 `timestamp,direction,port,raw_hex,ascii,decoded_json`，逗号、引号和
换行按 CSV 标准引用。`raw_hex` 可重建所记录的全部原始字节；TXT 同时保存 HEX
与转义的可打印文本。时间来自后台批次发布时间，不是硬件采样时间。

`--profile` 在日志进程中被动解码 RX，完成的帧及字段写入 `decoded_json` 数组或
TXT 附注；同批多帧、跨批帧均可解析，原始字节只记录一次。不会启用 Profile 自动
应答，也不改变后台 Profile；本地未完成帧缓存限制为 1 MiB，超限失败退出。

日志不承诺无限缓存或无损捕获。检测到历史覆盖、连接会话改变、端口失败或文件
写入/关闭失败，会非零退出，不显示“日志已保存”，保留已有部分文件供检查。
正常结束时读取已经提交的剩余批次；自建连接还会先停止并提交后台最后一批。
借用连接继续运行时，以结束读取所见的已提交批次为界，尚未提交的字节不属于本次
日志。YMODEM 协议字节仍在独立追踪通道，不混入普通日志。

### 协议 Profile 管理

```bash
# 从 C 源码自动生成 Profile
python -m mklink serial profile detect --source inc/uart_protocol.h
python -m mklink serial profile generate --source inc/uart_protocol.h --output .mklink/serial_profile.json

# 查看 Profile 内容
python -m mklink serial profile show --profile .mklink/serial_profile.json
```

### Profile JSON 格式

```json
{
  "name": "my-protocol",
  "version": "1.0",
  "frame": {
    "header": "AA55",
    "tail": "55AA",
    "length_field": {"offset": 2, "size": 1, "includes_header": false},
    "crc": {"algorithm": "crc16_modbus", "offset": -2, "scope": "payload"}
  },
  "fields": [
    {"name": "cmd", "offset": 3, "size": 1, "type": "uint8", "enum": {"0x01": "READ"}},
    {"name": "temperature", "offset": 4, "size": 2, "type": "int16", "scale": 0.1, "unit": "℃"}
  ],
  "auto_reply": [
    {"match_hex": "AA5501", "reply_hex": "AA558100", "description": "ACK"}
  ]
}
```

支持 CRC 算法：`crc8`, `crc16_modbus`, `crc16_ccitt`, `crc32`, `checksum8`, `checksum16`

