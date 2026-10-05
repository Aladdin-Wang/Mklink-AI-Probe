# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-05T14:50:08.7586353+00:00`
- 分支：`codex/v0.3.0-shared-runtime`
- HEAD：`Based on main d4e73bd; shared CDC development continues; long-duration validation deferred at user request. Use Git for exact tip.`
- 远端 HEAD：`Application release v0.2.3 fixed at b0e0f61; verify current main with Git.`
- 工作树：Existing isolated host task worktree; firmware has its own codex/v4-multiplex-runtime branch and draft PR1. SDK and submodules unchanged by this task.
- 当前任务：固件f74af2a已升级HPM探针：修复同名文件覆盖时FatFs旧缓存，HPM BIN/HEX文件事务与MSC写双向互斥。五项C harness、SES/SWD布局及最终真机边界通过：校验错、容量越界、奇数长度同扇区稀疏、未覆盖4KiB保留、BIN恢复。公共HEX入口仍待接入，完整审计目标活跃。
- 状态：`active`

## 里程碑

- **0.3.0 专用CLI共享迁移** — `development`。每探针共享后台、GUI在线持久提交与双V4真实终态恢复已短测；旧MCP启动入口删除，注册器/测试迁移仍待收敛。按用户要求进入最后收尾，之后暂停；长期验证继续暂停。
- **0.2.3正式版** — `complete`。三个发布渠道及更新索引通过；本地安装版和Skill为b0e0f61。
- **2026-10-03固件** — `complete`。HPMLink/MicroLink V4.5.2、MicroLink V3.5.2、V2.8.1已三端发布；V2为RBL附件，不进入UF2自动更新索引。

## 验证证据

- **CDC多路复用主机接入**：docs/verification/cdc-multiplex-host.md：1362后端通过/2跳过，最终Bridge补测69通过；GUI整套851通过、最终相关52通过，生产构建及真实Edge/stdio MCP短测通过。双RTT+Watch+内存读写校验恢复、CLI多通道采集、会话恢复通过。全仓离线安全算法资源及联网wheel测试未通过/未完成。 Skill旧通道上限断言已修正，反馈契约66项通过。 MUX及RTT GUI回归已加入现有CI测试清单。 见cdc-multiplex-host.md安装补验：f17e4047三项CI通过，本地NSIS安装退出0，三负载哈希匹配；sidecar与Skill算法7059/2224验证。安装版Web双RTT+Watch+本地Skill stdio MCP通过，正常关闭6.16秒释放COM；原生桌面及CLI双通道共存、正常退出通过。 RTT多面板与0.3.0记录：54项相关GUI通过，真实浏览器收起保留及双通道+Watch+MCP通过。 b21d071c多面板安装/Skill覆盖、原生版本弹窗与安装态共存补验通过，5.75秒退出。 各通道平等版474ef405：188后端/65GUI、三项CI通过，安装与本地Skill覆盖、真实Web双通道/Watch/MCP/CLI、6.03秒退出释放COM及原生版本说明通过。
- **149固件与后台空闲退出**：docs/verification/runtime-idle-mux-149.md：最终安装版GUI退出6.05秒、AI强杀5.40秒释放COM；真实双网页退出通过，网络排空上限回归4项通过，5508bd06三项CI及固件4ab77c2两项CI通过。
- **统一远程GUI**：148：应用06494629安装及Skill同步，三项包内负载哈希一致；109后端、247GUI通过，测试修正ff0c5b4c三项CI通过。源码RTT及安装版Memory/符号/SuperWatch、断线禁用并保留快照、桌面代理读取与管理拒绝通过；仅同机LAN短测。
- **远程GUI第一阶段**：147源码cd32f7e6：99后端+20GUI测试、生产构建、三个CI通过；同主机LAN真实F103内存读取/暂停运行/寄存器/RTT、双远程会话/AI共存及断线禁用通过。跨物理主机、内存写入、RTT发送、单步和新版安装仍待验收。 用户重新授权后安装及代理/包内Web短测已补验通过，详见147安装补验。
- **共享后台、多探针与AI共存**：144相关回归539通过/1跳过；1aca5414三项CI通过。145安装版单V4桌面/Web/Skill三客户端共存、正常退出隔离、健康检查通过；双探针证据仍为142源码短测。
- **正式版与安装**：145本地0.3.0开发版NSIS覆盖安装返回0；主程序/sidecar/STCP与NSIS负载哈希一致；Skill版本/前端/7059目标2224blob验证。旧0.2.3正式版证据保留原报告。
- **固件发布与代码同步**：docs/verification/firmware-20261003.md；UF2格式、RBL CRC/版本、三端下载哈希和索引通过；V2/V3 AP模型、V3电源及USB恢复通过。本轮未刷机。
- **实机与SuperWatch**：按需查docs/verification/v0.2.3-integration-20261002.md、v0.2.3-installed-f103-20261002.md；界面证据见superwatch-drag-groups-20261003.md、superwatch-inline-names-20261002.md。历史报告保留，不在交接重复流水账。

