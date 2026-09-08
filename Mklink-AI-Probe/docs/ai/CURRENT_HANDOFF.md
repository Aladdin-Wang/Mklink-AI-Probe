# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-09-08T09:26:58+08:00`
- 分支：`master`
- HEAD：`应用 v0.2.0 发布提交 911a70f；master 后续包含验收记录及独立固件目录更新。`
- 远端 HEAD：`GitHub/Gitee 应用 0.2.0 与独立固件索引已同步；最新 master 以 Git 为准。`
- 工作树：仅保留当前结论；历史操作见 Git 和验证报告。
- 当前任务：应用 0.2.0 与 MicroLink V3.4.0/V4.4.0 固件发布完成；后者仅做格式、发布与下载验证，未做新固件 HIL。
- 状态：`published`

## 里程碑

- **0.2.0 正式版** — `complete`。GitHub/Gitee Release、更新签名与 latest.json 已发布；本地桌面和 Skill 已同步。

## 验证证据

- **本轮门禁**：docs/verification/v0.2.0-release-qualification.md：Python 1913、GUI 682、Rust 19；正式包安装、算法/文件哈希、CLI/MCP 和双端发布通过。
- **真机基线**：docs/verification/v0.2.0-prerelease-hil-20260907.md；类型写入追加见 v0.2.0-superwatch-write-20260907.md。历史通过不能代替新正式包安装验收。
- **固件发布**：docs/verification/firmware-20260908.md：V3.4.0/V4.4.0；25 项测试、UF2/版本检查、双端下载哈希和公开索引一致性通过。

## 架构决策

- 构建/测试统一经 scripts/build_workspace.ps1，产物与原始证据留外层 .build；保留唯一备份，不上传用户固件、标识或 Pack。
- 正式包为签名标准 NSIS + 独立 sidecar；Skill 仅含运行时，首次加载检查更新，不携带维护交接、测试和构建信息。
- 默认扇区擦除；全片擦除需明确选择。文件哈希变化重载并停止依赖采集，不自动烧录。GPIO 分图由用户控制。
- 探针 I/O 串行，USB 失效释放旧句柄；HPM 保持 ROM API。安全操作遵循已验证芯片矩阵与单独电压授权，禁止 RDP2。

## 真机环境

- **current**：最近受测 V3 + STM32F103RE；正常 sw_write 测试程序，采集/串口已释放。此前完整 HIL 使用 V4。本次发布验收只发现探针，未写目标芯片。
- **backup**：Flash/工程备份留 .build/reports/prerelease-hil-20260907 和 superwatch-write-20260907。F103 测试获准修改/下载及 3.3V 保护往返；无 Modbus 从站。

## 下一动作

1. 后续版本开发和上游 PR 按用户下一步安排；应用和本轮固件发布均已完成，新固件真机功能尚未验收。
2. 保留已登记的 RTT、USB 和芯片安全限制，不能由本次发布推断已修复。

## 已知限制

- RTT 偶发启动失败与停止后 UART 残留前缀仍未闭环；高速 USB 识别异常按用户要求暂缓。
- PY32F030 保护后恢复未闭环，见 docs/ai/security-roadmap.md。
- 未覆盖物理 Modbus、其他板卡组合、Mac/Linux、跨主机 Agent；不由 F103 外推。
- 外设轮询可能漏短脉冲，SVD 过滤依赖厂商标注，缓冲有限；SystemView 启动少量丢弃，不称绝对无损。

## 延续协议

- 开始校正 Git/设备/进程；结束渲染并验证记忆、提交推送；环境失败和未覆盖不能写 PASS。
