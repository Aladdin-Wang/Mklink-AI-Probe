# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-09-05T12:30:00+08:00`
- 分支：`codex/v0.2.0-development`
- HEAD：`业务源码基线 d30b884；生产GUI资源快照 7b7902e。本轮交接结果随后独立提交。`
- 远端 HEAD：`每次维护前校正 GitHub origin/codex/v0.2.0-development。`
- 工作树：历史脱机/GUI/PY32改动已收口提交。候选包和原始证据仅在忽略的 .build；源码与生成GUI均受版本管理。
- 当前任务：0.2.0本地NSIS与Skill包构建完成；覆盖安装被Windows UAC取消，旧安装未改变，等待用户准备确认后重试。Python1845通过/12项symlink权限失败，GUI654通过，定向363通过。sidecar与Skill均验证7059目标/2224FLM。交接已精简，长期任务见security-roadmap.md。详情和校验值见docs/verification/v0.2.0-local-install-20260905.md。
- 状态：`v0.2.0-development`

## 里程碑

- **0.2.0 本地候选** — `in_progress`。标准NSIS与Skill包已完成，UAC取消导致覆盖安装未完成。保留旧安装，等待用户确认后验收。
- **芯片加锁/解锁长期任务** — `in_progress`。按保护架构和容量组累积代表板证据；当前范围、待办与完成标准见 docs/ai/security-roadmap.md。不设置无人值守硬件自动化。
- **交接整理** — `complete`。常驻交接仅保留当前基线、长期规则、未解决问题和证据入口；逐次操作日志不搬入交接，不删除原始备份。

## 验证证据

- **本轮打包**：生产构建成功；Python1845通过、12项WinError1314，GUI654通过，定向363通过。sidecar2225个资产文件逐项一致，Skill边界校验通过。安装被UAC取消，不计为安装通过。见docs/verification/v0.2.0-local-install-20260905.md。
- **当前 V4 + STM32F103**：普通暂停、3.3V：在线及脱机加锁/解锁/恢复通过，512KiB全片比对一致，APP RTT正常。F1选项FLM上下文/中断/cleanup修复，148项定向测试通过。当前未锁运行。见 docs/verification/v0.2.0-v4-security-port.md。
- **芯片安全证据**：在线/脱机开放范围不同；代表板矩阵和证据入口统一见 docs/ai/security-roadmap.md。历史成功不能关闭PY32近期异常，也不能证明加锁后无调试独立运行。
- **连接与 HEX**：STM32连接/复位矩阵与客户合并HEX在GD32验证通过；桌面勾选安全操作确认框修复。见 docs/verification/v0.2.0-hex-connect-modes-hil.md 和 v0.2.0-desktop-confirmation-offline-security.md。
- **文件重载与 SuperWatch**：STM32修改编译后重载AXF/HEX、GUI回烧及RTT通过；收藏/多关键词/刷新保留通过，三通道约1kHz且无丢样。见 docs/verification/v0.2.0-macos-file-reload-hil.md 和 v0.2.0-superwatch-pins-hil.md。
- **内置资产与实时显示**：维护仓库本地算法资产：7059目标、2224去重FLM，桌面/Skill共用且打包强制哈希校验。RTT/串口/曲线健康链路高频测试未复现稳态停顿；错误链路200ms退避仍存在。

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

- **probe**：当前V4 + STM32F103RE，3.3V，原bootloader+APP已恢复、未锁运行。新操作前重新枚举，安装验收不执行保护或VCC操作。
- **backup**：V4/F103原始512KiB双读备份与日志：.build/reports/v4-f103-security-20260905；GD32新程序备份：.build/reports/gd32-new-program-20260905。禁止随日志整理删除。
- **permission**：测试工程允许修改下载；芯片、电压或擦除范围变化须重新确认。当前硬件状态与权限不能自动外推到下一块板。

## 下一动作

1. 用户准备确认UAC后，重跑 .build/reports/install-local-20260905.ps1；停止已知源码8765服务再验证新安装的独立sidecar、界面、枚举和正常退出。不要把旧安装或源码响应当成新包结果。
2. 芯片安全长期任务按 docs/ai/security-roadmap.md 推進；优先PY32异常和加锁后独立运行，有对应板卡再扩展。
3. 补Mac/Linux、UART和RTOS Trace生命周期验证；正式发布前再跑发布全量门禁。

## 已知限制

- PY32F030K28T6近期加锁后重连/解锁异常尚未闭环；保留精确型号限制，不以历史成功代替当前复测。
- 加锁后无调试独立运行尚需额外观测；SWD/RTT可能受读保护限制，调试接入会干扰判断。其他架构及V4组合不能从F103结果外推。
- Mac/Linux无实机兼容验证；用户报告首次假烧录/后端退出缺少原始材料，未复现。UART新一轮真正收数待补。
- RTOS Trace在pyOCD在线烧录断开后时基停止，生命周期问题尚未修复；禁止盲写全局寄存器掩盖。
- RTT单次SWD失败仍可能退避200ms；高采样率需按通道数实测，不承诺16通道稳定10/20kHz。
- Windows全量12项symlink测试因WinError1314失败；带链接临时目录保留，不能强制清理。安装包无Authenticode；当前新包被UAC取消，安装/独立启动/退出验收待做。
- 1.8V/5V及800mV电源边界波形未经本轮真机测量；Modbus危险写操作未验收。

## 延续协议

- 开始前校正 Git、端口、目标固件和运行进程；硬件操作保持串行。
- 不把环境失败或未覆盖场景写成 PASS；关键证据写验证报告，交接只保留结论。
- 结束前更新 project-memory.json、渲染 CURRENT_HANDOFF.md，并保持工作树与远端同步。