## 架构决策

- 应用开发从MicroKeen/main建codex分支，经PR、CI整合；发布及合并需明确授权，标签/资产不可覆盖。
- 0.3保留CDC：USB序列号绑定后台及MSC，本机别名不写固件；多设备不选第一台，丢失身份拒绝新操作，不重放。GUI/MCP和已迁移CLI不再有--direct；Python脚本新增共享SDK，低层Device仍供后台/专用工具使用。后台协议48，内嵌远程服务已接入共享会话，仅允许绑定物理探针后台。 工程上下文固定于后台生命周期；删除旧PUT热切换入口，换工程须显式停止该探针后台再启动。 发现统一被动MI_04枚举，删除discover/自动连接全局锁/失败遍历与保存COM；底层自动连接也只接受唯一候选。 CDC和MSC共用probes不可变进程绑定，Bridge开口前后校验，lobby拒绝CDC/MSC/目标访问，允许独立UART会话；不是原子句柄身份认证。
- 应用MicroKeen/release主索引，旧GitHub/updates与Gitee/updates兼容；探针固件独立firmware索引。V2 RBL仅附件。
- V4代码MicroLink_Plus/main=4bf704a；V3 MicroLinkV3/main=6a39d28；V2 MicroLinkV2/main=d32c56f，均已同步GitHub。Arm-2D/MicroBoot禁止随本任务修改、提交或上传。
- 正式包、唯一备份、验收证据和依赖缓存保留；本轮清理20项约1.68GiB，48个含链接临时目录留待人工检查。mklink-issues-pr自动任务维持暂停。

## 真机环境

- **state**：单V4/STM32，已写MUX_FRAME=1/MUX_TARGET=1固件58c47a9；双RTT通道/Watch/内存并行及重连短测通过。未烧录目标或改压/复位；测试预留RAM写入已恢复。HPM未接，长期暂停。
- **installer**：474ef405本地0.3.0 NSIS与Skill已安装；各通道能力一致，包内三负载哈希与7059目标/2224算法完整性通过，安装版Web与原生版本弹窗确认。
- **backups**：原始实机证据、发布包与清理清单保留在本地.build。

## 下一动作

1. 下一步接入主机在线/脱机prepare_hpm_hex并用独立hpm.program_hex，禁止旧固件把HEX当BIN；再GUI/CLI/MCP及技能。固件f74af2a的HPM文件事务保护仅覆盖HPM，其他文件消费者需审计；实际并发MSC拒绝尚未真机，只有生产回调编译测试。HPM已运行f74af2a，STM32保持ba0a1cf，端口已释放，HPM已恢复hello BIN。证据reports/hpm-hex-boundaries-hil.json。
2. 用户已明确恢复持续全功能架构审计与短时验证；只有长期稳定性/soak仍保持暂停。不能沿用历史144批暂停普通审计的状态。
3. 固件应用层升级已获授权，在独立分支验证；不修改SDK/Arm-2D/MicroBoot，不增加WinUSB。所有验证通过前不合并固件；主机PR不自动合并。
4. 含链接的测试临时目录保留；需清理时先核对实际目标，不强制删除或改ACL。

## 已知限制

