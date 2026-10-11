# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-11T18:27:20+08:00`
- 分支：`codex/0.3.4-fixes`
- HEAD：`Fix sources ddda89c5 (capture) and 4c1227b9 (probe switching/peripherals); inspect Git for current handoff tip.`
- 远端 HEAD：`microkeen/codex/0.3.4-fixes; base microkeen/main 271af444. Verify current tip with Git.`
- 工作树：Original Mklink-AI-Probe remains the maintenance workspace. 0.3.4 changes are isolated on the task branch; source and production Web committed, hardware sessions released.
- 当前任务：0.3.4 RTT/SystemView/SuperWatch 与下载器切换修复完成。采集源 ddda89c5；新增源4c1227b9：外设ID去除绝对解压路径，失效偏好不阻断连接并提示重选，GUI切回已有下载器复用现有符号/采集。594项相关Python、70项GUI、生产构建通过；两实体下载器/独立桌面代理/真浏览器切换验证，原V3 RTT+126次内存检查0错误、符号版本不变。交接见v034-rtt-startup.md与v034-probe-switch-peripherals.md。PR40未合并或正式发布，未重建安装器。
- 状态：`complete`

## 里程碑

- **0.3.4 采集与下载器切换修复** — `verified`。源码ddda89c5/4c1227b9；采集准备、MUX诊断、稳定外设ID与非阻断恢复、GUI跨下载器复用现有连接。V3/F103、双实体下载器及生产Web/代理复核通过。PR40待整合；未发布或新安装器验收。
- **0.3.3正式版** — `complete`。源11616f80，PR38；Windows/ARM/Linux/Intel包、五份签名、三渠道核对和本地Skill更新完成。正式归档已回原工作空间；见v033-release-handoff.md。
- **0.3.2正式版** — `complete`。源3d511e94，PR35/36；三平台原生构建38028928283。Windows实装、五份更新验签、三个渠道已核对，见v032-release-handoff.md。
- **0.3.1正式版** — `complete`。PR33合并，源1d61159d；签名NSIS/Skill/SiteAgent与三端索引完成，最终提取包检查通过。见v031-release-handoff.md。
- **0.3.0正式版** — `complete`。签名NSIS、Skill、远程服务包及三端更新索引发布完成；精确源提交ec1d2834。安装/退出、CLI/MCP通过，Web由用户确认。
- **2026-10-09固件** — `complete`。用户指定MicroLink V4.6.3 SHA e960cb70，1625600B，三端下载及独立索引核对；与旧605验收UF2不同，不继承旧HIL。其他型号未变。

## 验证证据

