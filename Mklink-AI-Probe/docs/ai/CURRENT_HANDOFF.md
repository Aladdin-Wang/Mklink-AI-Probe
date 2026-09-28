# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-09-28T17:11:15+08:00`
- 分支：`codex/0.2.3-dev`
- HEAD：`VCC 测量功能提交 342ac86；本次交接记忆随后单独提交`
- 远端 HEAD：`342ac86 已推送并核对 microkeen/codex/0.2.3-dev；现有草稿 PR #9 继续开放，交接记忆随后推送`
- 工作树：0.2.3 RAM 表头冲突修复及 V3/H743 验收文档待本轮提交；固件工作区保留用户修改。未发布。
- 当前任务：V3 电压接口 raw/CLI/MCP 真机通过；H563 客户验收通过。H743 AP/Memory/SuperWatch 三场景、非对齐写入/零值/恢复最终一轮通过，4140 样本无读错误丢弃；文本 RAM 表头碰撞已修复，98 项回归通过。历史 USB 掉线和 Windows 433 未解决，用户要求继续排查连续芯片识别失败后的恢复问题。源码发现 DAP 整命令关中断、USB RESET 队列未复位等风险，尚未做 USB 修复。V4 遥测实测和安装包集成仍待完成。
- 状态：`active`

## 里程碑

- **正式发布** — `complete`。0.2.2 标准安装包、Skill、Site Agent 已同步新旧 GitHub 和 Gitee；四份探针固件已同步，UF2 三端索引通过。

## 验证证据

- **0.2.2 发布、安装与固件**：docs/verification/v0.2.2-release-final.md：Python2306通过/2跳过，GUI720、Rust19通过；正式NSIS87.6MiB，覆盖安装、内置后端、7059型号/2224FLM哈希、退出释放、更新签名及三端公开索引通过。 HPMLinkV4.5.1、MicroLinkV4.5.1/V3.5.0/V2.8.0已公开下载校验；25项发布/升级测试通过。V2 RBL头/体CRC、长度及程序版本验证，打包头V1.0.0保留原件。此发布轮未刷机，不新增硬件认证。 PR #6同步四份固件至源码目录，合并前Python2306/2跳过、GUI720及生产构建通过。
- **STM32与HPM功能回归**：按目标和功能查阅 v0.2.2-v4-stm32-regression-20260920.md、v0.2.2-v4-hpm6e80-regression-20260920.md、v0.2.2-online-verify-theme-20260920.md（均位于docs/verification）。包含高速档、烧录、窄值/非对齐、共享流、CLI/MCP/GUI；HPM6E80本轮UART未接。
- **HPM5301用户OTP**：docs/verification/v0.2.2-hpm-offline-otp-20260920.md：独立Flash回读门槛、旧API/旧值/缺文件停止、用户字和组18/19永久锁、真实Chrome/UART及断电保持通过。不能外推其他型号或安全生命周期字段。
- **nRF54L15保护**：Python真机 APPROTECT/SECUREAPPROTECT 写入、复位保护状态3、AHB关闭、CTRL-AP恢复0.923秒、1560576字节全空检查、客户HEX恢复校验通过。原始证据保存在用户测试目录 .mklink/security_roundtrip_20260924.json。别名与算法目录回归19项通过。
- **0.2.3本地安装交接**：标准builder成功，覆盖安装退出0；Skill升级至0.2.3，插件版本及安装清单、安装包SHA256、D盘ProductVersion=0.2.3均核对。用户启动后8765 health=ok、探针枚举正常；nrf54l/V4 unlock_supported=true、lock_supported=false。sidecar SHA256=925C353519384C6EADE1D8C9467218D212C69A6904B4C42CCF6AA8B1E62221DF，与构建产物一致；无Python回退，正常退出后主进程/sidecar及8765监听均清零。
- **0.2.3在线nRF54L安全操作阶段验证**：docs/verification/v0.2.3-nrf54l-online-security.md：新配方9项、在线API/CLI相关155项、GUI相关101项通过；生产前端构建成功。全量Python2320通过/2跳过、GUI721通过，各有1项既有版本断言失效，修正后单项复测通过。真实Chrome的V4探针/目标选择和两项确认弹窗通过，弹窗取消；未执行真机安全写入。
- **0.2.3在线烧录扇区几何修复**：docs/verification/v0.2.3-sector-geometry-20260924.md：审计7059型号，27个存在地址重叠且扇区声明冲突，STM32F767xG 双Bank/单Bank分别16/32KiB。按所选FLM绑定检查、映射和任务，未选择或冲突自定义FLM时拒绝；Pack优先使用FLM可变扇区范围，缺口和不完整尾部保持不可验证。Python全量2326通过/2跳过，最后冲突保护定向1项通过；GUI全量723、最后按钮门禁定向97项通过，生产Web构建与真实Chrome入口检查通过。未执行真机擦写。
- **0.2.3 VCC 测量**：docs/verification/v0.2.3-power-telemetry-20260928.md：主机135项、Skill与V3/V4 C模型和SEGGER构建通过。V3实际 raw/CLI/MCP 电压3246–3248mV、current/power null通过；未测V4和仪表精度。另见v0.2.3-v3-h743-acceptance-20260928.md：H743三场景4140样本、非对齐读写/全零/恢复通过；RAM表头碰撞修复，98项回归通过。历史USB掉线及Windows433待解决，未发布。

