# VPN/局域网直连远程调试

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
