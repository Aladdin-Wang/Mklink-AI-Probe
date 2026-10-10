# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-10T23:09:12+08:00`
- 分支：`0.3.3修复分支`
- HEAD：`Online flash algorithms/layout source 92e33221 / Web ee0c2024; SuperWatch toolbar 5444d3a5 / Web 32c69bb7; worker 350c3c18+b5ef7c5f; probe-only ac542173. Based on microkeen/main 01b413ff. Inspect Git for documentation/PR tip.`
- 远端 HEAD：`microkeen/main; verify exact current tip with Git.`
- 工作树：Original workspace remains main; active isolated worktree Mklink-AI-Probe-startup-cdc holds user-named branch 0.3.3修复分支. Preserve it while diagnosis continues.
- 当前任务：0.3.3修复分支/草稿PR38：在线烧录紧凑排版和多算法映射完成，源码92e33221/Webee0c2024，GUI120/Python530及浏览器验证通过，见v033-online-flash-algorithms.md。用户追加授权：用本机V3/STM32F103RC工程排查在线写入100%后读线程退出、优化校验、修复SVD打包遗漏、重新打包0.3.3并覆盖安装。用户已接回目标并确认未占用，开始实际烧录诊断；不改供电或固件。前轮SuperWatch/文件历史/共享后端修复保留。
- 状态：`in_progress`

## 里程碑

- **0.3.2正式版** — `complete`。源3d511e94，PR35/36；三平台原生构建38028928283。Windows实装、五份更新验签、三个渠道已核对，见v032-release-handoff.md。
- **0.3.1正式版** — `complete`。PR33合并，源1d61159d；签名NSIS/Skill/SiteAgent与三端索引完成，最终提取包检查通过。见v031-release-handoff.md。
- **0.3.0正式版** — `complete`。签名NSIS、Skill、远程服务包及三端更新索引发布完成；精确源提交ec1d2834。安装/退出、CLI/MCP通过，Web由用户确认。
- **2026-10-09固件** — `complete`。用户指定MicroLink V4.6.3 SHA e960cb70，1625600B，三端下载及独立索引核对；与旧605验收UF2不同，不继承旧HIL。其他型号未变。

## 验证证据

- **0.3.3 在线烧录算法选择与布局**：源码92e33221/Webee0c2024；连接折叠摘要、资源按钮、联网下载、多FLM选择及镜像地址映射。GUI120、Python530、构建通过；浏览器双分区模拟及真实内置F103RE文件解析通过。初次本地FLM目录缺失导致21项安全测试失败，基线同样失败，指定现有资产目录后全通过；未修改白名单。无物理烧录，未更新NSIS。见v033-online-flash-algorithms.md。
- **0.3.3 SuperWatch工具栏与自动配置**：源码5444d3a5/Web32c69bb7：两行44/42px；移除原始日志及保存/加载；触发弹窗、日志导出/回放菜单、本地自动偏好。GUI180、Python283+56、TypeScript/构建通过；真实浏览器模拟1600×900/1200×720验证布局、100k/10µs/触发参数刷新恢复和日志入口。启动间隔仅在已有共享启动事务首次应用，并发/资源冲突/独占恢复测试通过；不恢复旧目标地址或覆盖共享工作区。无硬件；未重建NSIS。见v033-superwatch-toolbar.md。
- **0.3.3 SuperWatch目录分区**：源码0ed75a71/Web b764ede3：三块独立折叠并本地记忆；搜索保留常用变量。四个GUI测试文件36项及TypeScript/生产构建通过。实际浏览器运行生产组件/样式加模拟API：三组信号、三个常用、80普通变量；500px目录/720px高收起上方后完整显示12行，滚动到80并勾选、常用搜索、刷新及键盘展开通过；280px/540px窄矮窗口可操作。无硬件、无锁或固件修改，未更新NSIS。见v033-superwatch-sections.md。
- **0.3.3 文件来源历史**：源码132cb364/Web9f013b65：ConfigView/desktopSettings/filePicker 57通过，TypeScript/生产构建通过；实际浏览器无硬件lobby验证三条录入、最近排序、鼠标/键盘选择、筛选、删除和刷新保留。历史仅客户端本地保存，上传快照不混入；不自动解析/连接。见v033-symbol-path-history.md。未重建NSIS。
- **0.3.3 worker/卷枚举/MCP环境**：源码350c3c18及b5ef7c5f；1521共享架构扩展回归通过，最后背压调整及包边界97通过。V3.6.4仅USB最终重跑100次worker/串口冷开关、10次共享后台冷启动/释放、100次共享附着、实际生成配置在最小PATH下MCP stdio与CLI设速率、原生卷发现/WMI失败注入回退均通过。无目标/磁盘写入，后台已释放。报告v033-worker-volume-mcp.md。客户Python3.12/权限原环境及有目标高速采集未重跑；旧NSIS不含本轮修复。 最后关闭状态发布/端口所有权70项通过；最终真机整组在b5ef7c5f重跑。
- **0.3.3 USB-only连接和时钟**：源码ac542173/Web871b496f；Python十组316通过，后补USB断开用例所在文件10通过；GUI59与生产构建通过。用户确认断开目标板，本机V3.6.4/IDCODE0旧20/30MHz拒绝复现，修复后SDK4/10/20/30、实际MCP stdio30、CLI20保存、断开重连恢复20和实际浏览器30均通过。无固件/供电/目标修改，已释放后台。见v033-probe-only-connection.md，取代上一轮要求目标先识别的建议。旧NSIS不含本轮修复。
- **0.3.3 启动/CDC第一轮修复**：源码2d033e77/Web92415bb3；Python177、GUI917、Rust22及标准NSIS构建通过。冻结CLI/MCP Windows-only PATH通过；默认环境原生启动、代理退出换端口恢复、真实Web状态通过。V3.6.4/STM32F103 30MHz/1µs候选90秒约2371万样本错误/丢弃0，接收worker退出注入停采断连及显式重连恢复通过。此前695秒源码诊断出现接收队列丢弃11754288字节，无CDC错误；不能称无损。实际安装获用户暂缓。见v033-startup-cdc-recovery.md。
- **0.3.2正式安装和渠道**：v032-release-handoff.md：NSIS真实覆盖0.3.1至0.3.2、注册及载荷哈希一致；安装态CLI/MCP、36项Web字节/MIME、3.420秒lobby、8.605秒原生启动、版本日期/说明界面及正常退出通过。最终GUI914，既有Python4647/2skip，Rust21+6。五份更新签名实际验签，17个公开文件及三个渠道核对，原空间v032-official归档。Mac/Linux物理安装USB/MSC/原地更新后验，不称通过。

