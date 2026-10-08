# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-08T09:12:40.1288759+08:00`
- 分支：`main`
- HEAD：`Based on main d4e73bd; shared CDC development continues; long-duration validation deferred at user request. Use Git for exact tip.`
- 远端 HEAD：`Application release v0.2.3 fixed at b0e0f61; verify current main with Git.`
- 工作树：Host PR30 publication preparation; V3 main bdd18d7 and V4 main ed73ae9 merged with CI success. SDK/submodules preserved.
- 当前任务：主机PR30已合并5543b2ee；4471 Python/902 GUI及三个CI通过，正式签名构建进行中。用户最新已提供V3.6.0/V4.6.0/HPMLink V4.6.0固件并授权一起发布，取代此前暂缓指示；须独立验证上传及固件索引。V3 main bdd18d7，V4 main ed73ae9。
- 状态：`in_progress`

## 里程碑

- **0.3.0 专用CLI共享迁移** — `release_preparation`。共享后台与多通道RTT已完成多轮源码/安装态短测；完整矩阵的未验证边界见最新交接，发布授权已获得。
- **0.2.3正式版** — `complete`。三个发布渠道及更新索引通过；本地安装版和Skill为b0e0f61。
- **2026-10-03固件** — `complete`。HPMLink/MicroLink V4.5.2、MicroLink V3.5.2、V2.8.1已三端发布；V2为RBL附件，不进入UF2自动更新索引。

## 验证证据

- **0.3.0正式发布回归**：2026-10-08：4471 Python通过、2跳过；902 GUI通过（87文件）；生产构建通过。V3 PR2 / bdd18d7和V4 PR4 / ed73ae9已通过CI并合并main。签名包与最终安装/发布仍待完成，不将源码测试当成发布成功。
- **CDC多路复用主机接入**：full-function-audit-030.md末尾：最终安装/Skill与算法资产验证、安装MCP/CLI/Web双GUI、双探针独立退出、同机WLAN认证及隔离通过；冻结MCP打包缺陷已修。最终代码90cee876，后续仅生成资源和文档。完整自动化不等于全部实体边界通过，长期及旧持续目标保持暂停。 历史：docs/verification/cdc-multiplex-host.md：1362后端通过/2跳过，最终Bridge补测69通过；GUI整套851通过、最终相关52通过，生产构建及真实Edge/stdio MCP短测通过。双RTT+Watch+内存读写校验恢复、CLI多通道采集、会话恢复通过。全仓离线安全算法资源及联网wheel测试未通过/未完成。 Skill旧通道上限断言已修正，反馈契约66项通过。 MUX及RTT GUI回归已加入现有CI测试清单。 见cdc-multiplex-host.md安装补验：f17e4047三项CI通过，本地NSIS安装退出0，三负载哈希匹配；sidecar与Skill算法7059/2224验证。安装版Web双RTT+Watch+本地Skill stdio MCP通过，正常关闭6.16秒释放COM；原生桌面及CLI双通道共存、正常退出通过。 RTT多面板与0.3.0记录：54项相关GUI通过，真实浏览器收起保留及双通道+Watch+MCP通过。 b21d071c多面板安装/Skill覆盖、原生版本弹窗与安装态共存补验通过，5.75秒退出。 各通道平等版474ef405：188后端/65GUI、三项CI通过，安装与本地Skill覆盖、真实Web双通道/Watch/MCP/CLI、6.03秒退出释放COM及原生版本说明通过。 V3迁移补验：offline_download/device_configuration两套111通过；首次未绑定本地算法资产时21失败，绑定既有MKLINK_BUILTIN_FLM_ROOT后通过。V3真实配置读取及错误容量拒绝通过，无保护/电压写入。
- **149固件与后台空闲退出**：docs/verification/runtime-idle-mux-149.md：最终安装版GUI退出6.05秒、AI强杀5.40秒释放COM；真实双网页退出通过，网络排空上限回归4项通过，5508bd06三项CI及固件4ab77c2两项CI通过。 新补验：runtime-idle-deadline.md：保留5秒租约和所有忙碌保护，仅消除最长约1秒的轮询量化；44测试通过，源码真机多客户端和RTT8通过，端口5.232秒释放，后台5.420秒退出。不承诺硬实时5秒；打包安装待后续。 打包补验：3e65f1ad本地NSIS已生成、本地Skill更新；冻结MCP+Skill MCP精简PATH通过，提取包多客户端RTT8/CLI真机端口5.241秒释放，进程5.427秒退出，无Python子进程。包内Web39文件一致；非覆盖安装。
- **统一远程GUI**：148：应用06494629安装及Skill同步，三项包内负载哈希一致；109后端、247GUI通过，测试修正ff0c5b4c三项CI通过。源码RTT及安装版Memory/符号/SuperWatch、断线禁用并保留快照、桌面代理读取与管理拒绝通过；仅同机LAN短测。
- **共享后台、多探针与AI共存**：144相关回归539通过/1跳过；1aca5414三项CI通过。145安装版单V4桌面/Web/Skill三客户端共存、正常退出隔离、健康检查通过；双探针证据仍为142源码短测。
- **正式版与安装**：145本地0.3.0开发版NSIS覆盖安装返回0；主程序/sidecar/STCP与NSIS负载哈希一致；Skill版本/前端/7059目标2224blob验证。旧0.2.3正式版证据保留原报告。
- **固件发布与代码同步**：docs/verification/firmware-20261003.md；UF2格式、RBL CRC/版本、三端下载哈希和索引通过；V2/V3 AP模型、V3电源及USB恢复通过。本轮未刷机。
- **实机与SuperWatch**：docs/verification/v030-release-prep-20261007.md：4471 Python通过/2跳过、902 GUI通过，生产构建通过。V4 3bc7ef7 SES与布局通过、37原生及USB恢复通过；Keil下载校验、RTT8+Watch运行/暂停/单步/恢复/退出通过，初始化后模式校验与传输丢弃为0。无DAP30秒271576.69/s、最大相邻73us、无>1ms。OpenOCD1MHz并行4区域1ms约225~236/s，下载校验与恢复通过，不保证设定频率。安装态和本地Skill待补验；保留其他功能矩阵的实体边界。

