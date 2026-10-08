# VPN/局域网直连远程调试


## 0.3.0 GUI 远程服务

先在配置页选择下载器及工程，再打开顶栏“远程服务”。旧“配置→启动服务”仅
打开文档页的入口已删除；新页面实际控制当前探针的WebSocket监听。

本机连接使用127.0.0.1；局域网选择本机网卡IP并勾选允许LAN。生成访问令牌，
为每台下载器指定不同端口，点击“启动/应用设置”，确认运行中后再把地址和
令牌配置到工程师客户端。地址是WebSocket入口，不能当作HTTP网页打开；
首次远程目标操作前执行connect；只有明确需要强制重连时才使用reconnect。以下注册/health/status示例可直接使用。

停止服务会等待正在执行的请求结束，再关闭远程会话；不会停止共享后台、
本地GUI或其他下载器。应用设置同样会断开现有远程连接，轮换令牌须先停止。
桌面版凭据按稳定探针身份分别用DPAPI保存，重新打开后台后显式启动服务；
旧全局服务配置不再自动应用到每个探针。Web GUI凭据仅在本次后台内存中保存，
生成时显示一次，后台退出后失效，不写入浏览器存储。更改下载器须回配置页选择。


> 触发词：远程调试、远程烧录、VPN、局域网、现场机、Site Agent、
> remote sites/status/capabilities/upload、远程 MCP
>
> 返回索引：[SKILL.md](../SKILL.md)

## 架构与角色

| 位置 | 运行内容 | 不需要 |
|------|----------|--------|
| 现场机 | 官方独立 Site Agent ZIP/EXE、探针驱动与经授权的项目输入 | Codex、工程师 Skill、源码 checkout、全局 Python/Node/Rust 工具链 |
| 工程师机 | 本 Skill、`mklink.remote` SDK、`python -m mklink remote`、可选 `mklink-remote-mcp` | 现场机源码或现场文件系统路径 |
| 传输 | 带身份验证的直连 `ws://<VPN_OR_LAN_HOST>:<PORT>` | 中间服务或公网入口 |

现场机永不读取本 Skill。本页只指导工程师侧 Agent 和现场维护者各自完成本端
操作，不能把工程师机的 Skill、源码目录或工具链复制到现场机。

Transport policy: direct LAN/VPN and the bundled in-process LAN STCP client are
supported. The STCP path uses `mklink-stcp.dll` and an operator-managed,
LAN-local `frps`; it never installs, extracts, renames, or launches `frpc.exe`.
NAT traversal, public relay/public tunnelling, bundled `frps`, and SiteTunnel deployment remain unsupported.

## 现场机：独立 Site Agent

只解压经过校验的官方 Windows x86_64 Site Agent ZIP。选择以下一种 token 来源：

```powershell
# 方式一：当前进程环境变量；不会出现在命令行参数中
$env:MKLINK_REMOTE_TOKEN = Read-Host -MaskInput "Site token"

# 方式二：已由现场维护者创建并验证为 owner-only 的 secret file
# 后续 start 命令增加：--token-file <OWNER_ONLY_TOKEN_FILE>
```

先在回环地址做无硬件 readiness/health 检查：

```powershell
.\mklink-remote-agent.exe start --host 127.0.0.1 --port 8766 --ready-file <READY_FILE>
.\mklink-remote-agent.exe health --host 127.0.0.1 --port 8766
.\mklink-remote-agent.exe status --host 127.0.0.1 --port 8766
```

`start` 是前台进程。ready event 的 schema 为
`mklink.site-agent.lifecycle.v1`，包含 listener、PID、探针状态和
`owned_children: 0`，不靠解析日志判断就绪。正式监听受管 VPN/局域网地址时：

```powershell
.\mklink-remote-agent.exe start --host <VPN_OR_LAN_HOST> --port 8766 --allow-lan
```

### 局域网 STCP（不需要 frpc.exe）

当工程师机不能直接访问现场机监听端口、但两端都能访问同一台局域网
`frps` 时，可使用进程内 STCP。`frps` 由局域网管理员单独维护；现场包和
工程师侧都不包含或启动 `frpc.exe`。现场 Site Agent 始终只监听回环地址。

