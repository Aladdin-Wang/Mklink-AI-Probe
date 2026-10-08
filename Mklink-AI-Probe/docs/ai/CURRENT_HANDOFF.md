# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-09T01:13:14.0017914+08:00`
- 分支：`codex/0.3.1-fixes`
- HEAD：`Product aad53020; final tests 72962eda; production Web 66a5d0fb (build 72962eda). Later documentation only; inspect Git for current tip.`
- 远端 HEAD：`microkeen/codex/0.3.1-fixes / PR #33; verify Git for latest documentation tip.`
- 工作树：Isolated 0.3.1 host repair worktree. Original main firmware edits and installed official 0.3.0 preserved.
- 当前任务：0.3.1候选NSIS/Skill/Site Agent已构建，PR #33。新增共享flash嵌套锁、RTT假签名扫描修复；版本统一。用户休息并豁免UAC安装验证，未授权合并发布。V4.6.2真机发现1kHz Watch饿死UART，已明确释放所有硬件给固件会话修复，等其新的最终交接后再测；不得因旧交接再次接管。自动跟进mklink保持活动。
- 状态：`in_progress`

## 里程碑

- **0.3.0正式版** — `complete`。签名NSIS、Skill、远程服务包及三端更新索引发布完成；精确源提交ec1d2834。安装/退出、CLI/MCP通过，Web由用户确认。
- **0.2.3正式版** — `complete`。三个发布渠道及更新索引通过；本地安装版和Skill为b0e0f61。
- **2026-10-08固件** — `complete`。用户提供MicroLink V3.6.0、MicroLink/HPMLink V4.6.0，UF2及三端下载哈希和独立索引验证；V2.8.1不变。未将旧候选HIL当成新二进制实测。

## 验证证据

