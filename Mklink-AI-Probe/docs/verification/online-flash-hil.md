# 在线烧录资格验证记录

本文档把可重复的非硬件证据与必须在 MKLink/目标板上执行的 HIL 证据分开。不得用单元测试结果替代真机结果；“Pack 可用”也不代表“已经 MKLink 验证”。

## 自动化证据（2026-07-12）

| 范围 | 命令 | 真实结果 |
|---|---|---|
| Task 12 Python 定向 | `python -m pytest _maintainer/testing/tests/test_online_flash_dependencies.py _maintainer/testing/tests/test_online_flash_errors.py _maintainer/testing/tests/test_pack_catalog.py _maintainer/testing/tests/test_pack_manager.py _maintainer/testing/tests/test_online_flash_probes.py _maintainer/testing/tests/test_online_flash_images.py _maintainer/testing/tests/test_online_flash_backend.py _maintainer/testing/tests/test_online_flash_jobs.py _maintainer/testing/tests/test_online_flash_api.py -q` | PASS：361 passed in 8.59s（命令墙钟 9.45s） |
| Python 全量 | `python -m pytest -q` | PASS：386 passed in 9.48s（命令墙钟 10.16s） |
| GUI 定向 | `npm test -- src/views/OnlineFlashView.test.ts src/lib/hexPreview.test.ts` | PASS：2 files / 50 tests，Vitest 3.37s（命令墙钟 4.16s） |
| GUI 全量 | `npm test` | PASS：6 files / 69 tests，Vitest 3.40s（命令墙钟 4.12s）；有既有 Vue `<table>/<tr>` 结构警告 |
| GUI 生产构建 | `npm run build` | PASS：134 modules transformed，Vite 340ms（命令墙钟 3.28s） |
| Pack 仓库策略 | `git ls-files '*.pack'` | PASS：无输出，Git 未跟踪 `.pack` |
| Pack 发布策略 | `Get-ChildItem -Recurse -Filter '*.pack' gui\src-tauri\target\release` | PASS：无输出，release 资源无 `.pack` |
| Tauri 前置检查 | `python skills/tauri-gui-builder/scripts/build.py --check` | BLOCKED：exit 1，0.33s；系统找不到 `rustc` |
| Tauri release exe | `python skills/tauri-gui-builder/scripts/build.py` | BLOCKED：exit 1，0.29s；同样在 Rust 前置检查处停止，未生成产物 |

测试机未安装 Rust，且本次验证禁止下载/安装系统工具，因此未执行 bundle。此项是构建环境阻塞，不记为 Tauri 构建成功。

## 真机矩阵（待执行）

| Date | MKLink | MCU | Pack ID/version | Image format/SHA-256 | Operation | Result | Duration | Notes |
|---|---|---|---|---|---|---|---|---|
| TBD | `<MKLINK_MODEL>/<SERIAL_REDACTED>` | TBD | TBD | N/A | MKLink-only 探针过滤（同时连接非 MKLink CMSIS-DAP） | PENDING | TBD | 需真机 |
| TBD | `<MKLINK_MODEL>/<SERIAL_REDACTED>` | TBD | TBD | N/A | 搜索未安装 MCU，更新索引并下载 DFP | PENDING | TBD | 需联网真机 |
| TBD | `<MKLINK_MODEL>/<SERIAL_REDACTED>` | TBD | TBD | N/A | 断网后复用缓存索引和 DFP | PENDING | TBD | 需真机 |
| TBD | `<MKLINK_MODEL>/<SERIAL_REDACTED>` | TBD | TBD | `HEX/<SHA256>` | connect/erase/program/verify/reset/disconnect | PENDING | TBD | 需真机 |
| TBD | `<MKLINK_MODEL>/<SERIAL_REDACTED>` | TBD | TBD | `BIN/<SHA256>` | 显式 base 后 program/verify | PENDING | TBD | 需真机 |
| TBD | `<MKLINK_MODEL>/<SERIAL_REDACTED>` | TBD | TBD | `<FORMAT>/<SHA256>` | 目标断连、探针拔出、目标掉电、program 中 stop、verify mismatch | PENDING | TBD | 每个故障需独立记录 |
| TBD | `<MKLINK_MODEL>/<SERIAL_REDACTED>` | TBD | TBD | `<FORMAT>/<SHA256>` | RTT 占用时尝试在线烧录，验证冲突和受控交接 | PENDING | TBD | 需真机 |

## HIL 命令模板

### 1. 项目与服务

```powershell
$ProjectRoot = '<PROJECT_ROOT>'
python -m mklink project-init --project-root $ProjectRoot
python -m mklink serve --host 127.0.0.1 --port 8765 --project-root $ProjectRoot
# 浏览器打开 http://127.0.0.1:8765/#/online-flash
```

如需代理，必须在启动 `serve` 之前设置：

```powershell
$env:HTTPS_PROXY = 'http://proxy.example:8080'
$env:HTTP_PROXY = $env:HTTPS_PROXY
$env:NO_PROXY = '127.0.0.1,localhost'
```

### 2. HEX 检查与任务

```powershell
$Base = 'http://127.0.0.1:8765/api/online-flash'
$ProbeId = '<PROBE_ID>'
$Part = '<EXACT_PART_NUMBER>'
$Hex = '<FIRMWARE.hex>'

$image = curl.exe -sS -X POST "$Base/images/inspect" -F "file=@$Hex" -F "part_number=$Part" | ConvertFrom-Json
$jobBody = @{ probe_id=$ProbeId; target_part=$Part; image_id=$image.image_id; actions=@('connect','erase','program','verify','reset','disconnect') } | ConvertTo-Json
$job = Invoke-RestMethod -Method Post -Uri "$Base/jobs" -ContentType 'application/json' -Body $jobBody
Invoke-RestMethod "$Base/jobs/$($job.job_id)"
```

### 3. BIN 检查与任务（必须显式基地址）

```powershell
$Bin = '<FIRMWARE.bin>'
$BinBase = 0x08000000 # 按目标 Flash 映射修改；保持 JSON 中为整数
$image = curl.exe -sS -X POST "$Base/images/inspect" -F "file=@$Bin" -F "part_number=$Part" -F "base_address=$BinBase" | ConvertFrom-Json
$jobBody = @{ probe_id=$ProbeId; target_part=$Part; image_id=$image.image_id; base_address=$BinBase; actions=@('connect','erase','program','verify','reset','disconnect') } | ConvertTo-Json
$job = Invoke-RestMethod -Method Post -Uri "$Base/jobs" -ContentType 'application/json' -Body $jobBody
```

### 4. Stop 和事件

```powershell
Invoke-RestMethod -Method Post -Uri "$Base/jobs/$($job.job_id)/stop"
curl.exe -N "$Base/jobs/$($job.job_id)/events?after=0"
```

`stop` 是协作式取消；发送后必须等待任务进入 `stopped` 且 disconnect/资源释放完成。

## 证据脱敏规则

- 探针序列号只保留型号和末 4 位，其余替换为 `***`；例：`MKLink/***1A2B`。
- 日志中的 `probe_id`、USB serial、COM 口友好名及截图必须使用同一规则；不得伪造一个新序列号替代。
- 保留 MCU、Pack ID/版本、固件格式、完整 SHA-256、操作、耗时和错误码；项目路径如包含用户名则用 `<PROJECT_ROOT>` 替换。