- **0.3.4 采集启动与通信**：源 ddda89c5；Python 全量4752通过/2旧读取顺序断言失败/2跳过，更新断言后相关487通过，最后边界与断连177通过；最终合计4757通过用例/2跳过。GUI全量936通过，补改冲突提示后SystemView25通过，最终937用例；生产构建通过。6万符号ELF基准20–22秒→1.45–1.51秒；V3/F103 RTT8+Watch3+跨客户端内存约126秒，读错误0；Trace三次0.53–0.66秒。最终冷启RTT0.328秒、Watch35209周期0错误、Trace0.354秒/123150事件；Web13任务72MHz/331969事件/drop0，停止释放通过。见v034-rtt-startup.md。 后续原工程原地编译/烧录校验通过，直接加载原 Obj AXF：RTT 0.246秒，Watch 35225周期0错误，Trace 0.379秒/122139事件；后台释放。05faf1e3 的三项 PR CI 全通过。 切换源4c1227b9：最终594项Python、70项GUI及生产构建通过；失效偏好下真机连接/RAM/RTT成功，页面重选后4876外设项、两次新后台冷启恢复；双实体A→B→A→B不影响另一窗口RTT，126次内存检查0错误，符号generation不变，后台释放。见v034-probe-switch-peripherals.md。
- **0.3.3 正式发布**：精确main11616f80重建Windows/Skill/SiteAgent；ARM/Linux CI38069170299，Intel详细重跑38071279659成功。三个native清单及冻结CLI/MCP/退出通过，五份签名实际验签。正式Windows提取包Windows-only PATH、35Web资源、原生界面/区域高度/退出通过；不计本次UAC取消为重新安装。两GitHub各17公开附件与三渠道回读验证，本地Skill逐文件核对并验证CLI/SVD/MCP；详见v033-release-handoff.md。
- **0.3.3 最终候选与补充回归**：源码77f56f20/Web0c01a71b；GUI934通过，Python合计4747通过/2跳过（首次磁盘满项F盘重跑）。实装载荷摘要一致、最小PATH启动及冻结CLI/MCP/F407VE目录通过；F103RC全流程约10.25秒、AXF5909变量解析和实际搜索/拖动通过。三平台原生CI38067335470全成功。e90f6df1修测试本地偏好串扰，精确复现12失败后115波形用例及GUI CI38068369545通过；后台管理测试固定中文，不改产品运行时。见v033-release-readiness.md及本地v033-final证据。
- **0.3.3 在线烧录算法选择与布局**：源码92e33221/Webee0c2024；连接折叠摘要、资源按钮、联网下载、多FLM选择及镜像地址映射。GUI120、Python530、构建通过；浏览器双分区模拟及真实内置F103RE文件解析通过。初次本地FLM目录缺失导致21项安全测试失败，基线同样失败，指定现有资产目录后全通过；未修改白名单。无物理烧录，未更新NSIS。见v033-online-flash-algorithms.md。
- **0.3.3 SuperWatch工具栏与自动配置**：源码5444d3a5/Web32c69bb7：两行44/42px；移除原始日志及保存/加载；触发弹窗、日志导出/回放菜单、本地自动偏好。GUI180、Python283+56、TypeScript/构建通过；真实浏览器模拟1600×900/1200×720验证布局、100k/10µs/触发参数刷新恢复和日志入口。启动间隔仅在已有共享启动事务首次应用，并发/资源冲突/独占恢复测试通过；不恢复旧目标地址或覆盖共享工作区。无硬件；未重建NSIS。见v033-superwatch-toolbar.md。
- **0.3.3 SuperWatch目录分区**：源码0ed75a71/Web b764ede3：三块独立折叠并本地记忆；搜索保留常用变量。四个GUI测试文件36项及TypeScript/生产构建通过。实际浏览器运行生产组件/样式加模拟API：三组信号、三个常用、80普通变量；500px目录/720px高收起上方后完整显示12行，滚动到80并勾选、常用搜索、刷新及键盘展开通过；280px/540px窄矮窗口可操作。无硬件、无锁或固件修改，未更新NSIS。见v033-superwatch-sections.md。
- **0.3.3 文件来源历史**：源码132cb364/Web9f013b65：ConfigView/desktopSettings/filePicker 57通过，TypeScript/生产构建通过；实际浏览器无硬件lobby验证三条录入、最近排序、鼠标/键盘选择、筛选、删除和刷新保留。历史仅客户端本地保存，上传快照不混入；不自动解析/连接。见v033-symbol-path-history.md。未重建NSIS。
- **0.3.3 worker/卷枚举/MCP环境**：源码350c3c18及b5ef7c5f；1521共享架构扩展回归通过，最后背压调整及包边界97通过。V3.6.4仅USB最终重跑100次worker/串口冷开关、10次共享后台冷启动/释放、100次共享附着、实际生成配置在最小PATH下MCP stdio与CLI设速率、原生卷发现/WMI失败注入回退均通过。无目标/磁盘写入，后台已释放。报告v033-worker-volume-mcp.md。客户Python3.12/权限原环境及有目标高速采集未重跑；旧NSIS不含本轮修复。 最后关闭状态发布/端口所有权70项通过；最终真机整组在b5ef7c5f重跑。

## 架构决策

