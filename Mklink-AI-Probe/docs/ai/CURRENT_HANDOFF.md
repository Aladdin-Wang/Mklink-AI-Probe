# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-04T20:08:05.355840+00:00`
- 分支：`codex/v0.3.0-shared-runtime`
- HEAD：`Based on main d4e73bd; 24h portable runtime soak started after b2508240; use Git for exact tip.`
- 远端 HEAD：`Application release v0.2.3 fixed at b0e0f61; verify current main with Git.`
- 工作树：Isolated task worktree; main and firmware source unchanged. Use Git for current commit and PR status.
- 当前任务：109批修复脱机部署Windows只读文件回滚与暂存清理：复用_remove_probe_file，新增3项实文件测试；短时109项通过，21项既有白名单失败需调查。长期测试继续暂停。
- 状态：`in_progress`

## 里程碑

- **0.3.0 专用CLI共享迁移** — `development`。每探针独立后台；常用MCP、28类CLI（配置说明/生成及外设索引仍离线）及SharedDevice/connect_shared SDK共享；独占任务持久化，MSC绑定USB身份。专用CLI、低层Device调用方、独立Agent、安装版和长稳待后续。
- **0.2.3正式版** — `complete`。三个发布渠道及更新索引通过；本地安装版和Skill为b0e0f61。
- **2026-10-03固件** — `complete`。HPMLink/MicroLink V4.5.2、MicroLink V3.5.2、V2.8.1已三端发布；V2为RBL附件，不进入UF2自动更新索引。

## 验证证据

- **共享后台、多探针与AI共存**：第107节：soak104按用户要求提前停止，本地与LAN各160797字节，22个样本；仅短时观察，不能认定长稳通过。
- **正式版与安装**：docs/verification/v0.2.3-release-final.md；Python2459/2跳过、GUI762，NSIS/Agent实包、签名及三端索引通过。
- **固件发布与代码同步**：docs/verification/firmware-20261003.md；UF2格式、RBL CRC/版本、三端下载哈希和索引通过；V2/V3 AP模型、V3电源及USB恢复通过。本轮未刷机。
- **实机与SuperWatch**：按需查docs/verification/v0.2.3-integration-20261002.md、v0.2.3-installed-f103-20261002.md；界面证据见superwatch-drag-groups-20261003.md、superwatch-inline-names-20261002.md。历史报告保留，不在交接重复流水账。

## 架构决策

- 应用开发从MicroKeen/main建codex分支，经PR、CI整合；发布及合并需明确授权，标签/资产不可覆盖。
- 0.3保留CDC：USB序列号绑定后台及MSC，本机别名不写固件；多设备不选第一台，丢失身份拒绝新操作，不重放。GUI/MCP和已迁移CLI不再有--direct；Python脚本新增共享SDK，低层Device仍供后台/专用工具使用。后台协议34，内嵌远程服务已接入共享会话，仅允许绑定物理探针后台。 工程上下文固定于后台生命周期；删除旧PUT热切换入口，换工程须显式停止该探针后台再启动。 发现统一被动MI_04枚举，删除discover/自动连接全局锁/失败遍历与保存COM；底层自动连接也只接受唯一候选。 CDC和MSC共用probes不可变进程绑定，Bridge开口前后校验，lobby拒绝CDC/MSC/目标访问，允许独立UART会话；不是原子句柄身份认证。
- 应用MicroKeen/release主索引，旧GitHub/updates与Gitee/updates兼容；探针固件独立firmware索引。V2 RBL仅附件。
- V4代码MicroLink_Plus/main=4bf704a；V3 MicroLinkV3/main=6a39d28；V2 MicroLinkV2/main=d32c56f，均已同步GitHub。Arm-2D/MicroBoot禁止随本任务修改、提交或上传。
- 正式包、唯一备份、验收证据和依赖缓存保留；本轮清理20项约1.68GiB，48个含链接临时目录留待人工检查。mklink-issues-pr自动任务维持暂停。

## 真机环境

- **state**：用户要求长期验证暂缓，等待后续明确通知。soak104已通过停止标记正常清理，运行1312.05秒，未完成24小时验收；禁止自动恢复或另启长期验证。 本轮两后台及控制进程已退出，端点清理完成，无清理错误。
- **installer**：本地仍为0.2.3/b0e0f61；0.3.0为源码开发分支，不代表安装/升级验收。
- **backups**：原始实机证据、发布包与清理清单保留在本地.build。

## 下一动作

1. 用户要求长期验证暂缓，等待后续明确通知。soak104已通过停止标记正常清理，运行1312.05秒，未完成24小时验收；禁止自动恢复或另启长期验证。 后续可继续短时架构审计及验证；不启动24/72小时等长期任务。
2. 优先调查脱机安全算法白名单：修改前dba9935c同样21项失败，不能豁免或改白名单绕过。109批只读文件修复本地109项通过/22项未选，待CI。脱机部署持久查询尚未实现，新包短时验证和NSIS UAC仍待验。
3. 需要清理剩余含链接目录时先人工核对链接目标，不强制删除或改ACL。

## 已知限制

