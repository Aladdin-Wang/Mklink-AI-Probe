# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-15T15:16:27+08:00`
- 分支：`codex/0.3.5-fixes`
- HEAD：`本次在49b7afb1之后修复拔掉旧下载器再换设备时自动连接失败；精确提交以Git为准。已安装NSIS仍为bdd3c3e3、Web/Skill仍为53b4ebb2，不含本次源码修复。`
- 远端 HEAD：`microkeen/codex/0.3.5-fixes；PR43草稿：https://github.com/MicroKeen/Mklink-AI-Probe/pull/43。新会话以 fetch 后实际远端为准。`
- 工作树：继续现有 E:/software/HPM5300/mklink-0.3.5-fixes/Mklink-AI-Probe（Git根为其父目录），分支 codex/0.3.5-fixes。原 E:/software/HPM5300/Mklink-AI-Probe 仍是 0.3.4 工作树，不在原目录继续修改或重建分支。
- 当前任务：修复未点断开直接拔掉旧下载器、换另一只后自动搜索仍被旧身份绑定拦截的问题。仅显式Connect且旧绑定missing时重新唯一选择，复用安全切换/清理/占用保护，选择在生命周期锁内执行。332 Python、89 GUI及用户配合实际拔插的Chrome/源码后台验证通过；详见docs/verification/v035-auto-connect.md。修复提交到现有0.3.5分支/PR43，未重新打包或安装；当前桌面和全局Skill不含本次修复。原安装版窗口保持打开但已断开，测试源码后台和浏览器已退出。
- 状态：`verified`

## 里程碑

- **0.3.5 时钟、符号、Pack/SVD及拔插自动连接修复** — `complete`。0.3.5本机NSIS覆盖安装及全局Skill更新完成；代码含时钟、位域、普通System搜索及Pack/SVD修复，用户待复测。PR43草稿，未合并或正式发布。 源码修复及用户配合物理拔插验证完成；332 Python、89 GUI通过。仅显式Connect在旧身份消失时选择唯一新设备，保持所有权和旧会话隔离。待后续打包安装，见v035-auto-connect.md。
- **0.3.4正式版** — `complete`。不可变源a8fd3fab0403，PR40正式发布；PR41已保存正式Web/交接，合并提交185678c59623。17附件、5份验签、3渠道及实装/Skill通过。07846c1a记录后续清理完成，本次补入0.3.5；见v034-release-handoff.md及v034-workspace-cleanup.md。
- **0.3.3正式版** — `complete`。源11616f80，PR38；Windows/ARM/Linux/Intel包、五份签名、三渠道核对和本地Skill更新完成。正式归档已回原工作空间；见v033-release-handoff.md。
- **0.3.2正式版** — `complete`。源3d511e94，PR35/36；三平台原生构建38028928283。Windows实装、五份更新验签、三个渠道已核对，见v032-release-handoff.md。
- **0.3.1正式版** — `complete`。PR33合并，源1d61159d；签名NSIS/Skill/SiteAgent与三端索引完成，最终提取包检查通过。见v031-release-handoff.md。
- **0.3.0及2026-10-09固件归档** — `complete`。0.3.0发布及2026-10-09固件记录见历史交接和固件归档；不继承其硬件验收结论。

## 验证证据

