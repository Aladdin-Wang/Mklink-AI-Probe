# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-02T12:21:30.7472963+08:00`
- 分支：`codex/superwatch-replay`
- HEAD：`35a8cd1: replay feature plus public documentation path correction.`
- 远端 HEAD：`PR #12 open at MicroKeen/Mklink-AI-Probe; #10/#11 fix closed issues #8/#7. No PR merged or released.`
- 工作树：Replay implementation, production resources, tests and usage/verification docs committed. Other worktrees preserved.
- 当前任务：User-requested issue #8/#7 fixes completed and issues closed; complete SuperWatch offline log playback implemented and verified, pending PR integration/release.
- 状态：`complete`

## 里程碑

- **正式发布** — `complete`。0.2.2 标准安装包、Skill、Site Agent 已同步新旧 GitHub 和 Gitee；四份探针固件已同步，UF2 三端索引通过。

## 验证证据

- **SuperWatch replay**：docs/verification/superwatch-replay-20261002.md: 124 GUI tests, 84 Python tests and production build passed; real Chrome desktop/standalone CSV/TXT/JSONL, seek/pause/4x/restart/error/cancel checks; 1M rows and 8M values imported and viewed. Initial feedback CI found an unshipped documentation link; moved instructions into references and all 62 local feedback/public-package checks passed.
- **Issue #8**：Closed per explicit user request; PR #10 (codex/issue-8), 140 tests plus V4.5.2/F103 fault recovery and 600k-point real-browser stress. Not merged/released.
- **Issue #7**：Closed per explicit user request; PR #11 (codex/issue-7), 27 GUI tests/build, real Chrome 940px panel and left/right path alignment. Not merged/released.
- **发布与安装**：docs/verification/v0.2.2-release-final.md：Python2306通过/2跳过，GUI720、Rust19通过；正式NSIS87.6MiB，覆盖安装、内置后端、7059型号/2224FLM哈希、退出释放、更新签名及三端公开索引通过。
- **STM32与HPM功能回归**：按目标和功能查阅 v0.2.2-v4-stm32-regression-20260920.md、v0.2.2-v4-hpm6e80-regression-20260920.md、v0.2.2-online-verify-theme-20260920.md（均位于docs/verification）。包含高速档、烧录、窄值/非对齐、共享流、CLI/MCP/GUI；HPM6E80本轮UART未接。
- **HPM5301用户OTP**：docs/verification/v0.2.2-hpm-offline-otp-20260920.md：独立Flash回读门槛、旧API/旧值/缺文件停止、用户字和组18/19永久锁、真实Chrome/UART及断电保持通过。不能外推其他型号或安全生命周期字段。
- **固件发布**：HPMLinkV4.5.1、MicroLinkV4.5.1/V3.5.0/V2.8.0已公开下载校验；25项发布/升级测试通过。V2 RBL头/体CRC、长度及程序版本验证，打包头V1.0.0保留原件。此发布轮未刷机，不新增硬件认证。 PR #6同步四份固件至源码目录，合并前Python2306/2跳过、GUI720及生产构建通过。
- **历史证据**：旧版测试保留在docs/verification，按需查阅；旧失败或曾经待测项目不再逐项重复载入当前交接。

## 架构决策

- 开发主仓库MicroKeen/main；后续修改从最新main创建codex分支，经PR及必需CI整合。审批人数0，发布和合并仍需明确授权；标签不可变。
- 应用主索引MicroKeen/release，旧GitHub/updates兼容，Gitee/updates备用。固件三个firmware索引保持兼容，客户端URL仍可指向旧GitHub。
- 现有自动固件更新仅支持UF2；V2 RBL作为手动升级附件，不写入严格UF2索引，避免破坏0.2.2解析。
- 按维护者授权，Gitee应用发布页仅保留最新0.2.2，固件渠道独立保留；GitHub历史版本不删除。
- 保留正式包、唯一备份、依赖缓存和必要HIL证据。原主工作区用户固件替换不得reset。mklink-issues-pr自动任务维持暂停。

## 真机环境

- **state**：V4.5.2 + STM32F103RET6 verified using existing test firmware; probe disconnected after issue checks. No firmware, flash, protection or voltage changes. Replay is entirely local browser processing without device operations. Older HPM OTP evidence is historical and must not be replayed.
- **backups**：本地.build/reports保留原始HIL证据；Gitee历史备份与清理记录在.build/artifacts/gitee-historical-backup-20260921。
- **installer**：.build/artifacts/v0.2.2-official/Mklink-AI-Probe-v0.2.2-x64-Setup.exe（正式签名更新包，已覆盖安装）。

## 下一动作

1. Review and integrate PR #12 plus #10/#11 only after explicit merge authorization; reconcile current main and rerun full suites/build and affected real-surface gates.
2. All three branches start from main independently. Reconcile generated gui/dist and project memory during integration; no main/0.2.3 development branch was overwritten.
3. Preserve codex/0.2.3-dev and its pending PR #9. Existing main worktree firmware modification remains untouched. No release/signing/update-pointer changes authorized.
4. Use docs/superwatch-replay.md for user instructions; no background automation or new task was created.

## 已知限制

- Issue #8 validation is finite Windows/V4.5.2 testing with host-injected faults, not a 7-hour Linux ARM64/V4.4.0 reproduction.
- Replay limits: 256 MiB, 64 channels, 8M values, 16 visible channels. No missing historical data reconstruction. Browser-tested, not a new native WebView2/NSIS qualification.
- 有限缓冲不保证无限暂停/物理断线无损；外设轮询可能漏短脉冲，多变量不是原子快照。
- 客户原始ELF/程序不可用，不能宣称复现其毛刺根因；odd-address packed halfword不保证原子性。
- HPM OTP仅按报告限定型号和字段；当前HPM5301组18/19永久锁定，禁止重放配方。其他安全GUI写入口未开放。
- PY32F030保护后恢复、物理Modbus、所有板卡、Mac/Linux与跨主机Agent未完整认证；STM32看门狗、STOP/STANDBY、WRP拒写仍待专测。
- Windows安装器无Authenticode签名（未知发布者），自动更新签名已验证；标准包不含离线WebView2。原生桌面本轮无新增视觉截图，Chrome截图不替代桌面视觉验收。
- HPM6E80回归有限时长且无UART；本次用户更新的四份固件只做格式/CRC/公开发布验证，不把历史实测外推到新二进制。

## 延续协议

- 先核对 Git、任务和设备状态；仅按需读相关验证报告，不加载历史流水账。