- 应用开发从MicroKeen/main建codex分支，经PR、CI整合；发布及合并需明确授权，标签/资产不可覆盖。
- 0.3保留CDC：USB序列号绑定后台及MSC，本机别名不写固件；多设备不选第一台，丢失身份拒绝新操作，不重放。GUI/MCP和已迁移CLI不再有--direct；Python脚本新增共享SDK，低层Device仍供后台/专用工具使用。后台协议50，内嵌远程服务已接入共享会话，仅允许绑定物理探针后台。 工程上下文固定于后台生命周期；删除旧PUT热切换入口，换工程须显式停止该探针后台再启动。 发现统一被动MI_04枚举，删除discover/自动连接全局锁/失败遍历与保存COM；底层自动连接也只接受唯一候选。 CDC和MSC共用probes不可变进程绑定，Bridge开口前后校验，lobby拒绝CDC/MSC/目标访问，允许独立UART会话；不是原子句柄身份认证。
- 应用MicroKeen/release主索引，旧GitHub/updates与Gitee/updates兼容；探针固件独立firmware索引。V2 RBL仅附件。
- 用户授权正式发布0.3.2与V3.6.4/V4.6.8/HPMLink4.6.8；原MK-Firmware同步最新，旧用户固件仅归档备份，不恢复stash。
- 用户接受30MHz并行目标读错留待下版，不写公开发布说明；Mac/Linux实机后验，Windows本轮已实际覆盖安装通过。
- 原Mklink-AI-Probe是唯一维护入口。0.3.3正式包/证据已回原.build/artifacts/v033-official；F盘为构建缓存。交接PR合入后删除startup-cdc临时工作树并记录结果，保留共享依赖和必要客户证据。
- mklink及既有长期跟进维持暂停；不得因旧交接自动接管硬件或重复发布。
- 用户明确授权合并0.3.3修复分支、签名正式发布、更新本地Skill及清理临时工作树；PR38已合入并发布。探针连接/时钟不要求目标板；固件需要改动时另开会话。Gitee缺失镜像沿用此前GitHub兜底，渠道最后写入。
- 用户特别要求：锁相关修复必须结合整体共享架构，不能仅消除当前卡点。保留唯一串口所有权、USB身份绑定、会话/操作锁及未知结果不重放；审查读写控制顺序、epoch隔离、取消完成前缓冲寿命、背压错误传播和端口释放，再以跨客户端与真实进程/硬件验证。 父进程仅在worker真正退出后发布串口关闭，避免其他线程提前释放应用锁。 0.3.4 继续保留这些边界；单次调用上下文缓存 RAM，未知响应不重放，错误可见不提前释放采集所有权。 GUI切换下载器保持每个物理探针一个后台，只切换当前窗口代理；加入已有连接不修改其ELF/芯片/解析器。外设ID使用Pack版本/型号/SVD相对路径，失效偏好仅禁用外设目录，不阻断设备；无法反推的旧ID由用户重选。
- 测试工程直接在用户指定原目录修改和构建，直接使用其 build/keil/Obj ELF，不再复制工程到其他目录；用户允许任意测试修改，不要求备份还原。详细硬件路径仅留本地。

## 真机环境

- **state**：用户授权V3/F103与第二只下载器切换验证，允许修改原测试工程且不复制。原build/keil/Obj/rt-thread.axf与板上SystemView程序一致。本次原工程注入失效外设ID后连接/RAM/RTT成功，已在页面重选STM32F103RE保存稳定ID；两次冷启动恢复4876项。两实体下载器、两个独立生产桌面代理及真浏览器A→B→A→B通过；第二只未接目标，只验证连接隔离。原V3持续RTT/内存126次0错误，符号不变。全部测试窗口/代理/SDK已停，后台列表为空；未改供电/下载器固件或重刷目标。路径身份仅留本地。
- **installer**：实际安装及F103回归来自77f56f20候选；正式11616f80运行时代码相同，已重建签名NSIS并验证提取包CLI/MCP/SVD/Web/原生界面/退出。本次再次覆盖安装UAC取消，未计新安装通过。详见v033-release-handoff.md。
- **backups**：原Git根.build/artifacts/v033-official保存17正式文件、archive-manifest及qualification（含候选实装/F103、正式冻结/签名/渠道/Skill证据）；旧0.3.2正式归档及用户备份保持。F盘保留共享缓存；联接测试目录和旧安装器占用文件不强删。

