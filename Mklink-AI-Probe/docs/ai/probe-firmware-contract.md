# MKLink V3/V4 固件与上位机契约

> 本页是维护者资料，不进入用户 Skill。它记录下载器固件、PC 上位机和官方手册之间的稳定契约，
> 供没有 V3/V4 固件源码的上位机开发者使用。修改任一端的公开能力、边界或线格式时必须同步本页和测试。

## 1. 基线与范围

| 层 | 基线 | 本轮范围 |
| --- | --- | --- |
| V3 固件 | `MicroLinkV3/main`，审计基线 `e4b5722` | Arm Cortex-M、SWD/CMSIS-DAP、烧录、RTT、SystemView、变量流、UART、离线下载 |
| V4 固件 | `MicroLink_Plus/main`，审计基线 `16ba901` | V3 公共能力，加 RS485、SD、显示、功率/供电与本机交互 |
| PC 上位机 | `codex/v0.1.9-development`，审计基线 `dcc57a5` | SDK、CLI、MCP、FastAPI、WebGUI、Tauri、Skill、Site Agent |
| Arm HIL | STM32F103RC 和 STM32H743 | F103 做通用功能及 16 路吞吐；H743 做 D-Cache/存储域一致性 |

HPM/RISC-V/JTAG 性能和板型配置在后续专项处理。本轮只要求共享代码不退化，不据此扩展 HPM 支持承诺。

## 2. 型号能力

| 能力 | V3 | V4 | 上位机职责 |
| --- | --- | --- | --- |
| USB High Speed CMSIS-DAP | 支持 | 支持 | IDE/pyOCD/后端通过 CMSIS-DAP 使用 |
| GPIO 模拟 SWD | 支持 | 支持 | 单探针串行占用，不与其他 SWD 流并发 |
| Arm FLM/BIN/HEX 烧录 | 支持 | 支持 | 选择目标与算法、校验、恢复运行 |
| MSC/脱机下载 | SPI NOR | SD 卡 | V3 使用固定脚本；V4 可选择脚本名 |
| Python Console | 支持 | 支持 | PC 控制命令及二进制流共用该接口 |
| USB 转 UART | 支持 | 支持 | 串口工具和 Modbus RTU 的底层链路 |
| USB 转 RS485 | 不支持 | 支持 | V4 独立 CDC；Modbus 协议仍在上位机层 |
| RTT | 支持 | 支持 | 目标 RTT 控制块发现、上下行与会话释放 |
| SystemView | 支持 | 支持 | 与 RTT/SWD 互斥，停止后恢复 Console |
| VOFA/SuperWatch | 支持 | 支持 | 连续曲线使用 `dump_memory` 二进制流 |
| LCD/编码器/本机界面 | 不支持 | 支持 | 不作为上位机通用能力的前提 |
| 自动跟随 VREF | 未公开 | 支持 | 必须按型号显示；改变 VCC 前取得用户确认 |
| YMODEM | 不作为稳定公开能力 | 发送路径实验性；接收未实现 | 修复和 HIL 前不得宣传 receive |

“支持”表示源码存在相应实现，不等同于本轮已经完成真机发布验收。官方手册的型号矩阵必须同时记录最低固件、
测试 ID 和最近真机证据，不能只放一个勾。

## 3. USB 枚举契约

V3/V4 当前共用 `VID:PID = 0x0D28:0x0202`。接口用途如下：

| 接口 | V3 | V4 |
| --- | --- | --- |
| CMSIS-DAP Vendor Bulk | EP OUT `0x02` / IN `0x81` | 相同 |
| MSC | OUT `0x04` / IN `0x83` | 相同 |
| UART CDC | OUT `0x05` / IN `0x85` / INT `0x86` | 相同 |
| Python Console CDC | OUT `0x07` / IN `0x87` / INT `0x88` | 相同 |
| RS485 CDC | 无 | OUT `0x09` / IN `0x89` / INT `0x8A` |

