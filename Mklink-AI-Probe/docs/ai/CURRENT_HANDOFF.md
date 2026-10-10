# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-10T19:23:09+08:00`
- 分支：`main`
- HEAD：`Official v0.3.2 source 3d511e94742ac95ccd93c30e60349e1b560ee7a4; later closeout PR only docs/generated Web. Inspect Git for current main.`
- 远端 HEAD：`microkeen/main; verify exact current tip with Git.`
- 工作树：Original Mklink-AI-Probe is the only maintenance workspace. Temporary worktrees removed after closeout PR; local cleanup.json records actual result.
- 当前任务：0.3.2已正式发布：Windows/Mac ARM64/Mac Intel/Linux x64、五个平台更新条目、Skill/SiteAgent及三个渠道完成；Windows实际覆盖安装与正常退出通过。V3.6.4/V4.6.8/HPM4.6.8独立发布。正式包与证据已归档原空间；交接/生成Web收尾PR后按cleanup.json移除临时树。后续不重复既有真机回归。 用户新增普通启动后台离线、SuperWatch CDC queued read failed停采断连；按最新要求只初查并交接，下会话修复，本轮收尾完成不代表这两项已修复。
- 状态：`complete`

## 里程碑

- **0.3.2正式版** — `complete`。源3d511e94，PR35/36；三平台原生构建38028928283。Windows实装、五份更新验签、三个渠道已核对，见v032-release-handoff.md。
- **0.3.1正式版** — `complete`。PR33合并，源1d61159d；签名NSIS/Skill/SiteAgent与三端索引完成，最终提取包检查通过。见v031-release-handoff.md。
- **0.3.0正式版** — `complete`。签名NSIS、Skill、远程服务包及三端更新索引发布完成；精确源提交ec1d2834。安装/退出、CLI/MCP通过，Web由用户确认。
- **2026-10-09固件** — `complete`。用户指定MicroLink V4.6.3 SHA e960cb70，1625600B，三端下载及独立索引核对；与旧605验收UF2不同，不继承旧HIL。其他型号未变。

## 验证证据

- **发布后故障初查（未修复）**：代码确认Windows GetOverlappedResult失败经worker E帧、Bridge ERROR到SuperWatch stopped；现有日志无底层Win32码，不能确认根因。仅只读检查，未做新的真机测试；按用户要求移交下一会话。
- **0.3.2正式安装和渠道**：v032-release-handoff.md：NSIS真实覆盖0.3.1至0.3.2、注册及载荷哈希一致；安装态CLI/MCP、36项Web字节/MIME、3.420秒lobby、8.605秒原生启动、版本日期/说明界面及正常退出通过。最终GUI914，既有Python4647/2skip，Rust21+6。五份更新签名实际验签，17个公开文件及三个渠道核对，原空间v032-official归档。Mac/Linux物理安装USB/MSC/原地更新后验，不称通过。
- **0.3.2 V4.6.8最终收尾**：见v032-v4-final-closure.md。冻结b06 + V4.6.8后台升级13.148秒；Keil新启/暂停/单步/继续/退出、四路并发检查、在线并行512KiB保全427.25秒、脱机共享失败停止恢复57.842秒及OpenOCD/退出/重连完成。30MHz并行1kHz/最大目标读错+1/+273，10MHz0，旧V4.6.6原始+1/+224已更正。用户接受限制继续发布。
- **0.3.2 V3最终矩阵**：v032-keil-capture-start.md：V3.6.4后台升级、Keil先Run新启RTT8/Watch4、暂停单步继续退出、UART并行、在线脱机共享失败停止恢复、OpenOCD、512KiB保全及6.03秒释放通过。已收敛，不再等待V4换机；V4最终矩阵另列。
- **0.3.2最终候选与既有修复回归**：见v032-final-candidate.md。86cfdff4冻结候选实际GUI升级V4.6.6；30MHz Flash128B在1kHz/请求1µs两档完整性指标均0，最大样本间隔1049/233µs；RTT8/Watch4/UART并行、文件检查、在线/脱机/共享烧录成功/失败/停止恢复、Keil下载断点单步退出及OpenOCD、GUI退出AI接续、旧端点重发现、最后6.299秒释放通过；512KiB逐字不变，未改VCC。真实收发毫秒/RX/TX、独立RTT拖动及20/30MHz保存通过。旧155次status5不冒作新固件故障注入证据。914 GUI/生产构建通过；原生3e39e1ef构建37949511991全部成功；完整Python/Rust和交付状态以发布准备报告为准。 全量Python4634通过/2跳过，Rust21+6通过；三平台下载CRC和载荷SHA256均核验，当前候选可交客户复测。 2026-10-10更正：旧并行load实际有+1/+224目标读错；passed不代表零读错，见V4最终收尾。
- **0.3.1正式发布**：v031-release-handoff.md：main/tag 1d61159d，clean locked GUI912、签名NSIS与SiteAgent重建通过；冻结MCP/CLI、4.825秒lobby、36项Web字节一致、10.340秒原生窗口、无Python子进程及正常退出通过；UAC安装豁免。三端资产/应用及固件索引已核对。用户原GUI保留，本次不连接目标。

## 架构决策