- **0.3.5 拔插自动连接**：修复前7个新增用例失败；修复后身份/切换/重连93、共享runtime/API/枚举/任务/安全239 Python通过，GUI89通过。用户真实拔掉旧下载器换另一只；Chrome直接点击连接、不选端口成功，后台PID/端口不变，generation1→2。第二只目标ID0x0只证下载器连接。测试后断开并退出源码后台，安装版仍打开且断开。无供电/烧录/固件变更，无新包或Skill更新；详见docs/verification/v035-auto-connect.md。
- **0.3.5 本机测试包与覆盖安装**：bdd3c3e3版本和NSIS，53b4ebb2 Web/Skill；949GUI、26版本/启动/更新器通过。NSIS退出0，登记0.3.5，四载荷哈希一致；195Python/38Web与源一致；Windows-only PATH冻结CLI/SVD/MCP/HTTP、原生WebView及Edge通过，版本说明和手动SVD可见。正常关闭进程/endpoint/8765释放。全局Skill0.3.5、2600文件一致及CLI/MCP通过，旧Skill备份。无新硬件操作，未签名/合并/发布，详见docs/verification/v035-local-install.md。 交接前75cc3106的shared-runtime-contract、shared-gui-contract、feedback-contract均成功；新文档提交的CI须按新HEAD另查。
- **0.3.5 Pack外设同步与手动SVD**：d5a65482：非空SVD索引随Pack状态/索引/工程配置变化刷新；聚焦重查/显式刷新；浏览器SVD校验持久化、桌面本地路径。138Python、33GUI、生产构建通过；真实Edge+HTTP在线导入后原查询找到型号、手动文件选择显示12项、错误XML保留当前配置、重载恢复均通过。离线夹具不访问硬件；该专项当时未实装；后续已随0.3.5完成桌面覆盖安装和全局Skill更新，详见docs/verification/v035-peripheral-import.md。
- **0.3.5 位域解析和整变量曲线**：62faad0e：客户ELF815→872标量叶，gSystemState6成员256模式1536比较通过，System23成员。旧MSB offset与data_bit_offset分离、显式存储宽度、cache6、位域只读、搜索generation刷新。450项Python通过，后加2个文本解析用例所在15项通过，共452覆盖；53GUI、TS/生产构建通过。V3/F103原工程Keil编译/烧录验证通过；15路一个8字节块、30MHz，1ms12343/50us245540/50us272200浏览器行全部一致、各256状态、signed -16..15；最后序号含元数据0缺口，读/CRC/固件/队列丢弃0、真实位域曲线通过。所有会话释放，测试固件保留；未改下载器固件/供电。见docs/verification/v035-dwarf-bitfields.md；该专项当时未打包，后续已随0.3.5覆盖安装并更新Skill。 旧/新生产GUI对照确认手动重解析未刷新不变查询的独立bug；旧2叶、新29叶，后台均System23，已补普通根回归。
- **0.3.5 SuperWatch环境时钟差异**：默认时钟与注入时钟、正负34.8秒偏差、无batch_time、1秒边界和64批队列回归；Python3.11.16 152通过，Python3.14.5 392通过。V3/F103单float、30MHz、每组约10秒：1us 261664/259304Hz，50us 21685/21676Hz；四组浏览器与后台丢弃0。详见docs/verification/v035-superwatch-clock.md。 另107项分发/runtime/MCP通过、1项可选hil_core跳过；GUI206通过。195源码/38Web资源及冻结方法字节码一致。Skill/冻结MCP各测1us/50us零缺口丢弃；Windows-only PATH原生WebView35秒9230741读零错误/丢弃，关闭窗口后台正常退出。首次UAC取消，用户要求重试后NSIS退出0；4安装载荷哈希一致，已安装MCP/真实Edge两组约262k/20k零缺口丢弃，原生窗口和后台正常退出。运行代码75a73a5a三个PR CI通过；最终文档头需另核对CI。
- **0.3.4 正式发布与本地升级**：最终源a8fd3fab0403；正式NSIS176582092字节，实装载荷哈希匹配；冻结CLI/MCP/38 Web文件/原生窗口及退出通过。F103双探针固定后台、采集中24写应答、5766周期零读错误通过；SystemView54字节仅证生命周期。三平台native CI38144587775、五份签名实际验签、17附件匿名下载及三渠道索引、本地Skill逐文件/CLI/MCP通过。见v034-release-handoff.md，早期准备与体积审计证据仍保留原报告。
- **0.3.4 共享架构修复（已合并历史证据）**：采集启动、窗口固定后台、变量写入仅认应答、明确断开自动收尾已随0.3.4发布；详情与各轮测试数字分别保留docs/verification/v034-rtt-startup.md、v034-window-owned-backend.md、v034-superwatch-write.md、v034-explicit-connection-control.md。旧按探针跳转后台方案已被固定窗口后台方案取代。最终正式版本实装双探针切换/共享断开通过，SystemView54字节0事件只证生命周期；异步烧录中断场景使用夹具，未中断实物烧录。
- **0.3.4 清理交接补入0.3.5**：源07846c1a原工作树交接此前未进入0.3.5，本次按文档合并，不合并产品代码。其清理记录：删除5个已合并旧分支、615路径约3.64GB；17正式载荷哈希核对及70项文档/边界检查通过。151个含联接run及旧安装器占用内容留人工处理，不重做删除。报告docs/verification/v034-workspace-cleanup.md及正式发布报告PR41完成状态已补入；历史测试数字不冒作本轮执行。 本轮memory及Skill边界59项通过；构建入口保留1个含测试联接的临时run，未强删。