三个凭据必须互不相同：Site Agent 访问令牌、`frps` 认证令牌、STCP 密钥。
凭据只从环境变量或 owner-only 文件读取，不得写入命令行、配置、ready
file 或日志：

```powershell
$env:MKLINK_REMOTE_TOKEN = Read-Host -MaskInput "Site Agent token"
$env:MKLINK_STCP_AUTH_TOKEN = Read-Host -MaskInput "LAN frps auth token"
$env:MKLINK_STCP_SECRET = Read-Host -MaskInput "Site STCP secret"
.\mklink-remote-agent.exe start --transport lan-stcp --host 127.0.0.1 --port 8766 --stcp-server-addr <LAN_FRPS_HOST> --stcp-server-port 7000 --stcp-user field-a --stcp-proxy-name <SITE_PROXY_NAME>
```

工程师机启动进程内 visitor，并把其回环端口作为普通 Site Agent 地址：

```powershell
$env:MKLINK_STCP_AUTH_TOKEN = Read-Host -MaskInput "LAN frps auth token"
$env:MKLINK_STCP_SECRET = Read-Host -MaskInput "Site STCP secret"
python -m mklink remote stcp visitor --server-addr <LAN_FRPS_HOST> --server-port 7000 --user field-a --proxy-name <SITE_PROXY_NAME> --bind-port 18766
```

visitor 就绪后，另一个终端把 `ws://127.0.0.1:18766` 注册为站点地址。
visitor 进程退出即关闭本地入口；它只绑定回环地址，不提供局域网监听。

非回环监听必须同时满足 `--allow-lan` 和 token；通配监听会被拒绝。
`--no-token` 只允许回环开发验证。token file 必须在启动前具备 owner-only 权限。
不要把 token 放入 URL、命令行值、ready file、日志或项目文件。

现场本地生命周期命令与相同 token 来源共用：

```powershell
.\mklink-remote-agent.exe health --host <VPN_OR_LAN_HOST> --port 8766
.\mklink-remote-agent.exe status --host <VPN_OR_LAN_HOST> --port 8766
.\mklink-remote-agent.exe stop --host <VPN_OR_LAN_HOST> --port 8766
.\mklink-remote-agent.exe restart --host <VPN_OR_LAN_HOST> --port 8766
```

## 工程师机：安装与站点注册

普通 SDK/CLI 只需要 remote runtime；可选 MCP 单独安装：

0.3.0 开发版的 `remote` extra 和现场便携包已包含共享后台的 HTTP 依赖
（FastAPI、Uvicorn 等），普通远程客户端导入时仍按需加载，不需要 FastMCP
或 Qt。便携入口支持后台内部使用的 `runtime serve` 启动契约；这只是部署
前提。0.3.0独立Agent核心目标、串口及Modbus已走共享后台；远程RTT/SystemView
及offline.deploy已接入共享后台；独立便携实包仍需验证，必须检查握手能力。包内包含算法加载代码，不包含 FLM、Pack 或目标固件。

```powershell
python -m pip install -e ".[remote]"
# 仅当工程师机需要 stdio MCP 时：
python -m pip install -e ".[mcp]"
```

注册站点时，CLI 从环境变量取 token，并写入 OS 用户数据目录下的 owner-only
site registry。`sites list` 只返回 `token_configured`，不会返回 token：

```powershell
$env:MKLINK_REMOTE_TOKEN = Read-Host -MaskInput "Site token"
python -m mklink remote sites add field-a "ws://<VPN_OR_LAN_HOST>:8766" --token-env MKLINK_REMOTE_TOKEN --note "managed VPN"
python -m mklink remote sites list
python -m mklink remote --project-root . sites use field-a
```

`sites use` 写入项目 `.mklink/remote.json` active pointer；Git 工作树会把该文件
加入 `.gitignore`。用户级默认站点使用：

```powershell
python -m mklink remote sites switch field-a --connect
```

解析站点的优先级是显式 `--site`、项目 active pointer、用户级 active site。
工程师操作可始终带 `--site field-a`，避免在高风险任务中误选现场。

## 先诊断，再操作