## 架构决策

- 应用开发从MicroKeen/main建codex分支，经PR、CI整合；发布及合并需明确授权，标签/资产不可覆盖。
- 0.3保留CDC：USB序列号绑定后台及MSC，本机别名不写固件；多设备不选第一台，丢失身份拒绝新操作，不重放。GUI/MCP和已迁移CLI不再有--direct；Python脚本新增共享SDK，低层Device仍供后台/专用工具使用。后台协议49，内嵌远程服务已接入共享会话，仅允许绑定物理探针后台。 工程上下文固定于后台生命周期；删除旧PUT热切换入口，换工程须显式停止该探针后台再启动。 发现统一被动MI_04枚举，删除discover/自动连接全局锁/失败遍历与保存COM；底层自动连接也只接受唯一候选。 CDC和MSC共用probes不可变进程绑定，Bridge开口前后校验，lobby拒绝CDC/MSC/目标访问，允许独立UART会话；不是原子句柄身份认证。
- 应用MicroKeen/release主索引，旧GitHub/updates与Gitee/updates兼容；探针固件独立firmware索引。V2 RBL仅附件。
- V3 main bdd18d7、V4 main ed73ae9已通过CI并合并推送；本地已切main。Arm-2D/MicroBoot等子模块保持原状。
- 正式包、唯一备份、验收证据和依赖缓存保留；本轮清理20项约1.68GiB，48个含链接临时目录留待人工检查。mklink-issues-pr自动任务维持暂停。
- 2026-10-08用户明确授权正式0.3.0发布、版本说明精简及V3/V4推送main；固件已经CI/PR整合，主机仍须精确提交发布门槛。
- 用户最新已提供最终V3.6.0/V4.6.0/HPMLink V4.6.0 UF2并明确授权一起发布，取代此前暂缓指示。文件由用户编译提供，不得将先前HIL候选的哈希或性能结果称为最终二进制重新实测。

## 真机环境

- **state**：V4/HPM5301共存与无DAP性能已短测；V3/STM32完成stage95短测后拔出。V4最终固件136525 samples/s、最大84us、无毫秒间隔；V3 269477 samples/s、最大79us。不能外推所有组合或长期。
- **installer**：当前本地安装及Skill为04c9241d开发包；正式0.3.0待合并后重新签名构建并覆盖验证。
- **backups**：原始实机证据、发布包与清理清单保留在本地.build。

## 下一动作

1. 完成主机完整回归、生产构建和PR30 CI，按明确授权合并main；只从干净且与远程一致的main重新构建正式签名NSIS。
2. 验收安装态Web/桌面、冻结MCP及本地Skill，准备七项发布文件，三端上传下载哈希验证后最后更新索引。
3. 保持SES已知限制、跨物理主机及全芯片组合未验证边界；不得将发布授权写成所有验收通过。网站来财交接沿用现有任务，长期目标暂停。

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