- **0.3.1发布准备及新真机失败**：见v031-release-preparation.md、v031-hardware-acceptance.md。最终完整Python4566通过/2跳过，640.25秒；此前3个测试断言修正后全套重新运行通过。GUI911、Rust桌面21/SiteAgent6、构建及66a5d0fb/c89ef46d三项CI通过。提取候选MCP/CLI/Web无外部Python通过，非覆盖安装。V4.6.2+F103RE实际在线/脱机/共享flash成功，校验失败及停止自动恢复RTT8/Watch4，完整512KiB读回不变；OpenOCD halt/step/resume/shutdown、GUI退出AI接管、最后退出5.63秒释放端口通过。UART基础及记录/队列/广播/原始文件通过，但1kHz Watch并发UART无响应，100/10Hz与单RTT正常；固件会话定位priority7 fast-service饿死priority10串口前台。等待修复后的新UF2和最终交接，未完成完整验收，未发布。
- **0.3.1下载、控制权和界面**：下载源码7b9c87a8/资源b91acb92：Python扩大818、最终相关75通过；GUI最终相关150、TypeScript和生产构建通过，真实浏览器模拟API验证拒绝清凭据及完成自动解锁。控制权/Skill源码7e46aabe：最终364项Python/文档回归及Skill quick_validate通过，含真实无硬件后台进程经新管理入口退出/释放实例锁。修复GUI所有权遗留，新增不依赖connect的诊断/定向管理。见v031-download-acquisition.md、v031-runtime-recovery.md。本批未构建NSIS/覆盖Skill或客户电脑实机验证。 固件升级6d2fc0fa：311 Python、54 GUI、57文档通过，自动同身份UF2与无指令手动回退；串口折叠0e6047ac：24 GUI通过；两批TypeScript/生产构建与真实浏览器模拟API通过，草稿折叠保留。报告v031-firmware-update-ui.md、v031-serial-extensions.md。均未打包安装或刷实机。
- **0.3.1启动及连接修复**：首批启动：1013 Python、905 GUI、21 Rust通过；本地提取包冷启动12.159秒、Web/MCP/CLI通过，实际覆盖安装受WinError740阻挡。连接批次：1175 Python扩大回归通过；最终ed67c134回归404通过；GUI 907通过，生产页面占用提示/管理入口浏览器验证通过（模拟API）。协议50，明确连接重新发现同一USB身份、撤销失效目标会话并保留UART/在途任务；已知MI_04恢复不做多余身份打印；target busy不毒化MUX、不重放写。实体拔插/旧固件/客户电脑待回归。报告v031-startup-audit.md、v031-connections.md；最终本地构建状态见连接报告。
- **0.3.0正式发布回归**：4471 Python通过/2跳过；902 GUI通过（干净npm ci后再次通过）；签名NSIS安装退出0，三负载哈希匹配。本地Skill更新，7059目标/2224算法；冻结版和Skill MCP/CLI通过。桌面配置/枚举通过；Web由用户手动确认连接STM32与v0.3.0。关闭后无MKLink进程、8765/8766无监听。详见v030-release-handoff.md，不能等同所有实体矩阵重新通过。
- **CDC多路复用主机接入**：full-function-audit-030.md末尾：最终安装/Skill与算法资产验证、安装MCP/CLI/Web双GUI、双探针独立退出、同机WLAN认证及隔离通过；冻结MCP打包缺陷已修。最终代码90cee876，后续仅生成资源和文档。完整自动化不等于全部实体边界通过，长期及旧持续目标保持暂停。 历史：docs/verification/cdc-multiplex-host.md：1362后端通过/2跳过，最终Bridge补测69通过；GUI整套851通过、最终相关52通过，生产构建及真实Edge/stdio MCP短测通过。双RTT+Watch+内存读写校验恢复、CLI多通道采集、会话恢复通过。全仓离线安全算法资源及联网wheel测试未通过/未完成。 Skill旧通道上限断言已修正，反馈契约66项通过。 MUX及RTT GUI回归已加入现有CI测试清单。 见cdc-multiplex-host.md安装补验：f17e4047三项CI通过，本地NSIS安装退出0，三负载哈希匹配；sidecar与Skill算法7059/2224验证。安装版Web双RTT+Watch+本地Skill stdio MCP通过，正常关闭6.16秒释放COM；原生桌面及CLI双通道共存、正常退出通过。 RTT多面板与0.3.0记录：54项相关GUI通过，真实浏览器收起保留及双通道+Watch+MCP通过。 b21d071c多面板安装/Skill覆盖、原生版本弹窗与安装态共存补验通过，5.75秒退出。 各通道平等版474ef405：188后端/65GUI、三项CI通过，安装与本地Skill覆盖、真实Web双通道/Watch/MCP/CLI、6.03秒退出释放COM及原生版本说明通过。 V3迁移补验：offline_download/device_configuration两套111通过；首次未绑定本地算法资产时21失败，绑定既有MKLINK_BUILTIN_FLM_ROOT后通过。V3真实配置读取及错误容量拒绝通过，无保护/电压写入。
- **149固件与后台空闲退出**：docs/verification/runtime-idle-mux-149.md：最终安装版GUI退出6.05秒、AI强杀5.40秒释放COM；真实双网页退出通过，网络排空上限回归4项通过，5508bd06三项CI及固件4ab77c2两项CI通过。 新补验：runtime-idle-deadline.md：保留5秒租约和所有忙碌保护，仅消除最长约1秒的轮询量化；44测试通过，源码真机多客户端和RTT8通过，端口5.232秒释放，后台5.420秒退出。不承诺硬实时5秒；打包安装待后续。 打包补验：3e65f1ad本地NSIS已生成、本地Skill更新；冻结MCP+Skill MCP精简PATH通过，提取包多客户端RTT8/CLI真机端口5.241秒释放，进程5.427秒退出，无Python子进程。包内Web39文件一致；非覆盖安装。
- **统一远程GUI**：148：应用06494629安装及Skill同步，三项包内负载哈希一致；109后端、247GUI通过，测试修正ff0c5b4c三项CI通过。源码RTT及安装版Memory/符号/SuperWatch、断线禁用并保留快照、桌面代理读取与管理拒绝通过；仅同机LAN短测。
- **共享后台、多探针与AI共存**：144相关回归539通过/1跳过；1aca5414三项CI通过。145安装版单V4桌面/Web/Skill三客户端共存、正常退出隔离、健康检查通过；双探针证据仍为142源码短测。

## 架构决策