```powershell
python -m mklink remote --site field-a health
python -m mklink remote --site field-a status
python -m mklink remote --site field-a capabilities
python -m mklink remote --site field-a ports
```

- `health` 和 `status` 不要求探针已连接，先用它们区分 listener/认证问题和设备问题。
- `capabilities` 是本次握手协商出的 availability/version/operation detail；不要
  调用未发布能力，也不要猜 operation 或参数。
- `ports` 列出现场探针端口，但文档、日志和回答不得记录真实端口或硬件标识。
- `python -m mklink remote --site field-a connect` 首次连接目标，已有连接则复用，不中断其他客户端的采集。
- `python -m mklink remote --site field-a reconnect` 重连的是现场探针，不是
  VPN/局域网链路。传输连接失败时先检查网络和现场 Agent，再重试工程师命令。

CLI 输出结构化 JSON。非协议异常只输出通用失败信息；不要通过 debug print、
shell history 或聊天补打 site registry/token。

## SDK

已注册站点的推荐 SDK：

```python
import os

from mklink.remote.sites import (
    add_site,
    close_all,
    get_device,
    list_sites,
    use_site,
)

add_site(
    "field-a",
    "ws://<VPN_OR_LAN_HOST>:8766",
    os.environ["MKLINK_REMOTE_TOKEN"],
    note="managed VPN",
)
use_site("field-a", ".")

client = get_device("field-a")
try:
    handshake = client.handshake()
    status = client.call("agent.status")
    if client.supports("probe.diagnostics"):
        probe = client.call("probe.info")
finally:
    close_all()
```

不使用 registry 时可直接连接，仍只从环境变量读取 token：

```python
import os

from mklink.remote.client import connect_remote

with connect_remote(
    "ws://<VPN_OR_LAN_HOST>:8766",
    token=os.environ["MKLINK_REMOTE_TOKEN"],
    flash_timeout=300.0,
) as client:
    status = client.call("agent.status")
```

`flash_timeout` must be a positive finite number of seconds. Its default is `300.0`
and it applies only while waiting for the complete `flash.program` response;
ordinary RPC calls continue to use `timeout`. If the deadline expires or the
transport is lost after dispatch, the flash result is `completion-unknown`;
callers must inspect the target state instead of automatically retrying.

`RemoteClient.reconnect()` 重建当前 WebSocket 并重新协商协议；它不同于
`agent.reconnect` 的现场探针重连。SDK 调用高风险 operation 前，调用方必须先在
工程师本地取得明确授权并传 `confirm=True`；现场 Agent 会再次拒绝缺少确认的请求。

## CLI 与能力 operation

低风险调用示例：

```powershell
python -m mklink remote --site field-a call probe.info
python -m mklink remote --site field-a call memory.read --params '{"address":536870912,"size":16}'
```

`call` 只接受已声明 operation。当前高风险 schema 是：

- `flash.program`、`flash.erase_chip`、`flash.erase_sector`
- `offline.deploy`、`target.reset`
- `breakpoint.set`、`breakpoint.clear`、`breakpoint.clear_all`
- `memory.write`、`variable.write`
- `serial.exchange`、`modbus.write`

这些 operation 的 CLI 必须带 `--yes`，MCP 必须传 `confirm=True`，SDK 必须在
本地授权后传 `confirm=True`；现场 Agent 还会做第二次校验。例如：

```powershell
python -m mklink remote --site field-a call flash.erase_chip --params '{}' --yes
python -m mklink remote --site field-a call memory.write --params '{"address":536870912,"data_b64":"AQI="}' --yes
```

执行前必须展示站点、目标、输入摘要、verify/reset 选择和不可逆影响。`--yes`
只是已取得授权的机器可读证明，不能替代授权过程。

## 原子上传、finalize 与激活

```powershell
python -m mklink remote --site field-a upload <LOCAL_FILE>
```

`upload` 自动执行 `transfer.open` → 顺序 `transfer.chunk` →
`transfer.finalize`。finalize 校验声明 size 和 SHA-256，成功后只返回
`remote-file:<OPAQUE_ID>`；失败会尝试 `transfer.abort`。它不支持续传，不接受
客户端指定现场路径，单文件上限 256 MiB。