## 架构决策

- 应用开发从MicroKeen/main建codex分支，经PR、CI整合；发布及合并需明确授权，标签/资产不可覆盖。
- 0.3保留CDC：USB序列号绑定后台及MSC，本机别名不写固件；多设备不选第一台，丢失身份拒绝新操作，不重放。GUI/MCP和已迁移CLI不再有--direct；Python脚本新增共享SDK，低层Device仍供后台/专用工具使用。后台协议50，内嵌远程服务已接入共享会话，仅允许绑定物理探针后台。 工程上下文固定于后台生命周期；删除旧PUT热切换入口，换工程须显式停止该探针后台再启动。 发现统一被动MI_04枚举，删除discover/自动连接全局锁/失败遍历与保存COM；底层自动连接也只接受唯一候选。 CDC和MSC共用probes不可变进程绑定，Bridge开口前后校验，lobby拒绝CDC/MSC/目标访问，允许独立UART会话；不是原子句柄身份认证。
- 应用MicroKeen/release主索引，旧GitHub/updates与Gitee/updates兼容；探针固件独立firmware索引。V2 RBL仅附件。
- 用户授权正式发布0.3.2与V3.6.4/V4.6.8/HPMLink4.6.8；原MK-Firmware同步最新，旧用户固件仅归档备份，不恢复stash。
- 用户接受30MHz并行目标读错留待下版，不写公开发布说明；Mac/Linux实机后验，Windows本轮已实际覆盖安装通过。
- 原空间是唯一维护入口。正式包/证据已回原.build/artifacts/v032-official和v032-handoff，F盘仅构建缓存；清理实录见cleanup.json。固件原V3/V4 main已核对，V4-fixes已清理，用户子模块改动保留。
- mklink及既有长期跟进维持暂停；不得因旧交接自动接管硬件或重复发布。
- 用户指定0.3.3修复分支；此会话仅修改应用分支，需要V3/V4固件修复时另开会话。连接下载器及设置时钟属于探针操作，不要求目标板；精确set clock回包可确认设置，profile_confirmed单列，不冒充目标稳定性验证。安装继续暂缓；保留草稿PR。
- 用户特别要求：锁相关修复必须结合整体共享架构，不能仅消除当前卡点。保留唯一串口所有权、USB身份绑定、会话/操作锁及未知结果不重放；审查读写控制顺序、epoch隔离、取消完成前缓冲寿命、背压错误传播和端口释放，再以跨客户端与真实进程/硬件验证。 父进程仅在worker真正退出后发布串口关闭，避免其他线程提前释放应用锁。

## 真机环境

