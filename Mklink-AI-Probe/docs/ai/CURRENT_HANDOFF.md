# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-10T10:03:45+08:00`
- 分支：`codex/0.3.2-fixes`
- HEAD：`Based on microkeen/main 078663fe; inspect Git for current 0.3.2 fix head.`
- 远端 HEAD：`microkeen/main 078663fe; task changes pushed only to codex/0.3.2-fixes.`
- 工作树：Isolated desktop-platforms worktree; original main checkout and released artifacts preserved.
- 当前任务：0.3.2最终回归与发布归档。b06心跳修复完整Python4647通过、2跳过，三平台原生候选哈希/冻结检查通过；Windows新候选构建中。V3.6.3/V4.6.7仍待刷测，不继承旧哈希HIL。用户已授权验收后合并主分支正式发布并清理修复空间；Mac/Linux真机与Windows人工UAC项豁免。正式包、交接、必要证据必须回原工作空间。
- 状态：`in_progress`

## 里程碑

- **0.3.1正式版** — `complete`。PR33合并，源1d61159d；签名NSIS/Skill/SiteAgent与三端索引完成，最终提取包检查通过。见v031-release-handoff.md。
- **0.3.0正式版** — `complete`。签名NSIS、Skill、远程服务包及三端更新索引发布完成；精确源提交ec1d2834。安装/退出、CLI/MCP通过，Web由用户确认。
- **2026-10-09固件** — `complete`。用户指定MicroLink V4.6.3 SHA e960cb70，1625600B，三端下载及独立索引核对；与旧605验收UF2不同，不继承旧HIL。其他型号未变。

## 验证证据