上位机必须综合 USB serial number、产品字符串、CDC interface string、复合设备父子关系、ContainerId、
接口号和后续 capability 查询识别端口。不得只依赖 VID/PID、COM 序号或模糊 FriendlyName。

## 4. 调试传输所有权

一只探针同一时刻只能有一个调试传输 owner：

```text
IDLE / CMSIS_DAP / FLASH / SUPERWATCH / DUMP / RTT / SYSTEMVIEW / OFFLINE
```

当前固件主要依赖若干 `volatile` 状态字段避让，不能提供原子所有权保证。0.1.9 上位机继续强制单探针串行、
复用连接和停止后排空；固件改造应增加统一 acquire/release、busy ACK、取消和错误恢复。owner 变化、reset、
烧录、CMSIS-DAP 命令或 SWD/JTAG 切换时，必须失效 DP SELECT、AP CSW 和 TAR 等缓存。

## 5. `dump_memory` v1

### 5.1 普通帧（总数据不超过 2048 B）

所有整数为小端：

```text
magic:u64
timestamp_us:u64
frame_length:u16
region_count:u8
repeat region_count:
    region_index:u8
    region_size:u16
    data[region_size]
flags:u16
frame_crc32:u32
```

### 5.2 分块帧（总数据大于 2048 B）

```text
magic:u64
timestamp_us:u64
frame_length:u16
region_count:u8
flags:u16
total_size:u32
block_size:u16
block_index:u16
block_count:u16
block_data_crc32:u32
repeat region_count:
    region_index:u8
    region_size:u16
    data[region_size]
frame_crc32:u32
```

固定值和已验证边界：

| 项目 | 当前值 | 主机安全策略 |
| --- | ---: | --- |
| 固件 region 容量 | 16 | 快照可用 16；连续流最多 15 |
| Pika 参数容量 | 33 | 16 组地址/长度加 period 恰好 33，真机已出现 REPL 失去响应，因此发送前拒绝 |
| Pika 命令行缓冲 | 512 B | 所有入口生成命令后再次检查长度 |
| 最大帧缓冲 | 4096 B | 解析器拒绝无效 frame length |
| 分块数据 | 2048 B | 校验 block index/count 和两个 CRC |
| 快速采样阈值 | `<50 us` | 解释为尽快采样，不承诺 1–49 us 周期 |
| 连续流停止排空 | 至少 50 ms | 发送 stop、排空、关闭连接后再执行普通命令 |

v1 没有 protocol version、frame type 和 sequence number；普通帧与分块帧的 flags 位置也不一致。
0.1.9 必须冻结兼容布局。后续 `dump-v2` 采用新 magic 或显式版本协商，并增加：

- `version`、`frame_type`、`header_size`；
- 单调 `sequence`；
- 请求周期、有效周期和单次采集耗时；
- SWD WAIT/FAULT/parity、USB backpressure 和 dropped counters；
- 统一固定头和明确 stop ACK。

## 6. PC/AI 安全边界

| 入口 | 边界 |
| --- | --- |
| MCP 单次内存读/写 | 4096 B |
| MCP 批量快照 | 最多 16 项、返回总计 4096 B |
| `dump_memory` 连续流 | 最多 15 region；不得回退为循环 `read_ram` |
| MCP RTT/SystemView/串口采集 | 最长 30 s |
| `flush_memory` | 最多 8 项；已验证总量上限 16300 B，仍受命令长度限制 |
| 超时 | 仅检查一次状态，随后取消/释放；禁止盲目重试 |
| 并发 | 单探针串行；CLI/MCP/GUI/IDE 不得交叉占用 |
| VCC | 每次改变输出前确认具体电压和连接方式；目标已有外部供电时默认不并联 |

## 7. 已确认的固件风险

### 发布阻断候选

