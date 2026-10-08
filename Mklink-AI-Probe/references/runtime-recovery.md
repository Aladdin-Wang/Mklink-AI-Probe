# 控制权与恢复

适用：连接失败、GUI/AI 争用、窗口退出后仍占用、MCP 超时或后台不可达。
以下新入口随 0.3.1 修复提供；先检查实际 MCP schema 或 CLI `--help`。
只有 Skill 文本更新、仍运行旧后台时，不代表具备新行为。

## 先分清三种占用

- **后台会话/采集**：GUI、DeepSeek 等 AI 客户端共用一个后台，只有后台打开命令口。
  GUI 退出只移除窗口；AI 的 MCP 进程可能还在编辑器内续约。模型结束一段回答不等于
  MCP 进程退出。正常任务收尾应调用 `disconnect`，借用采集时不替其他使用者停流。
- **操作系统串口持有者**：由指定端口的资源状态检查 PID；后台之外的串口助手也可能
  占用。COM 号、GUI 窗口 PID、后台 PID 不是同一概念。锁文件存在本身不证明仍占用。
- **下载器目标调试占用**：CMSIS-DAP/IDE 与 MCU 的调试所有权；结束 Python 进程不能
  保证释放 IDE 或固件持有的目标调试状态。USB 身份枚举不需要访问目标 MCU，不能把
  `target busy` 当成 USB 设备身份错误。

## 查明现状，不先连接硬件

1. `ping` 核对当前 MCP 为 `mode="shared-cdc"`，检查可用工具；`discover_probes`
   取得用户指定下载器的稳定 ID。多下载器不能挑第一台。GUI 已配置工程时连接省略
   `project_root/axf/mcu`，不要用 AI 的当前目录覆盖 GUI 工程。
2. `runtime_status(probe=ID)` 查询现有后台。无需先 `connect`，不启动新后台、不打开
   CDC、不续约 AI 会话。查看 `pid`、`instance_id`、`clients`、`streams`、`busy`、
   `operation`、`jobs`。`clients[].id` 是可公开的管理 ID，不是会话密钥或进程 PID。
   `streams[].owner.active=false` 表示原采集所有者已离开，仍须核对订阅者。
3. MCP 不可用时，从当前完整 Skill 的根目录使用 CLI：

```powershell
python -m mklink runtime status
python -m mklink runtime control status --probe "下载器ID或别名"
python -m mklink resources status --port COM9 --json
```

`COM9` 只作示例，使用当前枚举端口。旧版没有 `runtime control` 时，用该版本 GUI 的
后台管理页读取同样信息；不能因为缺工具改为低层 `Device`、原始串口或另一套私有后台。
共享版本/协议不一致时，先用旧版入口正常退出旧后台，再启用新版。当前修复协议为 50，
官方旧 0.3.0 可能仍是 49；版本号相同也不能假定内部协议兼容。

## 按用户意图恢复

正常读取 GUI 已有数据：`connect(probe=ID, client_name="DeepSeek/当前任务")`，
RTT 无参数 `rtt_start()` 订阅，然后读取历史/通道。完成后 `disconnect`。
不要通过重配 AXF、停止采集或关闭 GUI 来完成普通读任务。

用户要求结束旧会话、释放下载器或恢复连接时，先查询上述状态，再执行对应动作。
已有明确授权就直接处理，不重复询问；正在进行的烧录/擦除或写操作必须先等结果，
结果未知时保留请求 ID 查询，不能重放。

| 已确认状态 | 对应动作 |
|---|---|
| 仅自己的 AI 会话结束 | `disconnect`；后台保留其他使用者 |
| GUI 全部退出，遗留采集只有自己订阅 | 用户要求停止时调用对应 `rtt_stop`/`superwatch(action="stop")`；新后台允许接手。未订阅先无参数订阅，不能覆盖参数 |
| 另一个已不用的 AI 会话仍续约 | `runtime_control(action="detach-client", probe=ID, client_id=管理ID, confirm=true)`；旧心跳被拒绝，不再保持占用 |
| 要停遗留采集且已没有 AI 订阅者 | `runtime_control(action="stop-acquisition", probe=ID, stream="rtt", confirm=true)`；其他流使用实际名称 |
| 要释放命令口、保留后台窗口 | 结束目标会话并停止目标采集后，`runtime_control(action="release-device", probe=ID, confirm=true)` |
| 要退出整个后台 | 无在途任务、结束所有 AI 会话、停止所有采集（含 UART/Modbus）、关闭其他窗口后，`runtime_control(action="stop-backend", probe=ID, confirm=true)` |

CLI 等价入口，例如：

```powershell
python -m mklink runtime control detach-client --probe "下载器ID" --client-id "状态中的管理ID" --confirm
python -m mklink runtime control stop-acquisition --probe "下载器ID" --stream rtt --confirm
python -m mklink runtime control release-device --probe "下载器ID" --confirm
python -m mklink runtime stop --probe "下载器ID" --confirm
```

这些动作仍由后台检查任务、订阅者及窗口，拒绝时按原因处理，不循环重试或强制越过。
若只退出自己的全部客户端，无任务时后台约 5 秒后开始正常清理；采集线程与网络排空
还需时间。诊断轮询也会延后空闲期限，不要持续查状态同时等待后台空闲退出。

## 后台不可达或“杀不掉”

先记录具体错误与同一下载器的端口持有者，不能仅凭“连接失败”判为固件或进程死锁。
新后台重启/USB 换口后可显式 `connect(probe=原ID)` 重新发现，不自动重放之前操作。
若仍失败，按 PID 核对进程命令行、是否属于当前用户、是否有在途任务，以及 AI 客户端
是否自动重启其 MCP 子进程。不要结束所有 `python.exe`、删除活跃锁文件、另设锁目录，
或循环 `taskkill`。`resources release-serial` 的普通清理不会杀活跃持有者；其 `--force`
会影响整个后台的使用者，不是普通共享断开的替代品。

后台已无响应、用户明确要求结束该持有进程时，才按核对后的 PID 定向结束，保留系统
返回的“拒绝访问”等原始错误；不能将“已请求结束”说成已释放端口。进程已退出而 COM
仍不可用，或目标调试仍 busy，应分别检查驱动/USB与 IDE 状态；需要用户重插或后续
固件排查时说明依据。重启电脑作为最后手段，不应成为正常连接流程。

反馈至少保留：客户端/后台版本及协议、原始错误、所选探针/端口、后台 PID/实例 ID、
会话/采集/任务状态、退出动作及结果。不要附认证 token、endpoint 文件内容或会话密钥。