- 新MUX主机协议47需配套V4 MUX_TARGET=1固件；实体只验STM32两个Up/一个Down。SuperWatch最多15个128B区域，最短2ms，非原子快照；调试/烧录/时钟仍需停流，未知写入不重放。配套桌面安装包及本地Skill已更新，全仓测试未完全通过。
- 149是MUX帧基础，尚无多通道目标调度。后台约5秒触发退出，安装版完整清理约5.4至6.05秒；异常网络排空额外最多2秒。GUI靠在线连接保活，AI每秒续约/5秒过期；未打开的远程窗口仍有90秒回收上限。长期和跨物理主机未验证。 A5已收敛。A6活动MCP已扩展只读目录检查，仍有旧能力待迁移。A7端口锁统一、旧锁兼容删除；共享后台/API/多探针/VOFA及GUI契约与构建已进入CI，准确数量看精确提交报告。bfcache生命周期已修，但本机no-store阻止原生缓存命中，仅完成单测、受控恢复事件及普通返回验证；原生命中需补验。 Python/原生标准输出已统一轮转，启动文件只记录初始化前诊断；NSIS与非Windows仍待验收。 第二十一批已修复真实TCP reset复现的二进制流订阅退出卡住，使用框架任务组接收disconnect并清理；仍不能推断覆盖所有Windows Proactor错误/休眠/长稳，继续检查实际PID退出。
- 0.3.0第七阶段：专用CLI、低层Device调用方未全部迁移，共享SDK不是完整Device替代。共享断点仅FPBv1，未制造真实HardFault；Bootloader重枚举升级、非Windows共享MSC受限。物理擦除/恢复、操作中拔插/休眠和断电未验收；长期测试按用户要求暂停。HPM FreeRTOS SystemView已短时真机验证，其他RTOS待验。MAP/C回退仅基本全局标量，新增声明须显式重载，不等于源码与固件匹配；稀疏类型待验。VOFA仍用独立文档内旧绘图脚本，无网页通道编辑器，原生集成待验；Float32不保留大整数低位，历史500点。UART开口前后身份校验、COM别名及启停事务已统一，读错误须显式重启；Modbus执行中结果未知不重放。现有UART/Modbus共享能力及专用CLI覆盖见详细报告，嵌套循环归属、逐请求断开取消、真实从站/拔插/OS阻塞仍待验。远程RTT/SystemView版本2及双探针本机LAN短时通过。旧111候选物理MSC三文件部署/哈希/双盘保持/清理通过，不等于触发烧录。114源码将offline.deploy接入RuntimeJobs，协议35/flash.offline版本2，GUI和SDK可按request_id查询；模拟取消/日志失败/换盘/去重及真实Chrome受控查询通过，115实包LAN查询/重复请求/正常重启保留已通过，116临时磁盘生产部署子进程中断通过；117已登记强杀恢复目录，仅供人工核查、可能已清理；物理MSC中断和完整GUI真实部署仍待验。最多64条记录，缺失不代表未执行，未知结果不得重放。
- nRF54L15在线GUI加锁/CTRL-AP解锁闭环待真机验收，用户已明确接受该限制；历史Python配方不能外推。
- 分发/订阅缓冲有界但不是无损通道；105批发现RTT按行解析未换行尾部缓存无上限；106批源码加上限且CI通过，固定包长稳不含修复且消息带换行不能覆盖：SSE及二进制流共用合并唤醒的有界投递，每次待投递批次和正在排空批次各不超过配置条数，客户端队列另有独立上限；这是记录数边界，不是任意载荷的总字节承诺。溢出保留最新数据，二进制丢弃计数包含进入客户端前的损失；SSE停止与初始元数据有专门边界。断线/长暂停不保证无损；外设轮询可漏短脉冲，多变量不是原子快照，packed奇地址写不保证原子性。
- HPM实时通道仅V4配套固件；HPM5301 OTP组18/19已永久锁定，禁止重放配方。VCC每次变更需确认，电源遥测未完成外部精度校准。
- STM32F767等重叠算法需匹配Bank模式；26个无可靠扇区表的FLM继续禁用扇区操作。
- Mac/Linux、跨主机Agent、物理Modbus及所有芯片组合未完整认证；新固件仅格式/CRC/发布校验，不等同于重新完成实机认证。

## 延续协议

- 交接只保存现状、关键限制和报告索引；详细历史留在docs/verification。
