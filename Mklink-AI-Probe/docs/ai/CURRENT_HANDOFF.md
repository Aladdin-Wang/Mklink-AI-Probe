# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-09-15T00:14:55.9117651+08:00`
- 分支：`codex/v0.2.1-development`
- HEAD：`最新提交以 Git 为准；应用发布标签 v0.2.0 = 911a70f。`
- 远端 HEAD：`从 microkeen/main 的 7b826c35b1bea146c9afae6f0054e7df5477f28c 创建 0.2.1 开发分支，已包含合并的 PR #1。`
- 工作树：发布准备沿用 codex/v0.2.1-development；PR #2 待审核整合 main，再生成正式签名版本。
- 当前任务：0.2.1候选回归和覆盖安装完成：Python2187通过/2可选依赖跳过，GUI698，Rust19，真实Skill/MCP68工具和ping通过；修复空egg-info导致版本为None。2026-09-15用户追加授权自动审核合并PR #2并正式发布。待最后提交推送后尝试受保护PR合并；尚未签名、发布标签/Release/索引。
- 状态：`in_progress`

## 里程碑

- **已交付** — `complete`。应用 0.2.0、MicroLink V3.4.0/V4.4.0 已发布；最新源码与报障流程已同步 MicroKeen/main。

## 验证证据

- **正式版**：docs/verification/v0.2.0-release-qualification.md：Python 1913、GUI 682、Rust 19；安装/Skill/CLI/MCP 及下载校验通过。 docs/verification/v0.2.0-prerelease-hil-20260907.md、v0.2.0-superwatch-write-20260907.md；firmware-20260908.md 仅验证发布/格式/哈希，新固件未做 HIL。 docs/verification/v0.2.1-release-candidate.md：完整回归、0.2.1实际覆盖安装、68工具MCP、7059型号/2224算法审计通过。新旧GitHub/Gitee迁移准备完成；正式发布未执行。
- **报障流程**：docs/verification/issue-feedback-stage1.md：本地/CI 各 60 项通过；真实缺陷自动修复闭环未验证。
- **仓库权限**：GitHub API 回读四项 active 规则；release/firmware 与旧索引提交一致。仅 Aladdin-Wang 可绕过发布引用规则，main 审核/CI 无绕过者；未使用 su5176 身份执行写入测试。
- **外设三端统一**：docs/verification/v0.2.1-peripheral-unification.md：Python 190 通过/1 跳过；HPM 43 型号共 1226962 条目录项可加载；HPM5301 CLI/MCP stdio/Chrome 三通道约 1 kHz，CRC/帧丢失/固件丢样标记为零。ARM 未做实板验证。
- **选项字节/OTP 第一阶段**：docs/verification/v0.2.1-device-configuration-stage1.md：Python 103、GUI 24、正式构建通过；HPM5301 CLI/MCP/Chrome 8 个公开字段一致；Chrome ARM 配置及脚本预览通过，没有 ARM 实板读写或 OTP 编程。
- **STM32F103 选项字节与 ARM mem_dump**：docs/verification/v0.2.1-stm32f103-options-stage2.md：Python 99、GUI 29、生产构建通过；CLI/MCP stdio/Chrome 10 字段一致，DATA、两项低功耗复位位及 WRP3 写入/复位/回读/恢复通过；组合下载通过，最终全部 512 KiB Flash 与原始备份一致。未测试 RDP 转换及看门狗/低功耗/WRP 拒写行为。 docs/verification/v0.2.1-stm32f103-mem-dump.md：27软件测试、14项稳定矩阵、LA3.904/10.549MHz测量、CLI/MCP/Chrome低中档通过；20/30电气试验失败保留。单RAM60s约603万点101.293kSa/s，4KB630.34KiB/s；GUI功能素材和RTT双消费者修复分别记录A/B演示构建，未做多小时认证。 docs/verification/v0.2.1-stm32-clock-calibration.md：117相关Python测试通过；Keil/在线/脱机频率实测、RTT/SystemView短时复测通过，20/30M不合格。GUI同一API改频与LA通过，RTT修复后14项mem_dump通过；最终Chrome截图尚未完成。 本轮更新（旧失败仅属旧板/旧固件）：docs/verification/v0.2.1-stm32-four-profile-freeze.md。pipe-r20四档20项完整矩阵通过，持续59.598/111.956/157.770/187.636kSa/s；20M60秒/30M120秒。Keil1/2/5/10M，Chrome配置四档和SuperWatch四档，在线/脱机各四档LA通过。USB暂停/启停20、CDC12、RTT/SV32次启动及功能/CLI/MCP通过。入口Python405、间隔66、GUI144/29（重叠）/95、生产构建与2460文件本地Skill安装审计通过。Chrome真图已交文档任务，发布渠道不变。
- **mem_dump 四档与 HPM 实板稳定性**：docs/verification/v0.2.1-mem-dump-four-speeds.md：143 Python、3 GUI、生产构建、72打包/更新/边界通过；CLI/MCP stdio及Chrome四档切换/曲线实板通过。旧7510单变量两档各30min，旧20M 4KB失败保留；新2927修复版48用例通过，20M 4KB600s/30M300s及小块、动态RAM、10轮四档重连。SBA忙冲突按报告计数恢复，不称零冲突。 HPM6E80独立记录v0.2.1-hpm6e80-mem-dump.md：21软件测试、304候选28矩阵/30长测重连、cbd最终28回归、CLI/MCP24和Chrome通过；共享ID不识别精确型号。
- **SuperWatch 与 SystemView 文档实测修复**：docs/verification/v0.2.1-hpm-gui-acceptance.md：172+159+158 Python、95 GUI/构建；HPM脱机78464B全回读、数组index0..15/16pts通过。新9a338046探针+Web codec两轮Chrome16449/16577事件、3任务、RuntimeDrop0，已断开。原生CSV/PNG保存未验证。 Web修复：docs/verification/v0.2.1-hex-preview.md，159 Python、121 GUI、生产构建；Chrome 无芯片 FLM+25.5MiB HEX、IAP越界提示与预览、默认折叠通过。

