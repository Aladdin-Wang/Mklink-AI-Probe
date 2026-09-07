# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-09-07T18:42:25.161883+08:00`
- 分支：`codex/v0.2.0-development`
- HEAD：`52ff114 后新增 6a92b5e 串口合批修复、fa8807b 桌面关闭退出修复及发布前 HIL 记录；源码运行时身份 fa8807b4ac40，最终文档/构建资产提交 tip 以 Git 为准。`
- 远端 HEAD：`本轮用户已明确授权推送 master；最终记录提交后将开发分支与 master 同步，远端实际 tip 以 Git 核验为准。`
- 工作树：本轮修改、生产 GUI 和验证记录统一提交，核对 origin 开发分支及 master；不改正式发布指针。
- 当前任务：发布前 V4 + STM32F103RE 实测完成，边界见 docs/verification/v0.2.0-prerelease-hil-20260907.md。修复测试固件 UART/任务饥饿、主机串口队列溢出及桌面关闭残留。Python1902、GUI682、Rust19通过；实际 NSIS 覆盖安装、独立后端、在线/脱机烧录、UART、高吞吐切页、YMODEM、CLI/MCP、安全操作通过。用户追加的原生 computer-use 16变量+GPIO混采通过，共324112组、导出20万行；已停止断开，桌面保留波形。
- 状态：`v0.2.0-development`

## 里程碑

- **0.2.0 本地候选** — `complete`。标准NSIS和Skill包已构建；用户手动覆盖安装，独立sidecar、桌面界面、配置保留及正常退出验收通过。未正式发布。
- **芯片加锁/解锁长期任务** — `in_progress`。按保护架构和容量组累积代表板证据；当前范围、待办与完成标准见 docs/ai/security-roadmap.md。不设置无人值守硬件自动化。
- **交接整理** — `complete`。常驻交接仅保留当前基线、长期规则、未解决问题和证据入口；逐次操作日志不搬入交接，不删除原始备份。

## 验证证据

- **发布前全功能 HIL 与实际安装**：见 docs/verification/v0.2.0-prerelease-hil-20260907.md。Python1902/GUI682/Rust19，实际安装+原生操作/独立后端退出、Web/桌面连续流与USB文件复用、MCP27、CLI、SystemView、VOFA、HardFault、YMODEM113576B零重试、3.3V加锁解锁恢复通过。原生17通道324112组约996Hz，20万行CSV验证全部变量变化与GPIO 0/1，读取/CRC/帧/传输丢失为0，启动丢弃60字节。硬件覆盖仅V4/F103RE，保留RTT启动/停止残留问题与未覆盖矩阵。 Windows测试链接运行目录保留，不强制清理；完整Python以管理员符号链接权限通过。
- **GUI文件与脱机下载**：原文件重载/数组收起、导航KeepAlive及搜索遗漏修复见docs/verification/v0.2.0-file-reload-20260907.md、v0.2.0-flash-navigation-20260907.md、v0.2.0-symbol-search-20260907.md。手动FLM可用性见v0.2.0-manual-flm-20260907.md（该轮仅预览）。最新工具栏/U盘复用见docs/verification/v0.2.0-toolbar-usb-deploy-20260907.md：GUI682/Python63、Web10种布局/原路径自动重载通过；实际Web和Tauri各一次APP+BOOT烧录成功，原USB三文件内容/时间不变，UART递增输出、命令口及UART释放。旧桌面触发错误复现为Web占用命令口；保留互斥并显示具体原因。
- **PR #5代理接入**：Python全量1896通过、零失败零跳过（UAC提供符号链接权限）；GUI62文件667通过；生产构建及Nginx1.30.4+Edge根路径/子路径/index.html/308入口、实际端口、WS握手、释放200、中英文外设版本说明通过。未做真机采集。见docs/verification/v0.2.0-pr5-proxy-integration.md。
- **Windows DAP消失恢复**：现场PnP正常、GUID缺失、上位机枚举为空；备份补GUID并重启MI_00后枚举恢复1个，DAP Info 2.1.1/512B/2包/能力307通过。实读USB为High Speed，BOS33B/OS2集合170B，GUID内容正确。未卸载驱动/拔插/刷固件。定点工具12项条件验证及幂等自检通过；Keil界面和高速链路不稳定复现未验收。见docs/verification/v0.2.0-winusb-guid-recovery.md。
- **仪表盘持续采集与SVD外设**：Python定向289通过、GUI全量657通过；F103真实Edge切子页/配置页无隐式停流、无缓冲重置、无JS错误，UART10047条连续文本、SW约1kHz/19468点、GPIOB.12与IDR bit12一致。transport/backend丢批为零；SW启动解析器丢弃74字节，不称全程绝对无损。Pack型号联想/SVD选择、原程序变量与手动分图保留。见docs/verification/v0.2.0-dashboard-peripheral-hil.md。
- **SystemView上游同步**：上游移植ada1ca0的软件/模拟状态证据见docs/verification/v0.2.0-systemview-upstream-sync.md。后续F103真机另修复pyOCD断开清TRCENA；普通烧录后长流及连续启停通过，Python510通过，7任务/72MHz/零自动重试。每会话解析器丢弃11字节，不称无损。见docs/verification/v0.2.0-systemview-f103-hil.md。
- **芯片安全证据**：在线/脱机开放范围不同；代表板矩阵和证据入口统一见 docs/ai/security-roadmap.md。历史成功不能关闭PY32近期异常，也不能证明加锁后无调试独立运行。 早期F103修复见 docs/verification/v0.2.0-v4-security-port.md，最新安全往返见发布前HIL报告。
- **连接与 HEX**：STM32连接/复位矩阵与客户合并HEX在GD32验证通过；桌面勾选安全操作确认框修复。见 docs/verification/v0.2.0-hex-connect-modes-hil.md 和 v0.2.0-desktop-confirmation-offline-security.md。