- **state**：用户确认目标板已断开，仅USB的V3.6.4。本轮最终源码100次worker/串口冷开关、10次后台冷启动/释放、100次共享附着、真实MCP stdio/CLI及20/30MHz设速率、原生MSC只读发现均通过。自有后台已退出、串口释放；未烧录、写目标、复位、改供电或写下载器磁盘。客户GD32板及有目标高速采集未重跑。身份和路径只留本地证据。
- **installer**：正式main3d511e94 NSIS SHA3e72fae43380f7b060aac2c44b2f7e813259c7dd2e33f3ea59b78d41d46a2498；Windows实际覆盖安装通过，已观察0.3.2/2026-10-10。三平台原生38028928283通过及五份更新验签；Mac/Linux物理安装USB/MSC/原地更新仍客户后验。 0.3.3修复候选为本地未签名NSIS；UAC返回取消，用户允许暂缓安装，现有官方0.3.2安装未改变。 时钟修复仅源码及生产Web已更新，先前NSIS不含该修复。
- **backups**：原Git根.build/artifacts/v032-official保存正式包、清单、安装/CI/签名/渠道证据，v032-handoff保存阶段HIL和旧用户备份；索引逐项SHA核验。固件原工程CURRENT_HANDOFF.md与firmware-releases保留必要记录。 本轮候选、哈希和诊断证据在原Git根.build/artifacts/v033-fixes；F盘复用构建缓存。

## 下一动作

1. 当前继续0.3.3修复分支：排查用户在线烧录PROGRAM100%后read thread exited；使用已接回的V3/STM32F103RC工程实际测量下载/校验，核实并修复SVD资源打包，构建本地未签名0.3.3 NSIS并覆盖安装。用户已授权本轮安装；不发布、不合并、不改供电。新包必须包含本轮及之前全部修复。
2. 继续0.3.3修复分支：优先复现30MHz/1µs CDC底层失败和首次冷启动离线，读取候选新增Win32码/启动日志。保留草稿PR；实际覆盖安装暂缓，不宣称两个根因彻底修复。
3. 保留Mklink-AI-Probe-startup-cdc工作树；原工作区仍为主入口，候选与日志已在原.build/artifacts/v033-fixes归档。不得覆盖0.3.2正式包、标签、渠道或擅自合并。
4. 下一版排查30MHz并行目标读错/Flash偶发status5，区分固件目标访问与主机队列；保持偶发错误不断采、不误断的行为。
5. 收集Mac/Linux正式包客户实机USB/MSC和原地升级反馈；完整SES、缺失夹具和全部芯片组合保持未验证，供电仍须逐次确认具体电压。

## 已知限制

- USB-only配置与本轮worker/卷枚举/MCP修复已通过本机V3.6.4/Python3.14验证，客户Python3.12及受限AI原环境待复测；不能用100次冷开关等价客户所有故障闭环。原始30MHz/1µs CDC失败和首次启动离线仍未复现；目标仍断开，本轮未重测吞吐/目标烧录。新截图Internal Server Error缺栈，客户日志身份不同；历史unknown任务不得改判或重放。旧NSIS不含最新修复，用户继续暂缓安装。
- V4.6.8 30MHz RTT8/Watch4/UART并行目标读错1kHz +1、最大+273；10MHz0。旧V4.6.6原始+1/+224，报告此前漏记已更正。采集不停止、不误断、UART完整；用户明确继续发布，限制交接下版处理，不写公开发布说明。
- HPM/SES退出未发送DAP_Disconnect时可遗留占用，后续legacy握手等待；明确退出后正常OpenOCD init/resume/shutdown可恢复，用户可重插USB。禁止任意超时偷取调试所有权。完整SES矩阵和RTT下行未全部覆盖；V3.6.4/V4.6.8仿真中新启采集及负载读回通过，V4.6.8已完成Keil及相关矩阵。详见release handoff；长期目标暂停。
- 性能和功能证据按docs/verification/v030-release-handoff.md及各精确提交报告解释：采集不是无损通道，缓冲溢出/暂停/调试下载可能丢失观测；多变量不是原子快照，不能保证任意时序上界。
- V3无屏幕、不支持HPM；V3.6.4原生Keil先运行再采集、暂停/单步/继续/退出和OpenOCD均通过。V4最终无诊断固件完整SES矩阵未完成。
- 后台最后会话释放约5秒租约，加排空和退出开销；实测约5.2~6.1秒，不保证硬实时5秒。界面端口可以不同，物理探针仍由同一后台唯一拥有。
- 长期验证按用户要求暂停；跨物理主机Agent、Mac/Linux、真实Modbus从站及全部芯片组合未完整认证。模拟测试不得替代实体边界。
- nRF54L15 GUI保护闭环、全部物理擦除/拔插/休眠/断电场景、电源外部精度校准未全部认证。VCC每次改动必须确认具体电压，HPM已锁定OTP不得重放。 已知无可靠扇区表的26个FLM禁用扇区操作；重叠算法需要匹配Bank模式。

## 延续协议

- 交接只保存现状、关键限制和报告索引；详细历史留在docs/verification。
