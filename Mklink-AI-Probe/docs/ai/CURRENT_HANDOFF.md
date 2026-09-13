# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-09-13T18:00:32+08:00`
- 分支：`codex/v0.2.1-development`
- HEAD：`最新提交以 Git 为准；应用发布标签 v0.2.0 = 911a70f。`
- 远端 HEAD：`从 microkeen/main 的 7b826c35b1bea146c9afae6f0054e7df5477f28c 创建 0.2.1 开发分支，已包含合并的 PR #1。`
- 工作树：持续开发分支补齐 mem_dump 四档 4/10/20/30 MHz，默认10，旧high=20不变。HPM5301修复版20/30稳定性、CLI/MCP/Chrome闭环完成；正式发布通道不变。
- 当前任务：四档及HPM5301稳定性完成，报告v0.2.1-mem-dump-four-speeds.md；官网任务同步。HPM6E80待用户换板后独立验证。
- 状态：`in_progress`

## 里程碑

- **已交付** — `complete`。应用 0.2.0、MicroLink V3.4.0/V4.4.0 已发布；最新源码与报障流程已同步 MicroKeen/main。

## 验证证据

- **正式版**：docs/verification/v0.2.0-release-qualification.md：Python 1913、GUI 682、Rust 19；安装/Skill/CLI/MCP 及下载校验通过。 docs/verification/v0.2.0-prerelease-hil-20260907.md、v0.2.0-superwatch-write-20260907.md；firmware-20260908.md 仅验证发布/格式/哈希，新固件未做 HIL。
- **报障流程**：docs/verification/issue-feedback-stage1.md：本地/CI 各 60 项通过；真实缺陷自动修复闭环未验证。
- **仓库权限**：GitHub API 回读四项 active 规则；release/firmware 与旧索引提交一致。仅 Aladdin-Wang 可绕过发布引用规则，main 审核/CI 无绕过者；未使用 su5176 身份执行写入测试。
- **外设三端统一**：docs/verification/v0.2.1-peripheral-unification.md：Python 190 通过/1 跳过；HPM 43 型号共 1226962 条目录项可加载；HPM5301 CLI/MCP stdio/Chrome 三通道约 1 kHz，CRC/帧丢失/固件丢样标记为零。ARM 未做实板验证。
- **选项字节/OTP 第一阶段**：docs/verification/v0.2.1-device-configuration-stage1.md：Python 103、GUI 24、正式构建通过；HPM5301 CLI/MCP/Chrome 8 个公开字段一致；Chrome ARM 配置及脚本预览通过，没有 ARM 实板读写或 OTP 编程。
- **STM32F103 选项字节第二阶段**：docs/verification/v0.2.1-stm32f103-options-stage2.md：Python 99、GUI 29、生产构建通过；CLI/MCP stdio/Chrome 10 字段一致，DATA、两项低功耗复位位及 WRP3 写入/复位/回读/恢复通过；组合下载通过，最终全部 512 KiB Flash 与原始备份一致。未测试 RDP 转换及看门狗/低功耗/WRP 拒写行为。
- **mem_dump 四档与 HPM5301 稳定性**：docs/verification/v0.2.1-mem-dump-four-speeds.md：143 Python、3 GUI、生产构建、72打包/更新/边界通过；CLI/MCP stdio及Chrome四档切换/曲线实板通过。旧7510单变量两档各30min，旧20M 4KB失败保留；新2927修复版48用例通过，20M 4KB600s/30M300s及小块、动态RAM、10轮四档重连。SBA忙冲突按报告计数恢复，不称零冲突。
- **SuperWatch 与 SystemView 文档实测修复**：docs/verification/v0.2.1-hpm-gui-acceptance.md：172+159+158 Python、95 GUI/构建；HPM脱机78464B全回读、数组index0..15/16pts通过。新9a338046探针+Web codec两轮Chrome16449/16577事件、3任务、RuntimeDrop0，已断开。原生CSV/PNG保存未验证。

