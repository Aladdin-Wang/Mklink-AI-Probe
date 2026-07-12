# 在线烧录资格验证记录

本文分开记录自动化、真机 HIL 和尚未具备条件的项目。单元测试不能替代真机结果；“Pack 可用”也不代表“已经 MKLink 验证”。探针标识统一脱敏为 `MicroKeenV4/***1A91`。

## 自动化证据（2026-07-12）

| 范围 | 命令 | 真实结果 |
|---|---|---|
| Task 12 Python 定向 | `python -m pytest _maintainer/testing/tests/test_online_flash_dependencies.py _maintainer/testing/tests/test_online_flash_errors.py _maintainer/testing/tests/test_pack_catalog.py _maintainer/testing/tests/test_pack_manager.py _maintainer/testing/tests/test_online_flash_probes.py _maintainer/testing/tests/test_online_flash_images.py _maintainer/testing/tests/test_online_flash_backend.py _maintainer/testing/tests/test_online_flash_jobs.py _maintainer/testing/tests/test_online_flash_api.py -q` | PASS，361 passed in 8.59s |
| Python 全量 | `python -m pytest -q` | PASS，端口发现修复后 388 passed in 10.20s |
| 端口发现并发回归 | `python -m pytest _maintainer/testing/tests/test_remote_api.py -q` | PASS，2 passed；阻塞扫描期间 `/api/health` 保持响应，连续复跑 11 次稳定 |
| GUI 定向 | `npm test -- src/views/OnlineFlashView.test.ts src/lib/hexPreview.test.ts` | PASS，2 files / 50 tests |
| GUI 全量 | `npm test` | PASS，6 files / 69 tests；仅有既存 `<table>/<tr>` Vue 警告 |
| GUI 生产构建 | `npm run build` | PASS，134 modules transformed |
| Pack 仓库策略 | `git ls-files '*.pack'` | PASS，无跟踪的 `.pack` |
| Pack 发布策略 | `Get-ChildItem -Recurse -Filter '*.pack' gui\src-tauri\target\release` | PASS，无打包的 `.pack` |
| Tauri 前置检查 | `python skills/tauri-gui-builder/scripts/build.py --check` | PASS；使用 `%TEMP%` 中的官方 rustup 临时工具链，`rustc 1.97.0`，未修改系统 PATH |
| Tauri release EXE | `python skills/tauri-gui-builder/scripts/build.py` | PASS，`mklink-ai-probe.exe` 11,132,928 bytes |
| Tauri MSI bundle | `python skills/tauri-gui-builder/scripts/build.py --bundle` | PASS，`Mklink AI Probe_0.1.0_x64_en-US.msi` 47,554,560 bytes |
| Tauri NSIS bundle | 同一 bundle 命令 | BLOCKED：MSI 完成后下载官方 `nsis-3.11.zip` 时 `timeout: global`；不宣称 NSIS 成功 |

Rust 使用 `%TEMP%` 中的官方 rustup 临时工具链，MSVC Build Tools 与 Windows SDK 来自本机现有安装。EXE 和 MSI 已生成并记录尺寸；它们是本地验证产物，不纳入 Git。NSIS 只因其工具包下载超时而未生成。

## 真机矩阵（2026-07-12）