成功上传的 reference 是 inert 数据，不会自动连接、解析、烧录或替换任何内容。
低风险消费示例：

```powershell
python -m mklink remote --site field-a call symbols.parse --params '{"source":"remote-file:<OPAQUE_ID>"}'
```

当 reference 被烧录、脱机部署或其他高风险 operation 消费时，才是“激活”边界，
必须重新展示 reference 的 name/size/SHA-256、站点与目标并取得本地授权，然后
使用 `--yes` 或 `confirm=True`。专用远程烧录命令会完成上传/finalize 后再激活：

```powershell
python -m mklink remote --site field-a flash <LOCAL_FIRMWARE> --target-part <TARGET_PART> --yes
```

默认保留 verify 和 reset-after；只有用户明确要求并理解风险时才使用
`--no-verify` 或 `--no-reset`。

## MCP stdio

工程师机安装 `.[mcp]` 后，把以下无参数命令配置为 MCP client 的 stdio server：

```text
mklink-remote-mcp
```

该入口直接启动 stdio，不提供额外网络 listener 或 argparse flags。工具为：

- `remote_sites`
- `remote_status`
- `remote_connect`：首次目标操作前调用；已有连接会复用，不强制重连其他客户端
- `remote_capabilities`
- `remote_call`
- `remote_upload`
- `remote_flash`
- `remote_write_memory`

`remote_call` 会检查 operation schema 和能力。`remote_flash`、
`remote_write_memory` 以及 `remote_call` 的所有高风险 operation 都要求
`confirm=True`，且现场 Agent 会再次确认。

## 停止与替换现场 Agent

远程停止是高风险工程师操作：

```powershell
python -m mklink remote --site field-a stop-agent --yes
```

当前协议没有远程自更新或文件替换 operation。更换 Site Agent 必须另行取得现场
维护者授权：先确认目标站点和维护窗口，停止并验证旧前台进程已退出，由现场维护者
校验官方 ZIP 的来源与摘要、保留回滚包、替换文件，再按 readiness/health 流程启动。
不得把任意工程师上传 reference 当作 Agent 更新包自动激活。


### 0.3.0 脱机部署的设备身份限制

`offline.preview` 仍可在无探针时生成脚本。`offline.deploy` 仅允许具有不可变探针
身份绑定的后台执行，并通过 USB 身份匹配唯一卷 GUID；不会按 MICROKEEN 卷标、
盘符、环境变量或列表首项选盘。身份缺失、设备不在或磁盘映射不唯一时拒绝部署。

远程服务先通过 `agent.reconnect` 接入所选物理探针后台，再消费上传完成的
opaque reference。`firmware_files` / `algorithm_files` 必须分别按配置ID完整映射；
远程参数不能携带本机路径、profile/pack源或source_token。算法须先上传为引用。
只有服务端解析后的路径进入本机表单，复用现有部署接口的范围校验、USB身份检查
及共享互斥；活动采集或独占任务期间拒绝部署。不会在Agent进程直接写磁盘。

`offline.preview` 无需连接；部署未连接时明确拒绝。HTTP失败后不自动重放；部署
目前不属于持久任务日志，`jobs.status` 不能查询它，响应丢失须先核查磁盘内容。
当前便携独立远程服务实包及物理MSC部署仍待验收，不能以接口回归代替。

### 0.3.0 共享 Modbus

`modbus.read/write/scan` 已通过现场共享后台执行，不再由 Agent 直接打开串口。
多下载器环境要在启动 Agent 时通过 `--device-port` 选择命令接口，以接入该
下载器对应的 GUI 后台；首次 Modbus 操作会固定稳定探针 ID，COM 重用不改选。
更换这个选择需要重新启动 Agent，目标 `reconnect` 不会改变已固定的 UART 后台。
未指定探针且不能唯一选择时使用独立 UART lobby，它不代表任何物理下载器。

借用已有连接时，端口、波特率及 8N1 必须匹配；未传 timeout 保留已有时序，
显式 timeout 须匹配。新连接默认超时1秒、重试0，扫描使用既有短探测事务。
每次请求使用独立共享会话，退出不抢停 GUI 连接。写入失败可能结果未知，
Agent 不自动重放；借用连接的底层重试配置仍由共享后台控制。
串口 exchange、核心目标操作及下述 SystemView/RTT 已共享；脱机部署也复用共享后台接口。

