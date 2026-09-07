# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-09-07T23:41:03+08:00`
- 分支：`codex/v0.2.0-development`
- HEAD：`Git 为准；d02132f 后增加脱机全片擦除耗时提示。`
- 远端 HEAD：`master 基线 63016e3；本轮先推送开发分支，通过发布门禁后合并。`
- 工作树：仅保留当前结论；历史操作见 Git 和验证报告。
- 当前任务：用户已授权合并 master、正式发布 0.2.0（签名、标签、双端 Release、更新指针）。提示与 GUI 验证完成；完整 Python 符号链接测试待管理员权限，不得记为通过。
- 状态：`0.2.0-release-preparation`

## 里程碑

- **0.2.0 发布** — `in_progress`。尚未合并、签名或发布；按正式发布流程完成门禁及安装验收。

## 验证证据

- **本轮门禁**：docs/verification/v0.2.0-release-qualification.md：擦除提示、GUI/Rust、构建与发布状态。原始证据在 .build/reports/release-0.2.0。
- **真机基线**：docs/verification/v0.2.0-prerelease-hil-20260907.md；类型写入追加见 v0.2.0-superwatch-write-20260907.md。历史通过不能代替新正式包安装验收。

## 架构决策

- 构建/测试统一经 scripts/build_workspace.ps1，产物与原始证据留外层 .build；保留唯一备份，不上传用户固件、标识或 Pack。
- 正式包为签名标准 NSIS + 独立 sidecar；Skill 仅含运行时，首次加载检查更新，不携带维护交接、测试和构建信息。
- 默认扇区擦除；全片擦除需明确选择。文件哈希变化重载并停止依赖采集，不自动烧录。GPIO 分图由用户控制。
- 探针 I/O 串行，USB 失效释放旧句柄；HPM 保持 ROM API。安全操作遵循已验证芯片矩阵与单独电压授权，禁止 RDP2。

## 真机环境

- **current**：当前 V3 + STM32F103RE；正常 sw_write 测试程序，采集/串口已释放。此前完整 HIL 使用 V4。
- **backup**：Flash/工程备份留 .build/reports/prerelease-hil-20260907 和 superwatch-write-20260907。F103 测试获准修改/下载及 3.3V 保护往返；无 Modbus 从站。

## 下一动作

1. 解决完整 Python 测试的 Windows 符号链接权限，或取得明确豁免；随后合并 master，按 releasing.md 构建、安装验收和发布 0.2.0。
2. 发布完成后以 Release/manifest 记录版本与资产，精简更新本交接；上游 PR 另按用户后续安排。

## 已知限制

- RTT 偶发启动失败与停止后 UART 残留前缀仍未闭环；高速 USB 识别异常按用户要求暂缓。
- PY32F030 保护后恢复未闭环，见 docs/ai/security-roadmap.md。
- 未覆盖物理 Modbus、其他板卡组合、Mac/Linux、跨主机 Agent；不由 F103 外推。
- 外设轮询可能漏短脉冲，SVD 过滤依赖厂商标注，缓冲有限；SystemView 启动少量丢弃，不称绝对无损。

## 延续协议

- 开始校正 Git/设备/进程；结束渲染并验证记忆、提交推送；环境失败和未覆盖不能写 PASS。
