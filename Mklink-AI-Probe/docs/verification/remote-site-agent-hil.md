# Remote STCP / Site Agent 实机验收

> 适用范围：GitHub PR #5 `feature/remote-stcp-site-agent`
>
> 状态：`PENDING-HIL`。自动化、Windows GUI 实表面和确定性 Site Agent
> 打包已完成；本文件是合并前唯一剩余门禁。

## 1. 合并门禁

只有同时满足以下条件，PR #5 才可直接合并：

1. 本文件标记为“必测”的项目全部 `PASS`；
2. 条件项已经执行并通过，或由维护者签字批准 `N/A`；
3. 没有未关闭的 P0/P1 缺陷；
4. 实测 PR HEAD、ZIP、manifest 与第 2 节记录一致；
5. 测试结束后目标板已恢复到批准状态，现场机和工程师机没有遗留
   Agent、visitor、上传文件或明文凭据；
6. HIL 期间没有修改运行时代码。若为修复问题产生了代码改动，旧的自动化、
   制品和 HIL 证据全部失效，必须重新执行最终门禁。

HIL 通过前不得合并。HIL 通过后，不再增加新的功能性合并条件。

## 2. 候选冻结与预检结论

### 2.1 已冻结候选

| 项目 | 冻结值 |
|---|---|
| 仓库 | `https://github.com/su5176/Mklink-AI-Probe` |
| PR | `#5`，`master <- feature/remote-stcp-site-agent` |
| 已完成正式自动化的运行时 tip | `e071982825c85b91d51ecccac8ce5531f86df876` |
| Site Agent 文件 | `mklink-remote-site-agent-windows-x86_64.zip` |
| ZIP 大小 | `18,358,681` bytes |
| ZIP SHA-256 | `b771eaf0fa308b7fecfeb2c4acae126f521eb6d62fe0e44e477a9b688fb9b709` |
| manifest 文件 | `mklink-remote-site-agent-windows-x86_64.manifest.json` |
| manifest 大小 | `27,199` bytes |
| manifest SHA-256 | `6d72fb12dbc32a7659974c4699534776790c7183c88cb2244991d2e20e3d35a7` |
| `mklink-stcp.dll` SHA-256 | `758e428fe9ed6bcbd9489d6db1990fce5a18680887137ea3ca6d348c27a77c07` |
| 产品版本 | `0.1.4` |
| 平台 | Windows x86_64，console subsystem |
| 签名状态 | `unsigned` |

ZIP 是现场端 Site Agent 便携包，不是工程师端 Tauri GUI 安装包。它包含
`mklink-remote-agent.exe`、`mklink-stcp.dll`、内置 Python 运行时和依赖，
不包含 `frpc.exe`、`frps`、Windows 服务或 GUI。

### 2.2 已完成的非实机门禁

- N5T 制品验证 9/9 通过，包含从 ZIP 解压后的
  `help/start/health/status/stop` 回环生命周期；
- Python 正式套件：`1202 passed, 1 skipped`；
- GUI：422 tests、测试构建、生产构建及 HTTP smoke 通过；
- Rust Site Agent：5/5；Rust GUI：6/6；相关 check/build 通过；
- Go STCP bridge test/build 和 canonical DLL 重现通过；
- 最终审计 23/23，需求追踪 34/34；
- A/B 两次干净构建 ZIP 和 manifest 字节一致；
- 禁止路径、凭据、临时后缀命中均为 0；
- 正式证据绑定运行时 tip `e071982...`；
- PR 创建时为 `OPEN / MERGEABLE / CLEAN`，base `master`；
- force push、tag、Release、签名、上传 Release、merge 均未执行。

本 HIL 文档和项目记忆属于文档/交接增量。开始 HIL 时必须记录实时
`PR HEAD`，并证明从 `e071982...` 到该 HEAD 仅有文档/交接变化；否则停止。

```powershell
$RuntimeTip = 'e071982825c85b91d51ecccac8ce5531f86df876'
$HilHead = (git rev-parse HEAD).Trim()
git merge-base --is-ancestor $RuntimeTip $HilHead
git diff --name-status $RuntimeTip $HilHead
gh pr view 5 --repo su5176/Mklink-AI-Probe `
  --json state,mergeable,mergeStateStatus,baseRefName,headRefName,headRefOid,url