## 架构决策

- 当前维护入口是现有codex/0.3.5-fixes工作树及PR43；旧0.3.4交接的回原目录/保留旧分支要求是历史状态。继续既有任务分支，经PR/检查整合；合并、签名、发布需明确授权，既有标签/资产/更新公钥/应用ID不覆盖。07846c1a的文档内容已吸收，不需要再次cherry-pick覆盖当前记忆。
- 后台协议 52：一个 GUI 客户端持有一个固定后台，同窗口切换只改下载器，RTT/Watch/Trace 跟随当前设备并清空旧目标状态；另开客户端才建独立后台。已有 URL 的额外页面共享该后台。工程上下文固定，换工程须停止原后台后重开。
- 物理探针唯一 OS 所有权、USB 身份核对和 epoch 隔离保留。GUI/AI 明确断开或切换自动停止采集、排空在途操作并释放端口；旧会话不得跨设备，未知结果不得自动重放，不偷取其他后台占用。MCP disconnect 物理断开，detach 仅退出自身；独立 UART 保留。
- SuperWatch 变量写入只认写应答，不做自动回读；烧录/显式内存校验仍保留，真实写错误不得吞掉或重放。外设 ID 基于 Pack 版本/芯片/SVD 相对路径；失效选择不得阻断物理连接，无法迁移时重选。
- 应用主索引 MicroKeen/release，旧 GitHub/updates 和 Gitee/updates 兼容，固件使用独立索引。Gitee 仅要求 Windows 与 Skill；本次 Windows 超 100MB 被拒，索引指向 GitHub；Skill 已真实镜像，GitHub 不可达回退实测通过。其他平台仅 GitHub。
- 测试直接使用用户原工程及 build/keil/Obj ELF，允许修改且无需备份还原，不复制工程；硬件路径只留本地。HPM 使用 ROM API，不使用 FLM/第二次通用 SWD reset；VCC 每次改动需确认具体电压，固件修改另开会话。
- 构建使用scripts/build_workspace.ps1与F:/MKLink-Build，保留正式包、独有证据、依赖和缓存；联接或不可访问路径不强删。0.3.4清理已完成，不能沿用早期startup-cdc待删除任务。长期硬件跟进仍暂停，不因交接自动接管硬件或重复发布。
- 工程上下文固定于后台生命周期；被动MI_04枚举不遍历占用设备，底层自动连接只接受唯一候选；本机别名不写固件。未知结果不重放，worker实际退出后才发布串口关闭，取消前保留缓冲寿命，背压错误不隐瞒。
- 原MK-Firmware及固件工程保留既有最新归档与用户子模块改动，旧用户固件/stash仅备份用途不自动恢复；历史发布授权已完成，不延伸为0.3.5发布授权。

## 真机环境