| Date | MKLink | MCU | Pack ID/version | Image format/SHA-256 | Operation | Result | Duration | Notes |
|---|---|---|---|---|---|---|---|---|
| 2026-07-12 | `MicroKeenV4/***1A91` | STM32F103RC | pyOCD builtin | N/A | MKLink-only CMSIS-DAP 过滤 | PASS | 1.6s | API 仅返回 `MicroKeenV4 CMSIS-DAP`；现场没有第二只非 MKLink 探针，无法做双探针对照 |
| 2026-07-12 | `MicroKeenV4/***1A91` | Pack catalog | index | N/A | 首次更新完整 CMSIS-Pack 索引 | PASS | 221.906s | 处理 1,793 个描述文件；更新结果 11,951 个 Pack target；状态聚合后 12,142 个目标 |
| 2026-07-12 | `MicroKeenV4/***1A91` | GD32F303RC | GigaDevice.GD32F30x_DFP/2.2.1 | N/A | 未安装目标按需下载 DFP | PASS | 257.173s | 安装后 exact search 返回 `installed:true`；Pack 仅进入用户缓存 |
| 2026-07-12 | `MicroKeenV4/***1A91` | GD32F303RC | GigaDevice.GD32F30x_DFP/2.2.1 | N/A | 服务重启后复用本地索引与 Pack | PASS | 0.3s | 重启后仍返回 `installed:true`、索引可用；未切断系统网络，因此不宣称完成物理断网测试 |
| 2026-07-12 | `MicroKeenV4/***1A91` | STM32F103RC | pyOCD builtin | HEX/`3ebc8d31748a5d96eb5fce1e0d877577f2d8c09b30018f03d350de63c60e3d4e` | connect/program/verify/reset/disconnect，SWD 10MHz | PASS | backend 1.487s；端到端 2.520s | 作业 `succeeded`，17 个 SSE 事件按序闭环；映射 `0x08000000..0x08004B60` |
| 2026-07-12 | `MicroKeenV4/***1A91` | STM32F103RC | pyOCD builtin | BIN/`7fd0d782355cdbf3c728a74a916915d85286e6e9b5e1ada441bc2cfd03bef306` | 显式 `0x08000000` program/verify/reset | PASS | backend 1.441s；端到端 2.351s | 19,296 bytes，作业 `succeeded` |
| 2026-07-12 | `MicroKeenV4/***1A91` | STM32F103RC | pyOCD builtin | BIN/`ab5e078d350ff0b5e7d7a85de67f7842d01bafce19c67588d012ba6924811f4b` | 只 verify 错误固件 | PASS（预期失败） | backend 1.165s；端到端 2.061s | 返回 `VERIFY_FAIL`，首个 mismatch 为 `0x08000000`；清理/断开正常 |
| 2026-07-12 | `MicroKeenV4/***1A91` | STM32F103RC | pyOCD builtin | BIN/`ab5e078d350ff0b5e7d7a85de67f7842d01bafce19c67588d012ba6924811f4b` | program 中 stop | PASS | backend 6.468s；端到端 7.321s | 观察到 `programming -> stopping -> stopped`；等待安全 disconnect，没有强杀 USB |
| 2026-07-12 | `MicroKeenV4/***1A91` | STM32F103RC | pyOCD builtin | BIN/`7fd0d782355cdbf3c728a74a916915d85286e6e9b5e1ada441bc2cfd03bef306` | stop 测试后恢复 boot.bin 并 verify/reset | PASS | backend 2.241s；端到端 3.149s | 目标板恢复到已验证 boot 固件 |
| 2026-07-12 | `MicroKeenV4/***1A91` | STM32F103RC | pyOCD builtin | BIN/boot | VOFA 持有 `target_debug` 时启动在线 verify | PASS（受控冲突） | <0.1s | 在线作业返回 `PROBE_BUSY`，owner=`user:dashboard:vofa` |
| 2026-07-12 | `MicroKeenV4/***1A91` | STM32F103RC | pyOCD builtin | BIN/boot | 停止 VOFA 后在线 verify 交接 | PASS | backend 1.221s | 不重启服务即可 `succeeded`，租约已释放 |
| 2026-07-12 | `MicroKeenV4/***1A91` | STM32F103RC | pyOCD builtin | N/A | 当前源码 GUI headless 可视检查 | PASS | 5s virtual time | 四区布局、真实探针、索引状态、动作门禁与日志区可见；截图保存在本机临时证据目录，未提交大文件 |

## 尚未执行或发现的限制

- **物理故障注入未执行**：目标掉电、探针拔出、SWD 线断开需要人工操作硬件，不能用软件结果冒充。
- **非 MKLink 对照探针不可用**：现场只枚举到一只 MKLink CMSIS-DAP；过滤逻辑有自动化测试，双探针对照仍待补。
- **物理断网未执行**：已验证服务重启后使用本地缓存，但没有修改机器网络状态。
- **NSIS 未生成**：EXE 与 MSI 已成功；NSIS 工具包从 Tauri 官方 GitHub release 下载时触发全局超时，未把部分下载当作成功。
- **端口自动发现阻塞已修复**：真机验证发现 `GET /api/ports/discover` 的同步扫描会阻塞事件循环；提交 `e525428` 将扫描移到默认 executor，并发回归证明扫描期间 health 仍可响应。

## 可重复命令要点

```powershell
$Base = 'http://127.0.0.1:8765/api/online-flash'

# HEX/BIN 使用 multipart inspect；BIN 必须提供显式基址。
curl.exe -sS -X POST "$Base/images/inspect" `
  -F 'file=@<FIRMWARE.hex>' -F 'part_number=stm32f103rc'
curl.exe -sS -X POST "$Base/images/inspect" `
  -F 'file=@<FIRMWARE.bin>' -F 'part_number=stm32f103rc' `
  -F 'base_address=0x08000000'

# 作业 actions 必须以 connect 开始、disconnect 结束。
# stop 是协作式取消；发送后继续轮询，直到 stopped/failed/succeeded。
Invoke-RestMethod -Method Post -Uri "$Base/jobs/<JOB_ID>/stop" -Body '{}'
curl.exe -N "$Base/jobs/<JOB_ID>/events?after=0"
```

## 证据脱敏规则

- 探针标识仅保留型号和末 4 位，其余替换为 `***`。
- 不提交完整 `probe_id`、USB serial、COM 端口、用户目录截图或原始大日志。
- 保留 MCU、Pack ID/版本、固件格式、完整 SHA-256、操作、耗时和错误码。