## 架构决策

- 用户 Skill 只含运行时，报障指南按需读取；主仓库 MicroKeen/main，现有 Release/更新索引仍在 Aladdin-Wang 与 Gitee。
- 任务 mklink-issues-pr 为 PAUSED，未经要求不恢复；手动流程见 docs/ai/issue-maintenance.md，修复只提交 PR，合并由用户决定。
- 构建/清理遵循 AGENTS.md 与 docs/ai/build-storage.md；保留正式包、唯一备份、依赖缓存及 HIL 证据。
- 协作权限见 docs/ai/repository-governance.md：Aladdin-Wang、su5176 保持 Admin/Owner 并处理 PR；更新分支和正式标签仅 Aladdin-Wang 可写，最高管理员仍可修改规则，Release 附件权限不由分支规则隔离。
- 2026-09-10 用户指定 codex/v0.2.1-development 为本轮持续开发分支；后续修复继续该分支并推送 microkeen，整合 main 仍走审核 PR，不自动发布。

## 真机环境

- **state**：STM32F103RET6 / 72MHz / RT-Thread 5.1.0；MKLINK V4 HPM5301 360MHz，pipe-r20固化候选已升级并通过报告所列ARM验证；恢复10M并断开。Chrome新安装版GUI保留8771页面。HPM板切换待用户。
- **backups**：.build/reports/prerelease-hil-20260907、superwatch-write-20260907；保留其他芯片唯一备份。；本轮本地证据 .build/reports/peripheral-unification。；本轮 OTP 只读和浏览器证据 .build/reports/device-configuration。；STM32F103 唯一原始备份与本轮证据 .build/reports/stm32f103-options。
- **installer**：.build/artifacts/release-0.2.1-candidate/Mklink-AI-Probe-v0.2.1-x64-Setup.exe

## 下一动作

1. 按2026-09-15追加授权审核并尝试合并PR #2，保持另一维护者审批和CI规则；合并后的确定main上签名重建、完整资产校验并同步两个GitHub和Gitee，最后更新三端索引。
2. 换接HPM5301/HPM6E80回归pipe-r20批时间戳、USB和四档，不继承旧版硬件资格。ARM固化包已通过77源文件哈希对照。
3. 官网文档任务已收到四档Chrome真图和技术附件；保留公众号风格及技术附件分层，不自动发布。继续优化前先拆分批间组帧/调度开销；慢浏览器订阅需按队列背压评估，勿与USB字节故障混同。
4. 后续按原计划补STM32F103看门狗、STOP/STANDBY和WRP拒写行为及其他ARM实板；HPM永久编程未开放。
5. 本地Skill开发快照与正式安装器/发布渠道分开；定时任务维持暂停。

## 已知限制

- 本轮已复现的USB停读后32B缺失由独立对齐DMA槽修复，并修复RTT回执/描述符并发。有限缓存仍不保证无限暂停或物理断线无损；历史枚举异常未做全部场景认证。
- PY32F030 保护后恢复未闭环；未覆盖物理 Modbus、所有板卡、Mac/Linux 与跨主机 Agent。
- 外设轮询可漏短脉冲，缓冲有限；SystemView 启动可能丢弃少量数据。
- 共享外设目录目前只支持对齐 32 位、小端、无已知读取副作用的寄存器；真实 16 位 MMIO 需要探针协议/固件补齐和 ARM 实板验证。HPM 全型号目录加载不等同全外设 HIL。
- STM32F103 非 XL USER/DATA/WRP 配置已开放，实板为 V4 高容量组；WDG_SW 保持软件模式，未验证低功耗进入和 WRP 拒写行为。V3/其他容量仅描述与生成测试；其他 ARM 维持原有安全配方，G474/PY32 仍仅 V3。HPM OTP 永久写入未开放。
- 批量路径覆盖已列明HPM5301 DLM/XIP和新增HPM6E80 AXI SRAM、最多15区域；shared JTAG ID不识别精确型号，也不证明接线稳定。<50us请求沿用满速语义，非原子多变量/硬实时。XIP有界块忙冲突恢复不适用于RAM/MMIO或真实总线错误。历史HPM资格按对应固件保留；pipe-r20 HPM批时间戳/USB改动仍待HPM实板回归。ARM高速本轮按专门报告验证。

## 延续协议

- 先核对 Git、任务和设备状态；仅按需读相关验证报告，不加载历史流水账。