- 应用开发从MicroKeen/main建codex分支，经PR、CI整合；发布及合并需明确授权，标签/资产不可覆盖。
- 0.3保留CDC：USB序列号绑定后台及MSC，本机别名不写固件；多设备不选第一台，丢失身份拒绝新操作，不重放。GUI/MCP和已迁移CLI不再有--direct；Python脚本新增共享SDK，低层Device仍供后台/专用工具使用。后台协议50，内嵌远程服务已接入共享会话，仅允许绑定物理探针后台。 工程上下文固定于后台生命周期；删除旧PUT热切换入口，换工程须显式停止该探针后台再启动。 发现统一被动MI_04枚举，删除discover/自动连接全局锁/失败遍历与保存COM；底层自动连接也只接受唯一候选。 CDC和MSC共用probes不可变进程绑定，Bridge开口前后校验，lobby拒绝CDC/MSC/目标访问，允许独立UART会话；不是原子句柄身份认证。
- 应用MicroKeen/release主索引，旧GitHub/updates与Gitee/updates兼容；探针固件独立firmware索引。V2 RBL仅附件。
- V3 main bdd18d7、V4 main ed73ae9已通过CI并合并推送；本地已切main。Arm-2D/MicroBoot等子模块保持原状。
- 正式包、唯一备份、验收证据和依赖缓存保留；本轮清理20项约1.68GiB，48个含链接临时目录留待人工检查。mklink-issues-pr自动任务维持暂停。
- 2026-10-08用户明确授权正式0.3.0发布、版本说明精简及V3/V4推送main；固件已经CI/PR整合，主机仍须精确提交发布门槛。
- 用户最新已提供最终V3.6.0/V4.6.0/HPMLink V4.6.0 UF2并明确授权一起发布，取代此前暂缓指示。文件由用户编译提供，不得将先前HIL候选的哈希或性能结果称为最终二进制重新实测。

## 真机环境

- **state**：2026-10-09本会话V4.6.2/F103RE候选HIL后，目标512KiB与备份逐字节一致，VCC未改，后台5.63秒退出，COM命令口/UART可开关、无遗留句柄。因1kHz Watch/UART失败，已明确交还固件会话01a11b6a-0a88-73a0-b6f7-919ab7454c92；必须等新最终交接才再操作。
- **installer**：现有正式0.3.0未覆盖；0.3.1本地未签名NSIS已提取三负载测试，候选在主工作区.build/artifacts/v031-candidate-72962eda。用户明确豁免需要人工确认的管理员权限安装验证。
- **backups**：原始实机证据、发布包与清理清单保留在本地.build。

## 下一动作

1. 等待固件会话修复1kHz/最大速率Watch导致UART/RS485饥饿，收到新最终UF2 SHA、原目标恢复SHA和明确设备可接管后，重新验收相关并发矩阵。硬件现由固件会话独占，未交接前不触碰串口/SWD/供电。
2. 最终Python4566通过/2跳过，GUI911、Rust桌面21/SiteAgent6、候选构建和c89ef46d三项CI通过。继续更新最终验收文档/记忆/PR #33并推送精确分支；用户只授权准备，不合并/签名/发布/改渠道。
3. 新固件交接后补最终候选重连、完整退出释放与已测烧录自动恢复受影响回归；真实自动UF2升级、旧型号按键路径、物理拔插/客户CS32L015等缺口按实物条件如实记录，不制造模拟实测通过。
4. 完整用户授权范围完成后暂停mklink自动跟进；未变化静默，仅完成/实际失败/需用户动作通知。VCC每次仍需具体电压确认，未知程序禁止覆盖。
5. 长期验证继续暂停。UAC安装验证明确豁免；提取包不能称覆盖安装，旧固件或另一提交结果不能称当前二进制重新实测。

## 已知限制

- HPM/SES退出未发送DAP_Disconnect时可遗留占用，后续legacy握手等待；明确退出后正常OpenOCD init/resume/shutdown可恢复，用户可重插USB。禁止任意超时偷取调试所有权。最终无诊断固件完整SES矩阵、已在仿真时新开采集、RTT下行及负载下烧录回读仍需后续验证。详见release handoff；长期目标暂停。
- 性能和功能证据按docs/verification/v030-release-handoff.md及各精确提交报告解释：采集不是无损通道，缓冲溢出/暂停/调试下载可能丢失观测；多变量不是原子快照，不能保证任意时序上界。
- V3无屏幕、不支持HPM；V3原生Keil暂停/单步尚未完成，OpenOCD对应流程通过。V4最终无诊断固件完整SES矩阵未完成。
- 后台最后会话释放约5秒租约，加排空和退出开销；实测约5.2~6.1秒，不保证硬实时5秒。界面端口可以不同，物理探针仍由同一后台唯一拥有。
- 长期验证按用户要求暂停；跨物理主机Agent、Mac/Linux、真实Modbus从站及全部芯片组合未完整认证。模拟测试不得替代实体边界。
- nRF54L15 GUI保护闭环、全部物理擦除/拔插/休眠/断电场景、电源外部精度校准未全部认证。VCC每次改动必须确认具体电压，HPM已锁定OTP不得重放。
- 已知无可靠扇区表的26个FLM禁用扇区操作；重叠算法需要匹配Bank模式。
- Windows安装包无Authenticode签名；自动更新签名独立。正式发布必须核对manifest和三端下载哈希，不得因本地构建成功宣称已经发布。

## 延续协议

- 交接只保存现状、关键限制和报告索引；详细历史留在docs/verification。