## 架构决策

- 在 codex/v0.2.0-development 持续维护，问题独立提交推送 origin；正式发布、签名、master 合并、标签和更新索引需另行授权。
- 所有构建/测试经 scripts/build_workspace.ps1，临时目录、缓存、候选包和原始证据在外层 .build；不上传用户固件/设备标识，不删除唯一备份。
- 桌面标准NSIS携带独立sidecar，不依赖系统Python；local-bundle无更新签名，不作正式更新包。Skill仅含运行时，不包含维护交接、测试和构建指令。
- 算法打包只依赖本地维护资产；型号匹配选最具体且RAM/算法/几何一致的候选，不凭前缀猜测。非规范Pack仅规范化临时索引副本。
- 固件/AXF以内容哈希重载，变化时停止依赖采集，不自动烧录；浏览器上传是快照，后端路径可持续跟踪。
- 单探针I/O串行；超时或USB失效先释放旧句柄。普通烧录按扇区擦除，不自动全片擦除或复位回退；HPM保持ROM API独立路径。
- 新版V3/V4以开漏RST为前提，固件保持通用；芯片差异在上位机FLM/CFG维护。安全操作电压每次确认，默认断电3秒、脱机残压门限800mV。
- 加锁/解锁按保护架构和容量组验证后开放；CLI/MCP/在线共用后端，脱机另外核对执行器支持。禁止RDP2，异常身份/选项/算法一律拒绝。连接策略以当前代码和实测为准，不能沿用旧的统一under-reset说法。

## 真机环境

- **probe**：V4 + STM32F103RE；在线及脱机3.3V安全往返通过，最后为修复后正常测试程序、未保护。原生SuperWatch17通道测试已停止断开；最终UART401行连续，命令口与UART均释放，桌面保留曲线。
- **backup**：512KiB双读一致原始Flash、修改前源码与AXF/HEX/BIN及原始证据保留在.build/reports/prerelease-hil-20260907。安全测试恢复原备份全片一致；之后重新下载正常修复程序，独立全片回读确认应用与新HEX一致、BIN与HEX一致。不声称当前仍是原始映像。
- **permission**：用户明确允许修改编译下载测试工程，允许本块STM32F103RE加锁、解锁擦除并恢复，供电3.3V；已确认没有Modbus从站。

## 下一动作

1. 继续在 codex/v0.2.0-development 维护；本轮同源 fa8807b NSIS 已实际安装，Skill/Web/CLI/MCP一致且不含开发上下文。当前受测V4/F103RE路径完成；后续优先RTT启动/停流串口残留，物理Modbus与其他平台/芯片仍需对应设施。
2. 芯片安全长期任务按 docs/ai/security-roadmap.md 推進；优先PY32异常和加锁后独立运行，有对应板卡再扩展。
3. USB问题按用户要求暂缓，现场及恢复工具记录见docs/verification/v0.2.0-winusb-guid-recovery.md。根因仍待高速USB不稳定枚举阶段证据，FS兼容问题独立；不改写或烧录下载器固件。
4. 按用户要求，0.2.0开发完成后再向su5176/Mklink-AI-Probe提交PR；本轮不创建PR或发布。

## 已知限制

- PY32F030K28T6近期加锁后重连/解锁异常尚未闭环；保留精确型号限制，不以历史成功代替当前复测。
- 加锁后无调试独立运行尚需额外观测；SWD/RTT可能受读保护限制，调试接入会干扰判断。其他架构及V4组合不能从F103结果外推。
- Mac/Linux无实机兼容验证；用户报告首次假烧录/后端退出缺少原始材料，未复现。UART接线由用户修正后，本轮连续文本与切页验证通过。
- F103普通在线烧录后时基停止已修复并真机验证；探针断电冷启动复位/停流、其他芯片和保护操作不由此证明。保持单次有界恢复；不能盲写全局寄存器或扩大重试掩盖。
- USB GUID缺失已定点恢复，实测High Speed及512B正确；高速枚举中断/登记缺失的触发因果未证实。固件独立的FS包大小和other-speed类型问题不能当作本次根因。RTT失败退避和高采样率仍按原边界。
- 1.8V/5V及800mV电源边界波形未经本轮真机测量；Modbus危险写操作未验收。
- 外设为采样观察，可能漏掉短脉冲；仅过滤SVD明确标注的读取副作用，不证明厂商目录全部外设安全或适配所有封装。本轮GPIO实测，缓冲有容量上限。
- RTT偶发首次启动控制块未找到，原始应答发现描述与负载交错；停止后首条UART help曾混入RTTView.stop(前缀。均有明确残留证据，未修改探针固件，不能以重试成功关闭。SystemView首会话启动溢出1且不增长，第二会话0，不称绝对无损。

## 延续协议

- 开始前校正 Git、端口、目标固件和运行进程；硬件操作保持串行。
- 不把环境失败或未覆盖场景写成 PASS；关键证据写验证报告，交接只保留结论。
- 结束前更新 project-memory.json、渲染 CURRENT_HANDOFF.md，并保持工作树与远端同步。