## 架构决策

- 开发主仓库MicroKeen/main；后续修改从最新main创建codex分支，经PR及必需CI整合。审批人数0，发布和合并仍需明确授权；标签不可变。
- 应用主索引MicroKeen/release，旧GitHub/updates兼容，Gitee/updates备用。固件三个firmware索引保持兼容，客户端URL仍可指向旧GitHub。
- 现有自动固件更新仅支持UF2；V2 RBL作为手动升级附件，不写入严格UF2索引，避免破坏0.2.2解析。
- 按维护者授权，Gitee应用发布页仅保留最新0.2.2，固件渠道独立保留；GitHub历史版本不删除。
- 保留正式包、唯一备份、依赖缓存和必要HIL证据。原主工作区用户固件替换不得reset。mklink-issues-pr自动任务维持暂停。

## 真机环境

- **state**：2026-09-28：V3+STM32H743 已连接。V3 电压约 3246–3248mV，current/power 不支持返回 null；实际 CLI 与 MCP 测试通过。H743 功能验收通过，USB 稳定性问题独立未解决；未用仪表校准，未测试 V4。
- **backups**：本地.build/reports保留原始HIL证据；Gitee历史备份与清理记录在.build/artifacts/gitee-historical-backup-20260921。
- **installer**：.build/artifacts/v0.2.3-local-20260924/Mklink-AI-Probe-v0.2.3-x64-Setup.exe；SHA256 552EB646504C162AE4E5738280A054063704A88DA97F9EEC8202C69017BDD6D0。标准NSIS，自带后端与7059型号/2224算法，安装/S退出0；未正式发布，无更新签名。 实际安装目录 D:/Program Files/Mklink AI Probe，ProductVersion=0.2.3。

## 下一动作

1. 继续 USB 稳定性排查：连续芯片识别失败、DAP 整命令关中断、USB 重配置收发队列状态、看门狗复位原因。H743 功能最终轮和客户 H563 已通过；不能据此宣称 USB 稳定性通过。V4 遥测及外部仪表精度待测，安装包尚未集成本轮解析修复。
2. 用户若明确授权，按当前目标与已验证客户HEX执行在线GUI加锁、复位核对、CTRL-AP解锁、重烧和全量回读；记录证据。未经授权不执行擦除或安全写入。
3. 若有STM32F767xG板卡，先确认实际Bank模式，再用对应FLM执行真机检查与独立回读；对26个缺扇区表FLM取得可信Pack/厂商资料后补齐。
4. 手动清理移交：旧候选.build/artifacts/v0.2.3-dev和v0.2.3-nrf54l-offline此前删除被自动审批拦截，路径已给用户；未核实用户是否删除，不重试绕过。保留v0.2.3-local-20260924、正式0.2.2及唯一真机证据。 新会话继续codex/0.2.3-dev，先读取本文件并重新加载本地0.2.3 Skill。用户安装版位于D:/Program Files/Mklink AI Probe；开发WebGUI此前使用8785，操作前重新核对进程、设备和端口。0.2.3尚未正式发布。
5. 手动清理移交：旧候选.build/artifacts/v0.2.3-dev和v0.2.3-nrf54l-offline此前删除被自动审批拦截，路径已给用户；未核实用户是否删除，不重试绕过。保留v0.2.3-local-20260924、正式0.2.2及唯一真机证据。

## 已知限制

- 有限缓冲不保证无限暂停/物理断线无损；外设轮询可能漏短脉冲，多变量不是原子快照。 VCC遥测需要配套新固件；V3仅电压，V4功率为滤波电压电流乘积，未新增校准。135项测试和固件编译不能替代真实负载精度验证。已安装0.2.3二进制尚不含本次源码。
- 客户原始ELF/程序不可用，不能宣称复现其毛刺根因；odd-address packed halfword不保证原子性。
- HPM OTP仅按报告限定型号和字段；当前HPM5301组18/19永久锁定，禁止重放配方。其他安全GUI写入口未开放。
- PY32F030保护后恢复、物理Modbus、所有板卡、Mac/Linux与跨主机Agent未完整认证；STM32看门狗、STOP/STANDBY、WRP拒写仍待专测。
- Windows安装器无Authenticode签名（未知发布者），自动更新签名已验证；标准包不含离线WebView2。原生桌面本轮无新增视觉截图，Chrome截图不替代桌面视觉验收。
- HPM6E80回归有限时长且无UART；本次用户更新的四份固件只做格式/CRC/公开发布验证，不把历史实测外推到新二进制。
- nRF54L15 CTRL-AP 解锁已在 V4.5.1 真机验证：脚本恢复后客户 HEX 脱机烧录、全量回读和运行后保护状态通过；未在固件中写入 nRF54L15 型号。在线GUI已接入安全操作，但尚未做本轮真机加锁/CTRL-AP解锁闭环；脱机GUI仍仅解锁配方。此前Python真机配方通过不能外推为本轮GUI验收。
- STM32F767xG等重叠FLM型号需用户核对实际Bank模式并选择对应算法；本轮仅验证元数据、API和真实浏览器，未连接STM32F767xG真机擦写。另有26个内置FLM无扇区表且当前解析器无法解析，扇区操作继续禁用，需可信Pack或厂商几何资料。

## 延续协议

- 先核对 Git、任务和设备状态；仅按需读相关验证报告，不加载历史流水账。