- **state**：本轮用户授权连接/断开并配合物理换下载器，Chrome+源码后台自动连接第二只通过；第二只目标ID0x0，不当作目标调试验证。测试后已断开、测试浏览器及源码后台退出；原安装版窗口仍在且断开。未改供电、目标程序或下载器固件。此前V3/F103位域与时钟验证见原专项报告；后续接硬件前重新核实当前状态。
- **installer**：用户明确授权后已实际覆盖安装0.3.5本机测试NSIS，源bdd3c3e3、生产Web53b4ebb2。退出0，四载荷哈希一致；冻结195Python/38Web一致，Windows-only PATH原生/HTTP/MCP及正常退出通过。全局Skill也实际更新0.3.5、2600文件一致、CLI/MCP通过；备份在构建根artifacts/v035-local-bdd3c3e3/skill-backups。用户待复测，未正式发布。 本次拔插自动连接修复尚未重新打包/安装或更新全局Skill。
- **backups**：0.3.4正式包/安装/渠道/Skill/HIL在MKLINK_BUILD_ROOT/artifacts/v034-official，相邻v034-official-native保存完整原生CI ZIP；0.3.5本机包见上述构建根。原Git根.build/artifacts/v033-official、v032-official及用户备份保持；清理前快照/删除清单在构建根reports/v034-cleanup-*.json、v034-deleted-branches.json、v034-memory-before-cleanup.json。不能再把F盘仅视为可删缓存。

## 下一动作

1. 继续现有0.3.5工作树及PR43处理用户反馈；拔插自动连接修复已完成源码与实物验证，当前桌面/全局Skill尚未包含。后续打包安装时纳入该修复并验证安装态。此前时钟、System/位域、Pack/SVD继续收集用户/客户复测反馈。正式合并、签名、发布需授权。
2. 收集两位 RTT 客户的上位机/下载器固件版本、目标 ELF/芯片及 IDE 占用，用启动阶段耗时和 MUX 请求身份复核。历史 unknown 操作不得重放；原始 CDC/F405/受限 AI/GD32 仍待现场闭环。
3. 继续排查 30MHz 并行目标读错/Flash 偶发 status5，区分固件目标访问与主机队列；本次低负载 F103 结果不关闭该限制，需要固件改动另开会话。
4. Gitee单附件限制已确认100MB：0.3.4 Skill已真实镜像并验证GitHub不可达回退，Windows176.6MB被拒并使用GitHub链接；后续发布必须维持Gitee Skill可下载，其他平台不上传Gitee。历史清理已完成，151个含联接run/旧安装器占用内容仍留人工处理，见v034-workspace-cleanup.md；本次不重新清理。
5. 收集 Mac/Linux USB/MSC 和原地升级反馈、外置 Flash 多算法实物验证；完整 SES/芯片/拔插断电组合仍待补充。供电每次确认具体电压，长期验证仍暂停。

## 已知限制