1. typed VOFA 的 `double` 路径计算 8 B 类型大小，却固定只读 4 B，会解释未初始化后半部分。
2. SWD 各使用者缺少统一 owner，存在检查与开始之间的竞态。
3. 多个 Pika API 缺统一参数数量、类型、范围和单出口 cleanup；失败后可能永久保持 busy。
4. V3 `cmd_read_flash` 存在空文件指针关闭风险。
5. MSC 中 `MicroLink.rbl` 拖入路径的 write/close 和 `enter_bootloader()` 实现不完整，不能作为可用升级方式宣传。

### 高优先级

1. RTT/SystemView 对目标 RAM 中损坏的 buffer 数量、channel 和扫描范围校验不足；禁止使用目标值创建 VLA。
2. `SYSVIEW_REC_GetOutgoing()` 存在未初始化返回路径。
3. UART/RS485 没有完整 line-coding 校验、实际波特率误差和 overflow/backpressure 统计。
4. V4 Pika serial 对负数或超大 read length 缺少限制。
5. YMODEM 文件数量、字符串长度和 malloc 失败清理不完整，receive 为空实现。
6. MSC 与固件 FATFS 缺介质 owner，主机写盘与固件读写可能竞态。

### 维护债务

- V3/V4 `.version` 都不能代表实际固件能力；需要真实版本和 capability schema。
- `read_cpu_reg` 实际是内存读历史别名，不是 R0–R15 核心寄存器 API。
- V4 CMake 宽泛编入 Arm-2D 示例和 loader，应改为显式使用清单。
- V3/V4 的公共 SWD、流和 Pika 逻辑持续漂移，应在契约测试稳定后抽出共享核心或生成同步补丁。

## 8. Arm 真机夹具

### STM32F103RC

作为通用功能和 16 路吞吐主夹具：

- 16 个连续 `float`/`uint32_t`；
- 16 个离散地址和混合类型；
- 1 kHz、5 kHz、10 kHz、20 kHz 请求及 fast 模式；
- RTT 上下行、SystemView、RAM 全零写回恢复、core register、HardFault；
- 在线 BIN/HEX/FLM 烧录、verify、reset；
- V3/V4 分别执行 start/stop、配置切换、掉电和拔插恢复。

Cortex-M3 没有 D-Cache。它可以验证协议吞吐和稳定性，不能证明缓存一致性。

唯一符号文件固定为：

`E:\PHDZ\PROJECT\liu\STM32F103_test\STM32F103RC\build\keil\Obj\rt-thread.axf`

工程根目录的旧 `rt-thread.elf` 已删除。后续构建生成 AXF/BIN/manifest 同源校验，不自动搜索或回退到其他 ELF/AXF。

### STM32H743

专门覆盖 F103 无法验证的场景：

- AXI SRAM cacheable 区域与 non-cacheable 区域对照；
- dirty D-Cache、显式 clean 后的结果；
- DTCM 与跨 SRAM bank；
- ISR/主线程并发更新；
- 16 路高吞吐和缓存错误可诊断性。

## 9. 更新规则

以下任一变化都必须同时更新本页、机器可读 capability 表、主机测试和官方手册矩阵：

- USB descriptor、interface 或产品字符串；
- Pika API、参数数量、命令行长度、返回/错误语义；
- `dump_memory` 帧布局、CRC、flags、region/size/period 边界；
- owner、停止、排空、reboot 或掉线恢复；
- V3/V4 型号能力；
- 固件最低版本或已验证性能。

固件修改由维护者自行提交；MKLink 上位机和官方手册按各自仓库流程提交。测试报告必须记录固件 commit、
上位机 commit、目标 AXF SHA-256、接线、SWD 时钟、请求周期、实际周期和全部丢帧计数。

## 10. HPM 延期登记

HPM 系列后续单独测试和修改。本轮不调整配置或扩大支持范围。已知需复核项包括：

- 上位机与 V4 固件的部分板型 flash 配置字存在漂移；
- V3/V4 RISC-V 恢复逻辑不一致；
- RISC-V 内存写错误路径含下载器 MCU 自身 `ebreak` 风险。

正式 HPM 专项完成前，官方手册只列已经具名验证的目标和条件，不写“全系列”。