```

预期：

- `merge-base` 返回 0；
- 差异仅允许本 HIL 文档、项目记忆和生成的 handoff；
- PR 为 `OPEN`，base 为 `master`，head OID 等于 `$HilHead`；
- 若 `master` 已推进并导致 PR 不再 CLEAN，先更新分支并重新执行最终门禁。

### 2.3 签名边界

当前候选没有 Windows Authenticode 签名，只允许在隔离 LAN 或受管 VPN
内做内部 HIL。ZIP SHA-256 是文件指纹，不是发布者签名。

代码签名、时间戳、tag、GitHub Release 和正式上传是正式 Release 门禁，
不是本 PR 的 HIL/合并门禁；它们必须由维护者控制的证书和发布流程另行授权。

## 3. 范围、角色和非范围

### 3.1 必测范围

- 干净 Windows x64 现场机解压即用；
- Site Agent 回环和非回环监听策略；
- token 正确/错误/缺失的正反例；
- 隔离 LAN 直连；
- 进程内 LAN STCP provider/visitor；
- 真实 MKLink/MicroLink 探针和目标芯片识别；
- 安全 RAM 写入、读回和原值恢复；
- 已批准测试固件的上传、烧录、verify、reset 和恢复；
- RTT start/read/stop；固件支持下再做 RTT write；
- 链路中断、探针重连、Agent 正常和 Ctrl+C 退出、现场清理。

### 3.2 条件项

- 受管 VPN 直连：正式部署使用 VPN 时必测；否则维护者可批准 `N/A`。
- RTT write：仅当批准的测试固件提供可回显/可观察的 RTT down-channel 时必测。
- 物理拔插探针：夹具允许且没有烧录、写内存或 stream 操作进行时执行；
  固定夹具可批准 `N/A`，但仍须完成软件 reconnect。

### 3.3 非范围

- 公网监听、公网 relay、NAT 穿透和 SiteTunnel；
- Tauri 工程师端 GUI 安装包；
- `frps` 的安装、加固和生产运维验收；
- Windows 服务、托盘、自启动和自动更新；
- Authenticode、tag、Release、Gitee 同步；
- 未批准的固件、芯片、Flash 地址、RAM 地址或量产设备。

项目当前没有 `_maintainer/testing/tests/e2e/hil` 实体目录。本次 HIL 以本文件
规定的、可签字的真实 CLI 闭环为唯一硬件证据，不得用虚构 pytest 名称代替。

## 4. 拓扑

### 4.1 隔离 LAN / 受管 VPN 直连

```text
工程师机 python -m mklink remote
            |
      ws://LAN_OR_VPN_IP:8766
            |
现场机 mklink-remote-agent.exe
            |
       MKLink 探针 -> 目标板
```

### 4.2 LAN STCP

```text
工程师机 in-process visitor -- 运营方 LAN frps -- 现场机 in-process provider
         127.0.0.1:18766                         Site Agent 127.0.0.1:8766
                                                        |
                                                   探针 -> 目标板