- 应用开发从MicroKeen/main建codex分支，经PR、CI整合；发布及合并需明确授权，标签/资产不可覆盖。
- 0.3保留CDC：USB序列号绑定后台及MSC，本机别名不写固件；多设备不选第一台，丢失身份拒绝新操作，不重放。GUI/MCP和已迁移CLI不再有--direct；Python脚本新增共享SDK，低层Device仍供后台/专用工具使用。后台协议50，内嵌远程服务已接入共享会话，仅允许绑定物理探针后台。 工程上下文固定于后台生命周期；删除旧PUT热切换入口，换工程须显式停止该探针后台再启动。 发现统一被动MI_04枚举，删除discover/自动连接全局锁/失败遍历与保存COM；底层自动连接也只接受唯一候选。 CDC和MSC共用probes不可变进程绑定，Bridge开口前后校验，lobby拒绝CDC/MSC/目标访问，允许独立UART会话；不是原子句柄身份认证。
- 应用MicroKeen/release主索引，旧GitHub/updates与Gitee/updates兼容；探针固件独立firmware索引。V2 RBL仅附件。
- 用户授权正式发布0.3.2与V3.6.4/V4.6.8/HPMLink4.6.8；原MK-Firmware同步最新，旧用户固件仅归档备份，不恢复stash。
- 用户接受30MHz并行目标读错留待下版，不写公开发布说明；Mac/Linux实机后验，Windows本轮已实际覆盖安装通过。
- 原空间是唯一维护入口。正式包/证据已回原.build/artifacts/v032-official和v032-handoff，F盘仅构建缓存；清理实录见cleanup.json。固件原V3/V4 main已核对，V4-fixes已清理，用户子模块改动保留。
- mklink及既有长期跟进维持暂停；不得因旧交接自动接管硬件或重复发布。

## 真机环境

- **state**：V3.6.4与V4.6.8最终后台升级、Keil先Run后新启RTT8/Watch4及暂停单步继续退出、在线脱机共享烧录失败停止恢复、OpenOCD、GUI退出AI接续、重连与最后端口释放完成。两台最终512KiB SHA c1e51c22ae9530ee4afea9042ff6e710421bc24b6d8bf8ddd6e0992794a18bf8。未改VCC，硬件已释放。V4 30MHz并行读错留待下版，不误称零错误。 发布后用户再次操作设备并报告CDC错误，当前设备身份与旧HIL不同；本轮只读日志，禁止沿用旧硬件状态。
- **installer**：正式main3d511e94 NSIS SHA3e72fae43380f7b060aac2c44b2f7e813259c7dd2e33f3ea59b78d41d46a2498；Windows实际覆盖安装通过，已观察0.3.2/2026-10-10。三平台原生38028928283通过及五份更新验签；Mac/Linux物理安装USB/MSC/原地更新仍客户后验。
- **backups**：原Git根.build/artifacts/v032-official保存正式包、清单、安装/CI/签名/渠道证据，v032-handoff保存阶段HIL和旧用户备份；索引逐项SHA核验。固件原工程CURRENT_HANDOFF.md与firmware-releases保留必要记录。

## 下一动作

1. 下一会话优先读v032-postrelease-incidents.md和本地post-release-incidents证据，排查Windows队列读错误传播、状态矛盾及普通启动离线；尚未修复，不继承旧HIL设备信息，不覆盖0.3.2发布资产。
2. 后续从原工作空间main开展新版本；先读v032-release-handoff.md和本地cleanup.json，不再回临时工作树找资料，不移动0.3.2标签。
3. 下一版排查30MHz并行目标读错/Flash偶发status5，区分固件目标访问与主机队列；保持偶发错误不断采、不误断的行为。
4. 收集Mac/Linux正式包客户实机USB/MSC和原地升级反馈；完整SES、缺失夹具和全部芯片组合保持未验证，供电仍须逐次确认具体电压。

## 已知限制

- 发布后未解决：普通安装态启动后台离线；SuperWatch CDC queued read failed导致停采/断连，transport徽标状态矛盾。不同于status5；用户明确转下一会话。见v032-postrelease-incidents.md及原空间本地日志/截图。
- V4.6.8 30MHz RTT8/Watch4/UART并行目标读错1kHz +1、最大+273；10MHz0。旧V4.6.6原始+1/+224，报告此前漏记已更正。采集不停止、不误断、UART完整；用户明确继续发布，限制交接下版处理，不写公开发布说明。
- HPM/SES退出未发送DAP_Disconnect时可遗留占用，后续legacy握手等待；明确退出后正常OpenOCD init/resume/shutdown可恢复，用户可重插USB。禁止任意超时偷取调试所有权。完整SES矩阵和RTT下行未全部覆盖；V3.6.4/V4.6.8仿真中新启采集及负载读回通过，V4.6.8已完成Keil及相关矩阵。详见release handoff；长期目标暂停。
- 性能和功能证据按docs/verification/v030-release-handoff.md及各精确提交报告解释：采集不是无损通道，缓冲溢出/暂停/调试下载可能丢失观测；多变量不是原子快照，不能保证任意时序上界。
- V3无屏幕、不支持HPM；V3.6.4原生Keil先运行再采集、暂停/单步/继续/退出和OpenOCD均通过。V4最终无诊断固件完整SES矩阵未完成。
- 后台最后会话释放约5秒租约，加排空和退出开销；实测约5.2~6.1秒，不保证硬实时5秒。界面端口可以不同，物理探针仍由同一后台唯一拥有。
- 长期验证按用户要求暂停；跨物理主机Agent、Mac/Linux、真实Modbus从站及全部芯片组合未完整认证。模拟测试不得替代实体边界。
- nRF54L15 GUI保护闭环、全部物理擦除/拔插/休眠/断电场景、电源外部精度校准未全部认证。VCC每次改动必须确认具体电压，HPM已锁定OTP不得重放。 已知无可靠扇区表的26个FLM禁用扇区操作；重叠算法需要匹配Bank模式。

## 延续协议

- 交接只保存现状、关键限制和报告索引；详细历史留在docs/verification。
