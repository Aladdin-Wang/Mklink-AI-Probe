# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-09-07T11:11:51+08:00`
- 分支：`codex/v0.2.0-development`
- HEAD：`运行代码基线6787302baa93；本次提交仅保存同源重建的gui/dist和本地安装验收记录。`
- 远端 HEAD：`origin/master保持6787302baa93；本次构建资产及验收交接仅推送codex/v0.2.0-development，未再次合并master。`
- 工作树：构建资产与验收记录完成后提交并核对origin开发分支tip；本地Skill和桌面界面同为6787302baa93。
- 当前任务：按用户指令重建NSIS、覆盖本地安装并同步用户Skill。2448文件一致，Skill排除维护交接/测试/打包流程，保留用户配置；新版Web GUI已从安装Skill运行并打开，未连接设备或串口。
- 状态：`v0.2.0-development`

## 里程碑

- **0.2.0 本地候选** — `complete`。标准NSIS和Skill包已构建；用户手动覆盖安装，独立sidecar、桌面界面、配置保留及正常退出验收通过。未正式发布。
- **芯片加锁/解锁长期任务** — `in_progress`。按保护架构和容量组累积代表板证据；当前范围、待办与完成标准见 docs/ai/security-roadmap.md。不设置无人值守硬件自动化。
- **交接整理** — `complete`。常驻交接仅保留当前基线、长期规则、未解决问题和证据入口；逐次操作日志不搬入交接，不删除原始备份。

## 验证证据

- **PR #5代理接入**：Python全量1896通过、零失败零跳过（UAC提供符号链接权限）；GUI62文件667通过；生产构建及Nginx1.30.4+Edge根路径/子路径/index.html/308入口、实际端口、WS握手、释放200、中英文外设版本说明通过。未做真机采集。见docs/verification/v0.2.0-pr5-proxy-integration.md。
- **Windows DAP消失恢复**：现场PnP正常、GUID缺失、上位机枚举为空；备份补GUID并重启MI_00后枚举恢复1个，DAP Info 2.1.1/512B/2包/能力307通过。实读USB为High Speed，BOS33B/OS2集合170B，GUID内容正确。未卸载驱动/拔插/刷固件。定点工具12项条件验证及幂等自检通过；Keil界面和高速链路不稳定复现未验收。见docs/verification/v0.2.0-winusb-guid-recovery.md。
- **仪表盘持续采集与SVD外设**：Python定向289通过、GUI全量657通过；F103真实Edge切子页/配置页无隐式停流、无缓冲重置、无JS错误，UART10047条连续文本、SW约1kHz/19468点、GPIOB.12与IDR bit12一致。transport/backend丢批为零；SW启动解析器丢弃74字节，不称全程绝对无损。Pack型号联想/SVD选择、原程序变量与手动分图保留。见docs/verification/v0.2.0-dashboard-peripheral-hil.md。
- **SystemView上游同步**：上游移植ada1ca0的软件/模拟状态证据见docs/verification/v0.2.0-systemview-upstream-sync.md。后续F103真机另修复pyOCD断开清TRCENA；普通烧录后长流及连续启停通过，Python510通过，7任务/72MHz/零自动重试。每会话解析器丢弃11字节，不称无损。见docs/verification/v0.2.0-systemview-f103-hil.md。
- **本地打包与安装**：2026-09-07纯Windows PATH覆盖安装及启动通过；独立sidecar、探针枚举1个、SVD界面与版本说明、正常关闭释放8765均通过。sidecar/Skill均验证7059目标2224FLM；2448个Skill文件逐项匹配，GUI一致、用户配置保留。旧扩展导航脚本超时未计通过，详见docs/verification/v0.2.0-local-install-20260907.md。
- **当前 V4 + STM32F103**：普通暂停、3.3V：在线及脱机加锁/解锁/恢复通过，512KiB全片比对一致，APP RTT正常。F1选项FLM上下文/中断/cleanup修复，148项定向测试通过。当前未锁运行。见 docs/verification/v0.2.0-v4-security-port.md。
- **芯片安全证据**：在线/脱机开放范围不同；代表板矩阵和证据入口统一见 docs/ai/security-roadmap.md。历史成功不能关闭PY32近期异常，也不能证明加锁后无调试独立运行。
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

- **probe**：V4 + STM32F103RE、512KiB、72MHz，现有目标固件build=2026090501未改变。GUID已补回，DAP信息查询测试句柄已关闭；用户原有8765命令串口会话保留，本轮未打开UART或刷下载器。
- **backup**：本轮完整512KiB备份与原源码/AXF/HEX：.build/reports/systemview-hil-20260905/before；此前V4/F103双读备份：.build/reports/v4-f103-security-20260905；GD32备份：.build/reports/gd32-new-program-20260905。禁止删除唯一备份。
- **permission**：测试工程允许修改下载；芯片、电压或擦除范围变化须重新确认。当前硬件状态与权限不能自动外推到下一块板。

## 下一动作

1. origin/master与0.2.0开发分支已按用户授权同步。后续维护仍从记录的开发分支继续；正式发布前另行重建安装包并验收，当前GUI来源标识ca09b5639093。
2. 芯片安全长期任务按 docs/ai/security-roadmap.md 推進；优先PY32异常和加锁后独立运行，有对应板卡再扩展。
3. USB问题按用户要求暂缓，现场及恢复工具记录见docs/verification/v0.2.0-winusb-guid-recovery.md。根因仍待高速USB不稳定枚举阶段证据，FS兼容问题独立；不改写或烧录下载器固件。
4. 按用户要求，0.2.0开发完成后再向su5176/Mklink-AI-Probe提交PR；本轮不创建PR或发布。

## 已知限制

- PY32F030K28T6近期加锁后重连/解锁异常尚未闭环；保留精确型号限制，不以历史成功代替当前复测。
- 加锁后无调试独立运行尚需额外观测；SWD/RTT可能受读保护限制，调试接入会干扰判断。其他架构及V4组合不能从F103结果外推。
- Mac/Linux无实机兼容验证；用户报告首次假烧录/后端退出缺少原始材料，未复现。UART接线由用户修正后，本轮连续文本与切页验证通过。
- F103普通在线烧录后时基停止已修复并真机验证；探针断电冷启动复位/停流、其他芯片和保护操作不由此证明。保持单次有界恢复；不能盲写全局寄存器或扩大重试掩盖。
- USB GUID缺失已定点恢复，实测High Speed及512B正确；高速枚举中断/登记缺失的触发因果未证实。固件独立的FS包大小和other-speed类型问题不能当作本次根因。RTT失败退避和高采样率仍按原边界。
- 此前Windows全量12项symlink权限失败，本次UAC管理员完整1896项已全部通过；含测试链接的运行目录保留，不强制清理。安装包仍无Authenticode；安装阶段及纯系统PATH验收边界见原记录。
- 1.8V/5V及800mV电源边界波形未经本轮真机测量；Modbus危险写操作未验收。
- 外设为采样观察，可能漏掉短脉冲；仅过滤SVD明确标注的读取副作用，不证明厂商目录全部外设安全或适配所有封装。本轮GPIO实测，缓冲有容量上限。

## 延续协议

- 开始前校正 Git、端口、目标固件和运行进程；硬件操作保持串行。
- 不把环境失败或未覆盖场景写成 PASS；关键证据写验证报告，交接只保留结论。
- 结束前更新 project-memory.json、渲染 CURRENT_HANDOFF.md，并保持工作树与远端同步。