- **0.3.2 V3.6.2补验与首发失败**：见v032-v3-final-candidate.md。86冻结+V3.6.2实际GUI升级、30MHz两档时间戳、RTT8/Watch4/UART、脱机/共享/失败/停止恢复通过。在线后回读首发Serial worker write failed；两轮显式10MHz重测512KiB一致，88源码原路径复测亦一致。随后无close空闲82秒会话过期，修复SDK临时心跳失败有界重试，109专项通过；完整Python重新运行。363/467新固件待刷测，Keil/OpenOCD/退出矩阵待完成，不以V4旧通过替代。 b06全量Python最终4647通过、2跳过、60已有警告，682.98秒；磁盘耗尽的旧运行不计通过。原生构建38013387325三平台成功且载荷哈希核验通过。
- **0.3.2最终候选与既有修复回归**：见v032-final-candidate.md。86cfdff4冻结候选实际GUI升级V4.6.6；30MHz Flash128B在1kHz/请求1µs两档完整性指标均0，最大样本间隔1049/233µs；RTT8/Watch4/UART并行、文件检查、在线/脱机/共享烧录成功/失败/停止恢复、Keil下载断点单步退出及OpenOCD、GUI退出AI接续、旧端点重发现、最后6.299秒释放通过；512KiB逐字不变，未改VCC。真实收发毫秒/RX/TX、独立RTT拖动及20/30MHz保存通过。旧155次status5不冒作新固件故障注入证据。914 GUI/生产构建通过；原生3e39e1ef构建37949511991全部成功；完整Python/Rust和交付状态以发布准备报告为准。 全量Python4634通过/2跳过，Rust21+6通过；三平台下载CRC和载荷SHA256均核验，当前候选可交客户复测。
- **0.3.2冻结候选V4/Keil收敛**：详见v032-hardware-closure.md。e1eee01e frozen + UF2 2684d904：在线/脱机/共享及负向自动恢复、30MHz时间戳负载、RTT8/Watch4/UART、Keil下载断点单步、OpenOCD、Flash512KiB不变、旧端点重连和6.261秒释放。Keil期间155读错不误断，退出自动恢复；用户屏幕确认已连接。固件另有断线计时误判待修，新固件和最终自动升级仍未收敛。
- **0.3.1正式发布**：v031-release-handoff.md：main/tag 1d61159d，clean locked GUI912、签名NSIS与SiteAgent重建通过；冻结MCP/CLI、4.825秒lobby、36项Web字节一致、10.340秒原生窗口、无Python子进程及正常退出通过；UAC安装豁免。三端资产/应用及固件索引已核对。用户原GUI保留，本次不连接目标。
- **0.3.1 dumpmem队列修复和最终候选回归**：产品77d4849c/资源f586fd94：完整Python4576通过/2跳过686.57秒、GUI912、Rust桌面21/SiteAgent6、三项CI通过。安装旧版30MHz capture最大时间戳缺口84.113ms；新NSIS提取原生窗口三轮10万点最大98/89/82µs，measure5/15/30秒最大123/125/121µs，均主机丢弃0。SuperWatch单变量1kHz/单变量最大/三变量最大各20秒最大采样1046/127/129µs，最大批次105.169/73.280/56.691ms，队列/WS丢弃0。冻结MCP/CLI、原生启动、GUI退出AI读和最后释放通过；原生安装UAC豁免。NSIS/Skill/SiteAgent同源候选哈希见manifest，详细证据v031-dump-queue.md。未证明30MHz Flash连续读取status5修复，未重做所有旧烧录/串口/升级矩阵。
- **0.3.1原生桌面选文件并发修复**：v031-desktop-image-inspection.md：安装旧候选复现本地检查并发409；源码acdcc997、资源d89c0827修复两条本地检查独立硬件锁和前端取消请求竞态。192 Python/118 GUI、生产NSIS构建及三项CI通过，冻结MCP/CLI/5.44秒启动通过。新包提取原生桌面：Watch、RTT8、两者并行三种状态12次并发文件检查全200，实际文件对话框选HEX并点击烧录10.73秒成功，RTT8/Watch1自动暂停恢复且数据增长。10MHz读回512KiB与备份一致，30MHz原连接大块读偶发status5尚未归因；低频通过不代表30MHz修复。VCC未变、时钟未保存。正常退出后进程/endpoint消失、命令口可开关。新NSIS SHA5f2858333155e541a40c850fec97e0e05e27c33638d05337880983b13f975780，实际覆盖因740未完成，安装目录仍旧候选。证据.build/artifacts/v031-inspection-fix。 用户后续已实际覆盖安装，三负载哈希一致；30MHz专项见v031-installed-30mhz.md，原先等待安装状态已解除。
- **0.3.1发布准备及最终可用硬件验收**：见v031-release-preparation.md、v031-hardware-acceptance.md。完整Python4566通过/2跳过640.25秒、GUI911、Rust桌面21/SiteAgent6，候选构建及403fad75三项CI通过。NSIS/Skill/SiteAgent哈希冻结，提取候选不等于覆盖安装，UAC人工项豁免。V4.6.2发现1kHz Watch饿死UART，固件修复并明确交接V4.6.3后重新核对UF2/AXF、备份原程序，RTT8+Watch4+UART在100Hz/1kHz/请求1µs三档各5次完整154B响应，读错误0。在线15.50秒/脱机20.75秒/共享27.03秒及失败/停止均恢复采集；OpenOCD halt/step/resume/shutdown、GUI退出AI接续、真实串口记录/队列/广播/文件、RAM RTT搜索通过。512KiB与新备份相同SHA40aab8a117e7db22dfeffd13a2a592ab596bdd28a66fcd4a26443d2e72548732。旧endpoint明确connect恢复同一探针，最后6.018秒退出释放端口。真实原生提取程序冷启动6.006秒、退出不影响AI。VCC未改。现有硬件范围完成；旧型号升级、外部RS485及覆盖安装未实测，不冒称通过。
- **0.3.1下载、控制权和界面**：下载源码7b9c87a8/资源b91acb92：Python扩大818、最终相关75通过；GUI最终相关150、TypeScript和生产构建通过，真实浏览器模拟API验证拒绝清凭据及完成自动解锁。控制权/Skill源码7e46aabe：最终364项Python/文档回归及Skill quick_validate通过，含真实无硬件后台进程经新管理入口退出/释放实例锁。修复GUI所有权遗留，新增不依赖connect的诊断/定向管理。见v031-download-acquisition.md、v031-runtime-recovery.md。本批未构建NSIS/覆盖Skill或客户电脑实机验证。 固件升级6d2fc0fa：311 Python、54 GUI、57文档通过，自动同身份UF2与无指令手动回退；串口折叠0e6047ac：24 GUI通过；两批TypeScript/生产构建与真实浏览器模拟API通过，草稿折叠保留。报告v031-firmware-update-ui.md、v031-serial-extensions.md。均未打包安装或刷实机。