- 0.3.5时钟修复已通过偏差注入及本地Windows3.11/3.14实机短测；客户3.11.9原电脑仍待升级确认。原始CDC首次离线/F405 PROGRAM100%后退出、受限AI/GD32及RTT客户后续MUX超时仍未闭环；不宣称同一根因或任意负载无损。历史unknown操作不得重放。 位域当前仅little-endian、只读；曲线Float32对大整数有舍入。真实ELF只离线回放，F103使用专门测试固件；未把客户固件烧到该板。 原0.3.2故障链见docs/verification/v032-postrelease-incidents.md；CDC传输错误、目标status5与本次DLL解压拒绝不混为同一根因，不靠清空用户配置或全杀后台掩盖原因。
- V4.6.8 30MHz RTT8/Watch4/UART并行目标读错1kHz +1、最大+273；10MHz0。旧V4.6.6原始+1/+224，报告此前漏记已更正。采集不停止、不误断、UART完整；用户明确继续发布，限制交接下版处理，不写公开发布说明。
- HPM/SES退出未发送DAP_Disconnect时可遗留占用，后续legacy握手等待；明确退出后正常OpenOCD init/resume/shutdown可恢复，用户可重插USB。禁止任意超时偷取调试所有权。完整SES矩阵和RTT下行未全部覆盖；V3.6.4/V4.6.8仿真中新启采集及负载读回通过，V4.6.8已完成Keil及相关矩阵。详见release handoff；长期目标暂停。
- 性能和功能证据按docs/verification/v030-release-handoff.md及各精确提交报告解释：采集不是无损通道，缓冲溢出/暂停/调试下载可能丢失观测；多变量不是原子快照，不能保证任意时序上界。
- V3无屏幕、不支持HPM；V3.6.4原生Keil先运行再采集、暂停/单步/继续/退出和OpenOCD均通过。V4最终无诊断固件完整SES矩阵未完成。
- 后台最后会话释放约5秒租约，加排空和退出开销；不保证硬实时5秒。每个GUI客户端一个后台，同窗口切换固定PID/端口；一个物理探针在任一时刻仅由一个后台独占。打开已有URL的额外页面共享当前后台并跟随明确切换；独立操作应启动新客户端。
- 长期验证按用户要求暂停；跨物理主机Agent、Mac/Linux、真实Modbus从站及全部芯片组合未完整认证。模拟测试不得替代实体边界。 历史Mac仅ad-hoc、无Developer ID公证，Windows无Authenticode；0.3.5未构建独立Site Agent或跨平台正式包，仅同步Site Agent源码版本元数据。
- nRF54L15 GUI保护闭环、全部物理擦除/拔插/休眠/断电场景、电源外部精度校准未全部认证。VCC每次改动必须确认具体电压，HPM已锁定OTP不得重放。 已知无可靠扇区表的26个FLM禁用扇区操作；重叠算法需要匹配Bank模式。 HPM5301组18/19永久锁定的历史状态及用户字先写/组锁最后、全部固件独立校验后才写OTP等边界见docs/ai/hpm-offline-otp-handoff.md；接手重新确认芯片，其他型号不继承验收。

## 延续协议

- 新会话固定继续 E:/software/HPM5300/mklink-0.3.5-fixes/Mklink-AI-Probe 的 codex/0.3.5-fixes；读取该目录AGENTS.md和本交接，运行 python scripts/ai_memory.py validate，核对 git status、log、worktree及远端。不要从原0.3.4目录另起修复分支。
- 区分源码与安装态：桌面 D:/Program Files/Mklink AI Probe；全局Skill C:/Users/akqbd/.codex/skills/mklink-ai-probe；本机测试包、哈希、安装证据及旧Skill备份在 F:/MKLink-Build/artifacts/v035-local-bdd3c3e3。版本0.3.5，Web build bdd3c3e3ef32；后续文档提交不会更新已安装二进制。 本次源码自动连接修复未装入桌面/Skill；源码浏览器实测通过不能当作安装态验收。
- 合并来源：原0.3.4工作树07846c1a的CURRENT_HANDOFF/project-memory与v034-workspace-cleanup；历史v030/v031/v032/v033/v034-release-handoff、v032-archive-handoff和hpm-offline-otp-handoff已核对。其已完成发布/清理和当时安装/连接状态仅属历史；当前以本文件0.3.5断点为准。专项修复见docs/verification/v035-superwatch-clock.md、v035-dwarf-bitfields.md、v035-peripheral-import.md，安装见v035-local-install.md。
- 客户启动故障仅确认PyInstaller解压ucrtbase.dll时Permission denied，重启后恢复；未定位权限/杀软/占用的具体来源，按用户意见暂不做推测性修复。若再现，结合新startup/runtime日志复查。
- 仅继续修复和验证；PR43仍为草稿，未授权合并或正式发布。遵循AGENTS提交推送任务分支、更新memory并render/validate；详细历史保留docs/verification，敏感日志/硬件标识及本机产物不提交。