- A5已收敛。A6活动MCP37工具，仍有旧能力待迁移。A7端口锁统一、旧锁兼容删除；共享后台/API/多探针/VOFA及GUI契约与构建已进入CI，准确数量看精确提交报告。bfcache生命周期已修，但本机no-store阻止原生缓存命中，仅完成单测、受控恢复事件及普通返回验证；原生命中需补验。 Python/原生标准输出已统一轮转，启动文件只记录初始化前诊断；NSIS与非Windows仍待验收。 第二十一批已修复真实TCP reset复现的二进制流订阅退出卡住，使用框架任务组接收disconnect并清理；仍不能推断覆盖所有Windows Proactor错误/休眠/长稳，继续检查实际PID退出。
- 0.3.0第七阶段：剩余专用CLI、低层Device调用方与独立Agent未全部迁移；共享SDK不是完整Device替代；新增共享断点仅FPBv1，未制造真实HardFault。内嵌远程服务核心已接入共享；Bootloader重枚举升级及非Windows共享MSC仍受限。脱机部署、原生擦除准备已实现但物理擦除/恢复、操作中拔插/休眠、崩溃恢复、24/72小时长稳及安装升级未验收。HPM FreeRTOS共享SystemView已短时真机验证，长稳及其他RTOS组合待验。 MAP/C回退仅受限基本全局标量，新增源文件/声明须显式重载，不等于源码与固件匹配；HPM工程wave_tick符号读取已真机通过，稀疏类型及MAP/C回退覆盖仍待验证。 VOFA Web页复用旧全局绘图脚本，独立文档隔离，无网页通道编辑器；原生桌面不提供浏览器专用链接，集成待验。Float32图形不保留大整数低位，历史最多500点。 UART开口前后校验与COM别名规范化已统一；监控不自动重连，读错误须显式停止/重启。UART及Modbus REST均复用公共异步启停事务；Modbus排队超时/停止取消与执行中结果未知已明确。独立UART在lobby及目标任务期间准入已实现，共享scope=uart已支持端口列表、两类启停/状态、串口发送、Modbus事务、单地址扫描及有界历史/共享日志/命令序列/广播文件及Modbus循环/YMODEM/exchange25项；启停拥有者与借用者已统一，显式发送共享现有worker；单事务slave已支持且不改连接默认值；scan/read/write/poll/dashboard/diag/monitor CLI已共享且共用连接上下文；FC07/22/23复用既有transaction，FC23保持一次读写且独立写地址，扫描临时参数限单worker任务并恢复；monitor已有500事件会话游标并逐条写日志；serial send已共享且共用UART生命周期；serial dashboard已迁主GUI并删除旧服务；嵌套循环任务归属、逐请求HTTP断开取消仍待迁移；尚无真实Modbus从站/拔插/OS开口阻塞验收。 远程offline.deploy已复用共享后台表单部署接口，preview可离线；未连接拒绝，物理MSC及独立Agent实包短时验证通过，异常恢复和长稳待验；第75批24项目标能力已共享；Agent RTT/SystemView版本2均已共享并完成短时本机LAN真机验证；MSC部署适配回归已通过，物理MSC文件部署已由33ff94c1便携包验证（三文件哈希/双盘保持/清理），不等于触发烧录或异常恢复验收；部署尚不属于持久任务日志，丢失响应需核查磁盘且不重放。
- nRF54L15在线GUI加锁/CTRL-AP解锁闭环待真机验收，用户已明确接受该限制；历史Python配方不能外推。
- 分发/订阅缓冲有界但不是无损通道；105批发现RTT按行解析未换行尾部缓存无上限；106批源码加上限且CI通过，固定包长稳不含修复且消息带换行不能覆盖：SSE及二进制流共用合并唤醒的有界投递，每次待投递批次和正在排空批次各不超过配置条数，客户端队列另有独立上限；这是记录数边界，不是任意载荷的总字节承诺。溢出保留最新数据，二进制丢弃计数包含进入客户端前的损失；SSE停止与初始元数据有专门边界。断线/长暂停不保证无损；外设轮询可漏短脉冲，多变量不是原子快照，packed奇地址写不保证原子性。
- HPM实时通道仅V4配套固件；HPM5301 OTP组18/19已永久锁定，禁止重放配方。VCC每次变更需确认，电源遥测未完成外部精度校准。
- STM32F767等重叠算法需匹配Bank模式；26个无可靠扇区表的FLM继续禁用扇区操作。
- Mac/Linux、跨主机Agent、物理Modbus及所有芯片组合未完整认证；新固件仅格式/CRC/发布校验，不等同于重新完成实机认证。
- Windows安装器无Authenticode签名，更新签名已验证；标准包不含离线WebView2。 第78批原生主程序退出残留已修复并实测；NSIS候选已构建且负载自包含验证通过；perMachine安装/升级仍需Windows管理员/UAC配合，尚未执行。第83批配置初始加载覆盖快速选择已修复并通过真实Edge受控延迟验证。 第81批普通serve/serve_fastapi/run_server已删除；第82批已修复正常关窗的presence残留，真实双桌面立即停止后台通过；崩溃或后台不可达仍依赖既有TTL，未声称强杀也可立即清理。远程RTT/SystemView版本2均已接入；旧独占入口已删除。

## 延续协议

- 交接只保存现状、关键限制和报告索引；详细历史留在docs/verification。