## 架构决策

- 应用开发从MicroKeen/main建codex分支，经PR、CI整合；发布及合并需明确授权，标签/资产不可覆盖。
- 0.3保留CDC：USB序列号绑定后台及MSC，本机别名不写固件；多设备不选第一台，丢失身份拒绝新操作，不重放。GUI/MCP和已迁移CLI不再有--direct；Python脚本新增共享SDK，低层Device仍供后台/专用工具使用。后台协议50，内嵌远程服务已接入共享会话，仅允许绑定物理探针后台。 工程上下文固定于后台生命周期；删除旧PUT热切换入口，换工程须显式停止该探针后台再启动。 发现统一被动MI_04枚举，删除discover/自动连接全局锁/失败遍历与保存COM；底层自动连接也只接受唯一候选。 CDC和MSC共用probes不可变进程绑定，Bridge开口前后校验，lobby拒绝CDC/MSC/目标访问，允许独立UART会话；不是原子句柄身份认证。
- 应用MicroKeen/release主索引，旧GitHub/updates与Gitee/updates兼容；探针固件独立firmware索引。V2 RBL仅附件。
- V3 main bdd18d7、V4 main ed73ae9已通过CI并合并推送；本地已切main。Arm-2D/MicroBoot等子模块保持原状。
- 正式包、唯一备份、验收证据和依赖缓存保留；本轮清理20项约1.68GiB，48个含链接临时目录留待人工检查。mklink-issues-pr自动任务维持暂停。
- 2026-10-08用户明确授权正式0.3.0发布、版本说明精简及V3/V4推送main；固件已经CI/PR整合，主机仍须精确提交发布门槛。
- 用户最新已提供最终V3.6.0/V4.6.0/HPMLink V4.6.0 UF2并明确授权一起发布，取代此前暂缓指示。文件由用户编译提供，不得将先前HIL候选的哈希或性能结果称为最终二进制重新实测。
- 2026-10-10用户授权本轮验收完成后合并主分支、正式发布0.3.2；Mac/Linux实际安装USB/MSC及原地升级由客户后验，不再阻塞发布，Windows人工UAC项豁免。随后清理新建修复工作空间，保留用户改动。正式包/交接/必要证据回归原工作空间；F:/MKLink-Build仅临时构建。详见v032-archive-handoff.md。

## 真机环境

- **state**：本会话独占V3，当前V3.6.2；全部旧测试进程已正常退出，硬件未交给其他会话。VCC未改，512KiB多次保全。363/467候选UF2哈希已核对尚未刷入；新包/新固件和原失败收敛后再发布。
- **installer**：Windows86cfdff4 NSIS SHA256 c3463d7ad42c426f82efce986dbf3b7f413fd91b3707176019e26a28cfadce15，提取冻结后台和生产Web实测，不是覆盖安装；UAC人工项用户豁免。三平台3e39e1ef与Windows产品代码相同但打包提交不同，正式同源要求仍需整合后重建；候选未签名更新/未公证，不声称实装升级通过。
- **backups**：原工作空间Git根.build/artifacts保留既有完整HIL与目标备份；v032-handoff为统一阶段归档入口，最终v032-official保存正式包和清单。新增构建暂在F:/MKLink-Build，删除前须回原目录逐项SHA核验。固件原MicroLinkV3、MicroLink_Plus各有根CURRENT_HANDOFF.md及firmware-releases归档。

## 下一动作

1. Windows b06新候选完成后冻结并检查CLI/MCP/Web；产品完整Python已通过。
2. 实际GUI升级V3.6.3，补测原在线并行回读/时钟恢复、长空闲续租、Keil/OpenOCD/GUI退出AI接续及最后端口释放。
3. V3完成后请求换V4，验证V4.6.7。Mac/Linux实机及原地升级由客户后验，明确记录豁免而非通过。
4. 硬件及实际失败收敛后按用户授权合并、统一源构建签名、发布三平台/Skill/SiteAgent并核对渠道。
5. 按v032-archive-handoff.md归档正式包、证据与统一交接到原工作空间，逐项哈希核验，保全用户文件后再清理修复空间。

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