### 0.3.0 共享 SystemView（能力版本 2）

`stream.systemview` 握手版本为 `2`。同一远程连接内先调用 `systemview.start`，
然后分页读取；不要用多次独立 CLI 进程分别执行 start/read，因为断开会释放订阅。
先加载目标匹配的 ELF/AXF，使用已知 RAM 中的 RTT 控制块地址；借用已有采集时
start 必须不传配置参数，不会重启或改动当前采集器。

```python
from mklink.remote import connect_remote

with connect_remote("ws://<VPN_OR_LAN_HOST>:<端口>", token="<令牌>") as remote:
    remote.call("agent.reconnect")
    cursor = remote.call("systemview.start")  # 已在 GUI 启动时借用同一采集
    page = remote.call("systemview.read", session=cursor["session"],
                       after=cursor["after"], limit=500)
    print(page["points"], page["dropped"], page["capture"])
    # 下一页继续使用 page["session"] 与 page["next_seq"]。
    remote.call("systemview.stop")
```

- start 可传 `addr/channel/mode/search_size` 启动新采集；返回 `session/after/reused`。
- read 返回 `points/session/next_seq/latest_seq/dropped/capture`，每页1～500条。
  不传游标时使用该远程客户端自己的位置；显式游标可重读仍在历史窗口的数据。
  `dropped` 是历史中已丢失的事件数；`capture` 提供运行、暂停、同步、进度错误
  及解码/目标丢失指标。旧 `duration` 阻塞读取参数已移除；这些指标不是无损保证。
  采集换代会拒绝旧游标，需结束原订阅后重新start，不能自动跟随另一采集。
- `systemview.resolve_task_names(task_ids=[...])` 只查询采集缓存，最多256个ID；
  返回 `source=capture_cache`、`task_names` 和 `unresolved`，不会额外读目标 RAM。
- stop 对借用者仅退订，返回 `capture_stopped=false`；拥有者只有在其他订阅者
  退出后才能停采集，否则返回409并保留订阅。连接断开时清理自己的会话，拥有者
  尝试停止自己的采集一次；若其他订阅者仍在，采集保留供本地明确停止。
  停止响应丢失不会自动重放，后续退订的 `capture_stopped=null` 表示结果未知。

### 0.3.0 共享 RTT（能力版本 2）

RTT 与 SystemView 使用同一套拥有/借用与退出规则。RTT 订阅复用共享后台的
`rtt-terminal` 二进制通道；独立缓冲和读取不会消费另一客户端的数据。后台协议
为49，旧后台需要先正常退出再启动，不能借旧独占模式绕过升级。

同一SDK连接内执行：

```python
remote.call("agent.reconnect")
remote.rtt_start()                  # 无参数借用 GUI 已运行的 RTT
page = remote.rtt_read(timeout=1)  # 最多等1秒，已有数据则立即返回
print(page["text"], page["dropped_bytes"], page["missing_batches"])
remote.rtt_write("hello\n")        # 1～256 UTF-8 字节，不自动拆分或重放
result = remote.rtt_stop()         # 借用者只退订
```

- `rtt.start` 可传 `addr/channel/channels/mode/search_size/encoding` 启动新采集；借用已有
  采集时不传配置参数。返回 `session/reused`，采集换代后旧订阅明确报错。
- `rtt.read` 只接受 `timeout`（0～5秒，默认1秒）；旧 `duration` 参数移除。
  SDK现在返回字典，文本在 `text`，不再返回裸字符串。每客户端应用缓冲最多
  64 KiB/128批，满时保留较新的批次；超出64 KiB的单批丢弃并计数。
  WebSocket 库接收缓冲另受其队列和协议最大帧限制，这不是整个进程内存上限。
- `dropped_bytes` 是该客户端应用缓冲累计丢失字节，`missing_batches` 是其已
  观察到的数据序号缺口。`upstream` 是后台通道所有订阅者的累计指标，不能
  当成当前客户端的丢失量。`capture` 提供运行/暂停/错误/编码；`error` 表示
  二进制订阅断开或帧无效，需显式停止/重新订阅，不自动重连。