## 下一动作

1. 审查整合codex/0.3.4-fixes的PR40；源ddda89c5（采集）、4c1227b9（切换/外设恢复）。详见v034-rtt-startup.md与v034-probe-switch-peripherals.md。客户旧外设哈希无法反推时需在界面重选一次，不要求删文件。合并、构建安装器及正式发布仍须明确授权。
2. 收集两位 RTT 客户的上位机/下载器固件版本、目标 ELF/芯片及 IDE 占用，用启动阶段耗时和 MUX 请求身份复核。历史 unknown 操作不得重放；原始 CDC/F405/受限 AI/GD32 仍待现场闭环。
3. 继续排查 30MHz 并行目标读错/Flash 偶发 status5，区分固件目标访问与主机队列；本次低负载 F103 结果不关闭该限制，需要固件改动另开会话。
4. 检查 Gitee 镜像容量与可达性；缺失附件沿用 GitHub 兜底，不宣称国内镜像完整。历史联接/占用目录留人工处理。
5. 收集 Mac/Linux USB/MSC 和原地升级反馈、外置 Flash 多算法实物验证；完整 SES/芯片/拔插断电组合仍待补充。供电每次确认具体电压，长期验证仍暂停。

## 已知限制

- 原始30MHz/1µs CDC失败、首次启动离线和客户F405 PROGRAM100%后读线程退出仍未复现；诊断与保护不等于根因闭环。客户Python3.12/受限AI/GD32仍待复测。F103校验约0.30秒无显著加速；外置Flash多FLM缺少实物验证。历史unknown任务不得改判或重放。最新候选已覆盖安装，取代此前暂缓安装记录。 本轮修复可复现的RTT主机缺陷；两客户版本/目标ELF/IDE占用尚不全，未证明所有后续MUX超时同根因，按新增opcode/request/epoch继续核实。
- V4.6.8 30MHz RTT8/Watch4/UART并行目标读错1kHz +1、最大+273；10MHz0。旧V4.6.6原始+1/+224，报告此前漏记已更正。采集不停止、不误断、UART完整；用户明确继续发布，限制交接下版处理，不写公开发布说明。
- HPM/SES退出未发送DAP_Disconnect时可遗留占用，后续legacy握手等待；明确退出后正常OpenOCD init/resume/shutdown可恢复，用户可重插USB。禁止任意超时偷取调试所有权。完整SES矩阵和RTT下行未全部覆盖；V3.6.4/V4.6.8仿真中新启采集及负载读回通过，V4.6.8已完成Keil及相关矩阵。详见release handoff；长期目标暂停。
- 性能和功能证据按docs/verification/v030-release-handoff.md及各精确提交报告解释：采集不是无损通道，缓冲溢出/暂停/调试下载可能丢失观测；多变量不是原子快照，不能保证任意时序上界。
- V3无屏幕、不支持HPM；V3.6.4原生Keil先运行再采集、暂停/单步/继续/退出和OpenOCD均通过。V4最终无诊断固件完整SES矩阵未完成。
- 后台最后会话释放约5秒租约，加排空和退出开销；实测约5.2~6.1秒，不保证硬实时5秒。界面端口可以不同，物理探针仍由同一后台唯一拥有。
- 长期验证按用户要求暂停；跨物理主机Agent、Mac/Linux、真实Modbus从站及全部芯片组合未完整认证。模拟测试不得替代实体边界。
- nRF54L15 GUI保护闭环、全部物理擦除/拔插/休眠/断电场景、电源外部精度校准未全部认证。VCC每次改动必须确认具体电压，HPM已锁定OTP不得重放。 已知无可靠扇区表的26个FLM禁用扇区操作；重叠算法需要匹配Bank模式。

## 延续协议

- 交接只保存现状、关键限制和报告索引；详细历史留在docs/verification。