```

`frps` 由 LAN 管理员维护。工程师端和现场端均不得安装或启动 `frpc.exe`。

## 5. 前置条件和安全红线

### 5.1 人员与设备

- 现场维护者、工程师、`frps` 运维者在场或可即时联系；
- 一台干净 Windows x64 现场机，不依赖 Python/Node/Rust/Codex/source checkout；
- 工程师机从 PR 的最终 HIL HEAD 运行 remote CLI；
- 一只已批准的 MKLink/MicroLink 探针和一块可恢复的非量产目标板；
- 目标芯片型号、供电、SWD 接线和探针固件已记录；
- 一份批准的测试固件和一份已验证的恢复固件，二者均记录 SHA-256；
- 固件负责人书面给出一个不会覆盖栈、堆、外设 DMA、RTOS 对象或业务数据的
  4-byte scratch RAM 地址。

### 5.2 三类凭据必须分离

1. `MKLINK_REMOTE_TOKEN`：Site Agent 协议 token；
2. `MKLINK_STCP_AUTH_TOKEN`：LAN `frps` 认证 token；
3. `MKLINK_STCP_SECRET`：该 STCP proxy 的 secret。

三者不得相同。只通过当前进程环境变量或 owner-only 文件输入。不得写入：

- 命令行实值、URL、仓库、截图、聊天、日志；
- ready file、结果表、shell history；
- HIL 证据文件。

证据只记录“configured=true/false”，不记录 secret。

### 5.3 破坏性操作红线

- 仅在批准的非量产目标板执行；
- 写 RAM 前必须保存原值，写后必须回读并恢复原值；
- 未取得 scratch RAM 地址书面确认，不得猜测或使用文档示例地址；
- 烧录前验证恢复固件可用并记录 SHA-256；
- 未核对目标芯片、固件、base address 和目标板，不得使用 `--yes`；
- 烧录、RAM 写入、RTT stream 期间不得拔探针、断电或中断网络；
- HPM 目标只使用 HPM ROM API，不加载 FLM；
- 任何 `completion-unknown` 都不得自动重试烧录，必须先人工检查目标状态。

## 6. 证据目录和脱敏

在工程师机建立不进入 Git 的证据目录：

```powershell
$Evidence = Join-Path $PWD 'hil-evidence'
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
```

文件名使用：

```text
00-identity.json
01-loopback-ready.json
02-listener-negative.txt
03-direct-lan.json
04-vpn.json
05-stcp.json
06-probe-target.json
07-memory.json
08-flash.json
09-rtt.json
10-recovery.json
11-cleanup.json
HIL-RESULTS.md
```

不得提交原始大日志、截图、完整 probe ID、USB serial、COM 号、用户名或本地路径。
探针标识只保留型号和末 4 位，例如 `MicroKeenV4/***1A91`。正式结果表保留：
PR HEAD、MCU、固件 SHA-256、操作、耗时、结果和脱敏错误码。

## 7. HIL 步骤

以下命令中的 `<...>` 必须先替换。除明确写为“预期失败”的步骤外，任何退出码
非 0 都是 `FAIL`。

### HIL-00 候选身份和干净机启动（必测）

现场机：

```powershell
$Zip = Resolve-Path '.\mklink-remote-site-agent-windows-x86_64.zip'
$Manifest = Resolve-Path '.\mklink-remote-site-agent-windows-x86_64.manifest.json'
Get-Item $Zip, $Manifest | Select-Object Name,Length
Get-FileHash $Zip -Algorithm SHA256
Get-FileHash $Manifest -Algorithm SHA256

Expand-Archive -LiteralPath $Zip -DestinationPath '.\site-agent-hil'
Set-Location '.\site-agent-hil\mklink-remote-agent'
Get-FileHash '.\mklink-stcp.dll' -Algorithm SHA256
.\mklink-remote-agent.exe --help
.\mklink-remote-agent.exe start --help
```

PASS：

- 三个 hash 和两个大小精确匹配第 2 节；
- EXE 在没有 Python/Node/Rust 的现场机输出帮助；
- 解压目录只有官方包内容，没有 `frpc.exe`/`frps`；
- Windows Defender 没有隔离文件。若有告警，记录原始检测名并停止，不得绕过。

### HIL-01 回环生命周期（必测）

现场机终端 A：

```powershell
$env:MKLINK_REMOTE_TOKEN = Read-Host -MaskInput 'Site Agent token'
.\mklink-remote-agent.exe start `
  --host 127.0.0.1 `
  --port 8766 `
  --ready-file '.\hil-ready.json'
```

在 ready 后、stop 前复制 `hil-ready.json` 到证据目录。现场机终端 B：

```powershell
$env:MKLINK_REMOTE_TOKEN = Read-Host -MaskInput 'Same Site Agent token'
.\mklink-remote-agent.exe health --host 127.0.0.1 --port 8766
.\mklink-remote-agent.exe status --host 127.0.0.1 --port 8766
.\mklink-remote-agent.exe stop   --host 127.0.0.1 --port 8766
```

PASS：

- ready JSON 的 schema 为 `mklink.site-agent.lifecycle.v1`、event 为 `ready`；
- listener、PID、probe state 合理，`owned_children` 为 0；
- health/status 为结构化 JSON 且不泄露 token/path；
- stop 返回 0，前台进程退出，ready file 被移除，端口释放；
- 没有产品 worker/supervisor 子进程。

### HIL-02 监听和鉴权反例（必测）

以下每一条都必须是“预期失败”，退出码为 2 或 argparse 的非 0，且不得开始监听：

```powershell
# 通配监听必须拒绝
.\mklink-remote-agent.exe start --host 0.0.0.0 --port 8766 --allow-lan

# 非回环监听缺少 --allow-lan 必须拒绝
.\mklink-remote-agent.exe start --host <SITE_LAN_IP> --port 8766

# 非回环监听没有 token 必须拒绝
Remove-Item Env:MKLINK_REMOTE_TOKEN -ErrorAction SilentlyContinue
.\mklink-remote-agent.exe start --host <SITE_LAN_IP> --port 8766 --allow-lan
```

随后按 HIL-03 用正确 token 启动 LAN listener。HIL-03 listener 保持运行时，
在工程师机配置错误 token：

```powershell
$env:MKLINK_REMOTE_TOKEN_BAD = Read-Host -MaskInput 'Deliberately wrong token'
python -m mklink remote sites add field-wrong `
  'ws://<SITE_LAN_IP>:8766' `
  --token-env MKLINK_REMOTE_TOKEN_BAD
python -m mklink remote --site field-wrong health
python -m mklink remote sites remove field-wrong
Remove-Item Env:MKLINK_REMOTE_TOKEN_BAD
```

PASS：错误 token 的 health 返回 2 和脱敏失败信息，Site Agent 继续服务正确 token，
输出和证据中没有出现任何 token。

### HIL-03 隔离 LAN 直连（必测）

现场机：

```powershell
$env:MKLINK_REMOTE_TOKEN = Read-Host -MaskInput 'Site Agent token'
.\mklink-remote-agent.exe start `
  --host <SITE_LAN_IP> `
  --port 8766 `
  --allow-lan `
  --ready-file '.\hil-lan-ready.json'
```

工程师机：

```powershell
$env:MKLINK_REMOTE_TOKEN = Read-Host -MaskInput 'Same Site Agent token'
python -m mklink remote sites add field-lan `
  'ws://<SITE_LAN_IP>:8766' `
  --token-env MKLINK_REMOTE_TOKEN `
  --note 'isolated LAN HIL'
python -m mklink remote --site field-lan health
python -m mklink remote --site field-lan status
python -m mklink remote --site field-lan capabilities
python -m mklink remote --site field-lan ports
```

PASS：四条命令成功；`sites list` 只显示 `token_configured`，不显示 token；网络抓取或
防火墙检查确认只开放批准的现场 LAN 地址和端口，没有通配/公网监听。

### HIL-04 受管 VPN 直连（条件项）

停止 LAN listener，在现场机绑定实际 VPN 地址：

```powershell
.\mklink-remote-agent.exe start `
  --host <SITE_VPN_IP> `
  --port 8766 `
  --allow-lan
```

工程师机：

```powershell
python -m mklink remote sites add field-vpn `
  'ws://<SITE_VPN_IP>:8766' `
  --token-env MKLINK_REMOTE_TOKEN `
  --note 'managed VPN HIL'
python -m mklink remote --site field-vpn health
python -m mklink remote --site field-vpn status
```

PASS：仅 VPN 成员可访问，非 VPN/LAN 未授权主机不可访问；VPN 重连后 health 恢复。
若产品部署不使用 VPN，由维护者在结果表批准 `N/A`。

### HIL-05 LAN STCP（必测）

前置：LAN 管理员已启动受控 `frps`，工程师机和现场机都能访问其具体 LAN IP。

现场机：

```powershell
$env:MKLINK_REMOTE_TOKEN = Read-Host -MaskInput 'Site Agent token'
$env:MKLINK_STCP_AUTH_TOKEN = Read-Host -MaskInput 'LAN frps auth token'
$env:MKLINK_STCP_SECRET = Read-Host -MaskInput 'Site STCP secret'

.\mklink-remote-agent.exe start `
  --transport lan-stcp `
  --host 127.0.0.1 `
  --port 8766 `
  --stcp-server-addr <LAN_FRPS_IP> `
  --stcp-server-port 7000 `
  --stcp-user field-a `
  --stcp-proxy-name mklink-field-a `
  --ready-file '.\hil-stcp-ready.json'
```

工程师机终端 A：

```powershell
$env:MKLINK_STCP_AUTH_TOKEN = Read-Host -MaskInput 'Same frps auth token'
$env:MKLINK_STCP_SECRET = Read-Host -MaskInput 'Same STCP secret'
python -m mklink remote stcp visitor `
  --server-addr <LAN_FRPS_IP> `
  --server-port 7000 `
  --user field-a `
  --proxy-name mklink-field-a `
  --bind-port 18766
```

工程师机终端 B：

```powershell
$env:MKLINK_REMOTE_TOKEN = Read-Host -MaskInput 'Same Site Agent token'
python -m mklink remote sites add field-stcp `
  'ws://127.0.0.1:18766' `
  --token-env MKLINK_REMOTE_TOKEN `
  --note 'LAN STCP HIL'
python -m mklink remote --site field-stcp health
python -m mklink remote --site field-stcp status
python -m mklink remote --site field-stcp capabilities
Get-Process frpc -ErrorAction SilentlyContinue
```

PASS：

- Site Agent 仍只监听 loopback，visitor 只绑定工程师机 loopback；
- health/status/capabilities 通过 STCP 成功；
- ready 仍为 `owned_children: 0`；
- 两端没有 `frpc.exe` 进程或文件；
- 错误 STCP secret 的 visitor 无法建立可用 health，恢复正确 secret 后成功；
- 三类凭据不同且没有进入日志。

### HIL-06 探针连接和目标身份（必测）

仅保存脱敏输出：

```powershell
python -m mklink remote --site field-stcp ports
python -m mklink remote --site field-stcp reconnect
python -m mklink remote --site field-stcp call probe.info
python -m mklink remote --site field-stcp call registers.core
```

如果现场采用直连，把 `field-stcp` 替换为已验证的直连 site。

PASS：

- `ports` 只枚举到预期现场探针；
- reconnect 成功；
- `probe.info.connected` 为 true；
- `idcode` 和 `mcu_name` 与批准目标板一致；
- core registers 可读且结构合理；
- 证据已脱敏完整 probe ID、USB serial 和 COM。

目标型号不一致是 P0，立即停止所有写入和烧录。

### HIL-07 安全 RAM 写读回读与恢复（必测）

先由固件负责人填写十进制 `<APPROVED_SCRATCH_RAM>`。不得直接照抄其他芯片或
其他固件的地址。

```powershell
$Site = 'field-stcp'
$Scratch = <APPROVED_SCRATCH_RAM>
$ReadParams = @{address=$Scratch; size=4} | ConvertTo-Json -Compress
$Before = (
  python -m mklink remote --site $Site call memory.read --params $ReadParams
) | ConvertFrom-Json
$OriginalB64 = $Before.'__bytes__'

# 先证明缺少 --yes 会被客户端拒绝，且内存不变
$WriteParams = @{
  address=$Scratch
  data_b64='3q2+7w=='
} | ConvertTo-Json -Compress
python -m mklink remote --site $Site call memory.write --params $WriteParams

# 已经现场授权后再执行实际写入
python -m mklink remote --site $Site call memory.write `
  --params $WriteParams `
  --yes
$After = (
  python -m mklink remote --site $Site call memory.read --params $ReadParams
) | ConvertFrom-Json

# 无论验证结果如何，都恢复原值并再次回读
$RestoreParams = @{
  address=$Scratch
  data_b64=$OriginalB64
} | ConvertTo-Json -Compress
python -m mklink remote --site $Site call memory.write `
  --params $RestoreParams `
  --yes
$Restored = (
  python -m mklink remote --site $Site call memory.read --params $ReadParams
) | ConvertFrom-Json
```

PASS：

- 无 `--yes` 的写入被拒绝且原值不变；
- 实际写入后 `$After.'__bytes__'` 为 `3q2+7w==`；
- 恢复后 `$Restored.'__bytes__'` 与 `$OriginalB64` 完全一致；
- 目标继续运行，无 HardFault、异常 reset 或业务数据破坏。

若写入后任何一步失败，优先恢复原值；无法确认恢复时为 P0。

### HIL-08 批准固件烧录、verify、reset（必测）

```powershell
$Site = 'field-stcp'
$Firmware = Resolve-Path '<APPROVED_TEST_FIRMWARE>'
$Recovery = Resolve-Path '<APPROVED_RECOVERY_FIRMWARE>'
Get-FileHash $Firmware -Algorithm SHA256
Get-FileHash $Recovery -Algorithm SHA256

# 先证明缺少 --yes 会被 argparse 拒绝，不执行上传/烧录
python -m mklink remote --site $Site flash `
  $Firmware `
  --target-part <TARGET_PART>

# 核对现场授权表后执行；默认保留 verify 和 reset-after
python -m mklink remote --site $Site flash `
  $Firmware `
  --target-part <TARGET_PART> `
  --yes

python -m mklink remote --site $Site call probe.info
python -m mklink remote --site $Site call target.reset --params '{}' --yes
```

HPM 目标按项目批准参数增加 `--base-address`/`--board`，并确认结果使用
`hpm-rom-api`。非 HPM BIN 必须提供正确 base address；不得猜测。

PASS：

- 无 `--yes` 不产生远端文件或 flash 修改；
- 正式命令完成原子上传/finalize 后才激活；
- 结果表记录本地固件 SHA-256、remote reference 摘要、目标型号、verify=true、
  reset_after=true、耗时和成功状态；
- reset 后 `probe.info` 仍能识别正确 MCU；
- 目标板运行测试固件的批准可观察行为。

超时或传输中断后的结果为 `completion-unknown` 时，不得自动重试；先读取目标状态，
必要时执行第 7.10 节恢复。

### HIL-09 RTT 闭环（必测，write 为条件项）

测试固件必须提供已知 RTT 标记。

```powershell
$Site = 'field-stcp'
python -m mklink remote --site $Site call rtt.start --params '{}'
python -m mklink remote --site $Site call rtt.read `
  --params '{"duration":3.0}'

# 仅当固件定义了可安全写入并可观察的 down-channel
python -m mklink remote --site $Site call rtt.write `
  --params '{"data":"HIL_PING"}'
python -m mklink remote --site $Site call rtt.read `
  --params '{"duration":3.0}'

python -m mklink remote --site $Site call rtt.stop --params '{}'
```

PASS：

- start/read/stop 成功；
- read 获得测试固件规定的非空、可识别标记；
- 支持 down-channel 时，写入 `HIL_PING` 后出现规定的响应；
- stop 后资源释放，再次执行 `probe.info` 成功。

### HIL-10 中断、重连和恢复（必测）

$Site 使用本轮硬件闭环实际采用的站点；STCP 路径示例为：

```powershell
$Site = 'field-stcp'
```

1. 没有 flash/RAM write/stream 进行时退出 STCP visitor；
2. health 应失败且错误脱敏；
3. 重启 visitor，health/status 应恢复；
4. 没有破坏性操作时，允许的夹具执行探针拔插；重新插入后运行：

```powershell
python -m mklink remote --site $Site reconnect
python -m mklink remote --site $Site call probe.info
```

5. 在现场机前台对 Site Agent 按 Ctrl+C，确认退出并释放端口；
6. 重新启动同一候选，确认 ready/health；
7. 烧录恢复固件：

```powershell
python -m mklink remote --site $Site flash `
  $Recovery `
  --target-part <TARGET_PART> `
  --yes
python -m mklink remote --site $Site call probe.info
```

8. 按恢复固件定义验证启动行为。

PASS：链路和探针均可恢复；没有孤儿产品进程；恢复固件 verify/reset 成功；
目标板回到维护者批准的最终状态。

### HIL-11 清理（必测）

工程师机：

```powershell
# 只删除本轮实际注册且尚未删除的站点；“不存在”表示已经清理，不是失败
python -m mklink remote sites remove field-lan
python -m mklink remote sites remove field-vpn
python -m mklink remote sites remove field-stcp
Remove-Item Env:MKLINK_REMOTE_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:MKLINK_STCP_AUTH_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:MKLINK_STCP_SECRET -ErrorAction SilentlyContinue
```

现场机：

```powershell
.\mklink-remote-agent.exe stop --host 127.0.0.1 --port 8766
Remove-Item Env:MKLINK_REMOTE_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:MKLINK_STCP_AUTH_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:MKLINK_STCP_SECRET -ErrorAction SilentlyContinue
```

PASS：

- Agent、visitor 和测试期间产生的上传/临时目录已停止或清除；
- 8766/18766 不再监听；
- 没有 `frpc.exe`；
- 目标板为批准恢复固件，RAM scratch 已恢复；
- owner-only site registry 不再有 HIL 临时站点；
- 证据已脱敏并存放在非 Git 受控位置。

## 8. 缺陷分级和处置

| 级别 | 定义 | 处置 |
|---|---|---|
| P0 | 错板/错芯片烧录、无法恢复、凭据泄露、未授权公网监听、目标损坏 | 立即停止，PR 不得合并 |
| P1 | 必测链路失败、错误 token 可访问、verify/reset 失败、资源或进程泄漏 | PR 不得合并，修复后重跑最终门禁 |
| P2 | 条件项失败但有批准替代路径，或不影响安全/核心闭环的可诊断问题 | 维护者决定修复或记录后续 |
| P3 | 文案、显示或证据整理问题 | 不阻断，但须记录 |

任何代码修复都会改变候选身份。修复后不得只重跑失败一项：至少重新执行正式自动化、
A/B 制品构建和受影响的完整 HIL 闭环。

## 9. 结果表

| ID | 项目 | 必测/条件 | 结果 | 证据文件 | 缺陷号/备注 |
|---|---|---|---|---|---|
| HIL-00 | 候选身份/干净机 | 必测 | PENDING | `00-identity.json` | |
| HIL-01 | 回环生命周期 | 必测 | PENDING | `01-loopback-ready.json` | |
| HIL-02 | 监听/鉴权反例 | 必测 | PENDING | `02-listener-negative.txt` | |
| HIL-03 | 隔离 LAN 直连 | 必测 | PENDING | `03-direct-lan.json` | |
| HIL-04 | 受管 VPN | 条件 | PENDING | `04-vpn.json` | |
| HIL-05 | LAN STCP | 必测 | PENDING | `05-stcp.json` | |
| HIL-06 | 探针/目标身份 | 必测 | PENDING | `06-probe-target.json` | |
| HIL-07 | RAM 写读恢复 | 必测 | PENDING | `07-memory.json` | |
| HIL-08 | flash/verify/reset | 必测 | PENDING | `08-flash.json` | |
| HIL-09 | RTT | 必测/部分条件 | PENDING | `09-rtt.json` | |
| HIL-10 | 中断/重连/恢复 | 必测 | PENDING | `10-recovery.json` | |
| HIL-11 | 清理 | 必测 | PENDING | `11-cleanup.json` | |

## 10. 最终签字

| 角色 | 姓名/标识 | 日期时间（含时区） | 结论 | 签字 |
|---|---|---|---|---|
| 现场维护者 | | | PASS / FAIL | |
| 工程师 | | | PASS / FAIL | |
| `frps` 运维者 | | | PASS / N/A / FAIL | |
| 固件/目标板负责人 | | | 恢复确认 | |
| 仓库维护者 | | | MERGE / HOLD | |

最终记录：

```text
PR HEAD:
Runtime tip ancestry verified: YES / NO
ZIP SHA-256:
Manifest SHA-256:
Probe (redacted):
MCU:
Test firmware SHA-256:
Recovery firmware SHA-256:
Required tests: __ / __ PASS
Conditional tests: PASS / approved N/A / FAIL
Open P0/P1: 0 / __
Target restored: YES / NO
Secrets removed: YES / NO
Final verdict: HIL PASS / HIL FAIL
```

当最终 verdict 为 `HIL PASS`、全部必测为 PASS、无 P0/P1、目标已恢复且候选身份
匹配时，PR #5 可直接合并。