- 超时而无数据返回空 `text`，不表示目标断开。UTF-8/ANSI按后台终端解码结果
  原样转发，不从按行历史拼接；目标程序在多字节字符中间插入其他输出时，
  不能靠客户端还原原文。慢读、断线与目标缓冲溢出都不保证无损。
- `rtt.write` 通用RPC返回 `sent_bytes`，SDK布尔值按确认字节数判断。
  `rtt.stop` 返回 `subscribed/capture_stopped`；SDK同样返回字典。
  `wait_for_rtt` 遇到本客户端丢失/订阅错误会抛异常，收集上限为1 MiB。


### 结果未知时查询任务

协商能力 `runtime.jobs` 提供只读 `jobs.status`。恰好传一个 `job_id` 或
`request_id`；Python 使用 `remote.job_status(request_id="此前提交的ID")`。
该查询读取所选探针后台现有记录，不创建目标会话、不连接CDC、不提交新任务。
远程服务必须仍绑定原后台；换探针后不能用另一后台的查询结果判断原任务。

返回后台保留的状态及结果，`unknown` 仍需检查目标。后台最多保留64条，记录
不存在（request_id为not_found，job_id为404）不能证明操作未执行，禁止据此自动
重放烧录/擦除/复位。任务请求ID应在首次提交前保存，远程重连后可继续查询。

### 远程 RTT 多通道原始数据

`rtt.start(channels=[0,1,...,7])` 可启动目标实际支持的多通道采集；`channel`
须包含在列表中，省略时为0。已有采集继续用无参数 `rtt_start()` 借用。
`rtt.read_channel` 复用共享后台的每通道64KiB历史，每页最多16KiB，
不会为各通道新增接收线程或第二份历史。客户端为每通道分别保存返回的 `cursor`，
检查 `lost_bytes`、`session` 和 `reset`；返回 `data_hex` 保留原始二进制，
文本按通道使用增量解码器，不能把每页单独解码后假定字符完整。

```python
page = remote.rtt_read_channel(channel=7, cursor=0)
payload = bytes.fromhex(page['data_hex'])
next_page = remote.rtt_read_channel(channel=7, cursor=page['cursor'])
remote.rtt_write(b'\x00\xff\x80', channel=7)
```

RPC `rtt.write` 接受 `data`（UTF-8文本）或 `data_hex`，必须二选一，
每次仍限1～256字节；可指定0～7的 `channel`，省略沿用默认发送通道。
旧 `rtt.read(timeout=...)` 继续返回默认终端文本。新服务的能力目录明确列出
`rtt.read_channel`；旧服务不支持时应报错，不自动回退或重放写入。
### CLI 在同一连接中采集 RTT

```powershell
python -m mklink remote --site field-a rtt --start --channels 0,1 --duration 5
python -m mklink remote --site field-a rtt --channels 0,1 --duration 5
```

第一条显式新建采集，正在采集时会拒绝重新配置；第二条借用现有采集。
未指定 `--start` 且当前没有采集时，沿用后台默认行为启动通道0；其他通道需要
先显式启动。`--addr` 仅与 `--start` 一起使用，必须是目标实际RTT控制块地址。
通道列表为互不重复的0～7，duration必须为有限正数，默认10秒。

输出为逐行JSON：首行event=subscribed，数据行event=data，包含channel、
session、cursor、data_hex、lost_bytes。原始字节不会按字符拆解，也不在CLI内
无限累计；有丢失必须根据lost_bytes识别。时间结束、Ctrl+C或失败都退出本客户端，
借用者不停止其他客户端采集；拥有者存在其他订阅者时，采集仍受共享归属规则保护。
Ctrl+C退出码130，其他失败非零，未知写入/请求不自动重放。duration限制正常读取
循环，网络请求仍有自身超时，不是故障时的硬退出期限。

独立 `remote call rtt.start` 与后续 `remote call rtt.read_channel` 不共享连接，
不能替代上述持续命令。需要发送二进制或交互读写时使用持久SDK/MCP会话。
