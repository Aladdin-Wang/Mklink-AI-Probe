# Remote STCP / Site Agent 实机验收结果

> 对应流程：[`remote-site-agent-hil.md`](remote-site-agent-hil.md)
>
> 验收日期：2026-08-01（Asia/Shanghai）
>
> 最终结论：`PASS — 可以合并 PR #5`

## 1. 验收对象

| 项目 | 冻结值 |
|---|---|
| 分支 | `feature/remote-stcp-site-agent` |
| 正式实测运行时 tip | `ddf7ff27deaad6156b6c5b88b977b3331e0ed0ac` |
| Site Agent ZIP 大小 | `18,487,420` bytes |
| Site Agent ZIP SHA-256 | `f59db9c3e4db2c9c9b0345062e1e2f8d9d1498b9961c52e8f55fc911864ac428` |
| manifest 大小 | `27,243` bytes |
| manifest SHA-256 | `b5d0774117f18c8c1fef35366c7d109211795e4e1662e4ceae5de543fcbf083c` |
| `mklink-remote-agent.exe` SHA-256 | `46443b453d0388d6f8a2188a95325d75e91e805f10ecaad3ed0ce3b5ccabb90e` |
| `mklink-stcp.dll` SHA-256 | `0d17b6ce89de3d15e6629f4c5a087e0bbf1d809bf4516aa52786be7175d2e9e9` |
| 签名状态 | unsigned，仅用于内部受控 HIL；未执行签名或发布 |

两次独立干净构建的 ZIP 和 manifest 字节一致。制品共 101 个成员，不包含 `frpc`。现场机启动前已独立复核 ZIP、EXE 和 DLL 哈希。

## 2. 验收环境边界

- 本机作为工程师机；受管 VPN 后的 Windows 主机作为现场机。
- 连接的是可恢复的非量产台架板，目标系列为 `STM32F40x`，批准目标型号匹配。
- 现场机仅运行独立 Site Agent；工程师端使用仓库 CLI 和进程内 STCP visitor。
- 未安装或启动 `frpc.exe`；STCP provider/visitor 均为进程内实现。
- 文档不记录现场账号、IP、COM 号、完整探针编号、token、secret、固件本地路径或原始 RTT 输出。

## 3. 实机结果

| 门禁 | 结果 | 实测结论 |
|---|---|---|
| HIL-00 制品身份与预检 | PASS | A/B 可重复构建、manifest、成员审计、无 frpc、未签名状态和现场哈希复核均通过 |
| HIL-01 回环生命周期 | PASS | ready、health、status、stop、ready 清除、子进程和监听零残留 |
| HIL-02 监听与凭据反例 | PASS | wildcard、缺少 allow、缺少/错误 Site token 和错误 STCP secret 均失败关闭，正确连接不受影响 |
| HIL-03 现场直连 | PASS | 同一最终 EXE 的 health、status、capabilities、ports 和停止清理闭环通过 |
| HIL-04 受管 VPN | PASS | 直连流量实际经受管 VPN；真实断连被检测，重连后 health 恢复 |
| HIL-05 LAN STCP | PASS | provider/visitor 回环、健康检查、visitor 中断/恢复、精确进程清理和无 frpc 通过 |
| HIL-06 探针与目标 | PASS | reconnect、probe.info、core registers 与批准芯片身份核对通过 |
| HIL-07 安全 RAM | PASS | 缺少 `--yes` 被拒绝且内存不变；批准 4 字节区域写回读后恢复原值并复核 |
| HIL-08 批准固件烧录 | PASS | 缺少确认被拒绝；烧录到批准基址后 terminal state 为 succeeded，verify/reset 通过，独立 reset/reconnect/前缀复核通过 |
| HIL-09 RTT | PASS | 已知控制块的 start/read/安全 down-channel write/stop 和资源零残留通过 |
| HIL-10 中断与恢复 | PASS | visitor、Agent 和探针软件恢复通过；恢复固件再次烧录、verify/reset 与最终目标复核通过 |
| HIL-11 清理 | PASS | 现场 Agent、visitor、HIL 监听、上传、临时目录和明文凭据零残留；既有站点与无关进程保留 |

物理拔插探针因固定无人值守夹具获批准为 `N/A`；要求的软件 reconnect 已执行并通过。受管 VPN 条件项不是 `N/A`，本次已用真实断连/重连完成验证。

## 4. 运行时修复与重新定版

HIL 首轮暴露出 BIN 烧录沿用 5 秒默认命令超时，以及远端 CLI 未按 flash 终态返回失败码的问题。修复限定在 flash timeout 和 CLI 终态传播，并增加回归测试。修复后重新完成：

- 最终 Python 套件：`1208 passed, 1 skipped`；
- GUI：422 tests、测试构建和生产构建通过；
- Rust Site Agent：5 tests、check/build 通过；Rust GUI：6 tests、check/build 通过；
- Go STCP bridge：test/build 与正式 DLL 输入审计通过；
- 最终 HEAD 的两次独立制品构建字节一致；
- 维护者直接最小审计通过，并基于绑定最终 HEAD 的正式测试记录 Phase 4 重复执行豁免；
- 修复后的完整 HIL-00 至 HIL-11 重新通过。

## 5. 固件恢复与清理

批准的测试固件和恢复固件是同一映像：大小 `348,104` bytes，SHA-256 为 `fcdcdbe6f59fc0c259c44ce4705581bd56b79d8e3aee997ba5d3100d2bb38727`，目标型号 `STM32F407VETx`，批准基址 `0x08020000`。

验收结束前已再次烧录该恢复映像，`verify=true`、`reset=true`，随后独立 reconnect、目标身份和 Flash 前缀哈希复核均通过。安全 RAM 原值也已恢复并回读确认。

现场 HIL 清理失败数为 0；现场 HIL 目录、上传文件、监听和 `frpc` 进程均为 0。本地脱敏证据仅保留结论与哈希，不保留明文凭据或硬件完整标识。

## 6. 合并判定

- 必测项：全部 `PASS`；
- 条件项：受管 VPN `PASS`，固定夹具物理拔插为批准的 `N/A`；
- 未关闭 P0/P1：0；
- 目标板：已恢复批准状态；
- 现场与工程师运行残留：0；
- 签名、tag、GitHub Release、Release 上传、Gitee 同步：均未执行，也不属于本次授权。

因此，PR #5 的实机门禁已关闭，可在确认分支包含当前 `master`、CI 通过且 PR 可合并后直接合并。
