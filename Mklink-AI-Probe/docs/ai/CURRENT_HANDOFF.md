# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-09-07T22:44:34.515074+08:00`
- 分支：`codex/v0.2.0-development`
- HEAD：`63016e3 为已同步 master 的 HIL 基线；后续包含 Skill 加载检查与 SuperWatch 类型写入修复，最新 tip 以 Git 为准。`
- 远端 HEAD：`origin/master 已同步 63016e3；后续维护提交推送 origin/codex/v0.2.0-development。`
- 工作树：仅保留当前状态与证据入口，不在交接累积逐次操作记录。
- 当前任务：STM32F103 真机 CLI + Chrome 常用类型写入完成；修复超范围输入提示、停流残留响应及 CLI typedef/数组解码，结果集中在验证报告。
- 状态：`v0.2.0-development`

## 里程碑

- **0.2.0 本地候选** — `complete`。覆盖安装、独立后端、Web/桌面与 V4/F103RE HIL 通过；受测范围及限制见验证报告。
- **芯片安全扩展** — `in_progress`。按 docs/ai/security-roadmap.md 累积代表板证据；其他芯片不能由 F103 结果外推。

## 验证证据

- **当前发布前基线**：docs/verification/v0.2.0-prerelease-hil-20260907.md：Python1902、GUI682、Rust19；实际安装与原生17通道、烧录/流/CLI/MCP/安全恢复记录集中在此。
- **GUI与代理**：文件重载、数组、导航、搜索、U盘复用及PR #5分别见 docs/verification/v0.2.0-file-reload-20260907.md、v0.2.0-flash-navigation-20260907.md、v0.2.0-symbol-search-20260907.md、v0.2.0-toolbar-usb-deploy-20260907.md、v0.2.0-pr5-proxy-integration.md。
- **硬件限制与后续入口**：安全矩阵见 docs/ai/security-roadmap.md；高速USB现场记录见 docs/verification/v0.2.0-winusb-guid-recovery.md；RTT启动/停流残留见发布前HIL报告。
- **Skill加载检查**：MCP ping(force_update_check=True) 与脚本 check --force 跳过近期缓存；普通健康检查仍复用缓存。103项更新/上下文/协议测试通过，本机用户Skill已同步；实际MCP与脚本均联网返回cached:false，用户Skill校验通过且不含维护上下文。
- **SuperWatch类型写入**：docs/verification/v0.2.0-superwatch-write-20260907.md：Chrome 18项常用值、6项非法值、20次采集中写入及CLI 10组交叉验证通过；Python 1901通过，12项因当前Windows无符号链接权限失败。

## 架构决策

- 在 codex/v0.2.0-development 持续维护并推送 origin；master 合并、正式发布、签名、标签及更新索引按用户明确授权执行。
- 所有构建/测试经 scripts/build_workspace.ps1，临时目录、缓存、候选包和原始证据在外层 .build；不上传用户固件/设备标识，不删除唯一备份。
- 桌面标准NSIS携带独立sidecar，不依赖系统Python；local-bundle无更新签名，不作正式更新包。Skill仅含运行时，不包含维护交接、测试和构建指令。
- 算法打包只依赖本地维护资产；型号匹配选最具体且RAM/算法/几何一致的候选，不凭前缀猜测。非规范Pack仅规范化临时索引副本。
- 固件/AXF以内容哈希重载，变化时停止依赖采集，不自动烧录；浏览器上传是快照，后端路径可持续跟踪。
- 单探针I/O串行；超时或USB失效先释放旧句柄。普通烧录按扇区擦除，不自动全片擦除或复位回退；HPM保持ROM API独立路径。
- 新版V3/V4以开漏RST为前提，固件保持通用；芯片差异在上位机FLM/CFG维护。安全操作电压每次确认，默认断电3秒、脱机残压门限800mV。
- 加锁/解锁按保护架构和容量组验证后开放；CLI/MCP/在线共用后端，脱机另外核对执行器支持。禁止RDP2，异常身份/选项/算法一律拒绝。连接策略以当前代码和实测为准，不能沿用旧的统一under-reset说法。

## 真机环境

- **probe**：V4 + STM32F103RE，测试程序新增稳定 sw_write 结构体，写入值已恢复初值；采集停止，命令口与UART释放。
- **backup**：原始512KiB Flash、源码/AXF/HEX/BIN前态与原始HIL证据保留在 .build/reports/prerelease-hil-20260907。安全往返已校验原备份；最终下载修复程序并独立回读校验。 本轮稳定写入夹具与工程前态保留在 .build/reports/superwatch-write-20260907。
- **permission**：本轮F103RE测试获准修改/下载及3.3V加锁解锁擦除恢复；没有Modbus从站。

## 下一动作

1. 继续在开发分支维护；优先闭环RTT启动和停止后的串口残留。按需查历史报告，不预载逐次验证记录。
2. 芯片安全按 docs/ai/security-roadmap.md 推进；高速USB问题保持登记，待用户恢复安排。
3. 0.2.0开发完成后再向su5176/Mklink-AI-Probe提交PR；正式发布、标签和更新指针需对应授权。

## 已知限制

- RTT偶发首次启动控制块未找到；停止后首条UART命令曾混入RTTView.stop(前缀。未修改探针固件，重试成功不代表问题关闭。
- 高速USB不稳定导致设备识别异常按用户要求暂缓。GUID定点恢复成功，触发因果仍未证实；FS兼容问题不能当作本次根因。
- PY32F030K28T6近期保护后重连/解锁异常未闭环；加锁后无调试独立运行仍需专门验证。
- 未覆盖物理Modbus、其他芯片/探针组合、Mac/Linux及跨主机Site Agent；1.8V/5V及残压边界未经本轮测量。
- 外设轮询可能漏短脉冲，SVD副作用过滤以厂商标注为限，缓冲容量有限；SystemView启动有少量丢弃，不称绝对无损。

## 延续协议

- 开始前校正 Git、端口、目标固件和运行进程；硬件操作保持串行。
- 不把环境失败或未覆盖场景写成 PASS；关键证据写验证报告，交接只保留结论。
- 结束前更新 project-memory.json、渲染 CURRENT_HANDOFF.md，并保持工作树与远端同步。