## 架构决策

- 用户 Skill 只含运行时，报障指南按需读取；主仓库 MicroKeen/main，现有 Release/更新索引仍在 Aladdin-Wang 与 Gitee。
- 任务 mklink-issues-pr 为 PAUSED，未经要求不恢复；手动流程见 docs/ai/issue-maintenance.md，修复只提交 PR，合并由用户决定。
- 构建/清理遵循 AGENTS.md 与 docs/ai/build-storage.md；保留正式包、唯一备份、依赖缓存及 HIL 证据。
- 协作权限见 docs/ai/repository-governance.md：Aladdin-Wang、su5176 保持 Admin/Owner 并处理 PR；更新分支和正式标签仅 Aladdin-Wang 可写，最高管理员仍可修改规则，Release 附件权限不由分支规则隔离。
- 2026-09-10 用户指定 codex/v0.2.1-development 为本轮持续开发分支；后续修复继续该分支并推送 microkeen，整合 main 仍走审核 PR，不自动发布。

## 真机环境

- **state**：当前HPM5301探针2927de9b，四档回归48用例及CLI/MCP/Chrome通过，最终10MHz并释放连接。旧7510长测和20MHz失败证据分别保留；本地Skill开发快照安装回执在.build/reports/four-speed，正式安装器/发布通道不变。
- **backups**：.build/reports/prerelease-hil-20260907、superwatch-write-20260907；保留其他芯片唯一备份。；本轮本地证据 .build/reports/peripheral-unification。；本轮 OTP 只读和浏览器证据 .build/reports/device-configuration。；STM32F103 唯一原始备份与本轮证据 .build/reports/stm32f103-options。
- **installer**：.build/artifacts/release-0.2.0-20260908/Mklink-AI-Probe-v0.2.0-x64-Setup.exe

## 下一动作

1. 用户接入HPM6E80后单独识别能力及测试，不能套用HPM5301高速白名单。
2. 官网文档任务同步四档及旧/新固件分离证据，不发布。原生CSV/PNG保存仍无新增验证。
3. 审核PR #2的外设/配置统一和四档mem_dump，不自动合并或发布。
4. 后续按原计划补STM32F103看门狗、STOP/STANDBY和WRP拒写行为及其他ARM实板；HPM永久编程未开放。
5. 本地Skill开发快照与正式安装器/发布渠道分开；定时任务维持暂停。

## 已知限制

- 高速 USB 识别异常暂缓；RTT 偶发启动失败及停止后 UART 残留未闭环。
- PY32F030 保护后恢复未闭环；未覆盖物理 Modbus、所有板卡、Mac/Linux 与跨主机 Agent。
- 外设轮询可漏短脉冲，缓冲有限；SystemView 启动可能丢弃少量数据。
- 共享外设目录目前只支持对齐 32 位、小端、无已知读取副作用的寄存器；真实 16 位 MMIO 需要探针协议/固件补齐和 ARM 实板验证。HPM 全型号目录加载不等同全外设 HIL。
- STM32F103 非 XL USER/DATA/WRP 配置已开放，实板为 V4 高容量组；WDG_SW 保持软件模式，未验证低功耗进入和 WRP 拒写行为。V3/其他容量仅描述与生成测试；其他 ARM 维持原有安全配方，G474/PY32 仍仅 V3。HPM OTP 永久写入未开放。
- 批量路径仍限HPM5301白名单DLM/XIP、最多15区域；<50us请求沿用满速语义，非原子多变量/硬实时。XIP有界块忙冲突恢复不适用于RAM/MMIO或真实总线错误；资格仅当前板/接线，HPM6E80和ARM高速待验证。旧4.361ms事件不能追认为本次已定位的SBA错误；冻结安装版无独立接收进程。

## 延续协议

- 先核对 Git、任务和设备状态；仅按需读相关验证报告，不加载历史流水账。
