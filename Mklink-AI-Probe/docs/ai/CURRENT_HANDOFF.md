# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-03T21:31:18+00:00`
- 分支：`codex/v0.3.0-shared-runtime`
- HEAD：`Based on main d4e73bd; shared watch and bounded MAP/C snapshot implemented after 9f80f11; see PR 30 and Git for exact tip.`
- 远端 HEAD：`Application release v0.2.3 fixed at b0e0f61; verify current main with Git.`
- 工作树：Isolated task worktree; main and firmware source unchanged. Use Git for current commit and PR status.
- 当前任务：持续循环评审/验证。watch已迁移共享目录/批量读取，删除旧逐变量CDC与重复循环；MAP/C限定工程范围、冻结解析依据、拒绝歧义和来源变化。最终扩展1553通过/2可选跳过，双下载器Edge/SDK/MCP真机通过；实际后台/串口子进程退出。继续VOFA等专用入口与A7。
- 状态：`in_progress`

## 里程碑

- **0.3.0 专用CLI共享迁移** — `development`。每探针独立后台；常用MCP、27类CLI（配置说明/生成及外设索引仍离线）及SharedDevice/connect_shared SDK共享；独占任务持久化，MSC绑定USB身份。专用CLI、低层Device调用方、独立Agent、安装版和长稳待后续。
- **0.2.3正式版** — `complete`。三个发布渠道及更新索引通过；本地安装版和Skill为b0e0f61。
- **2026-10-03固件** — `complete`。HPMLink/MicroLink V4.5.2、MicroLink V3.5.2、V2.8.1已三端发布；V2为RBL附件，不进入UF2自动更新索引。

## 验证证据

- **共享后台、多探针与AI共存**：docs/verification/v0.3.0-mcp-consolidation.md第二十二批：最终1553通过/2可选依赖跳过；CI集合957后台/79GUI。watch单次/周期、批量顺序、C覆盖/只读Flash/枚举、MAP/C边界与变更拒绝通过。双下载器/Edge/SDK/MCP真机：GUI RTT中watch均409且两会话保持，停止后数组首尾与裸内存一致；周期退出只detach，第二探针独立；Boot/选项字节/VTOR/配置保持、tick推进，后台及串口子进程退出已实查。
- **正式版与安装**：docs/verification/v0.2.3-release-final.md；Python2459/2跳过、GUI762，NSIS/Agent实包、签名及三端索引通过。
- **固件发布与代码同步**：docs/verification/firmware-20261003.md；UF2格式、RBL CRC/版本、三端下载哈希和索引通过；V2/V3 AP模型、V3电源及USB恢复通过。本轮未刷机。
- **实机与SuperWatch**：按需查docs/verification/v0.2.3-integration-20261002.md、v0.2.3-installed-f103-20261002.md；界面证据见superwatch-drag-groups-20261003.md、superwatch-inline-names-20261002.md。历史报告保留，不在交接重复流水账。

## 架构决策

- 应用开发从MicroKeen/main建codex分支，经PR、CI整合；发布及合并需明确授权，标签/资产不可覆盖。
- 0.3保留CDC：USB序列号绑定后台及MSC，本机别名不写固件；多设备不选第一台，丢失身份拒绝新操作，不重放。GUI/MCP和已迁移CLI不再有--direct；Python脚本新增共享SDK，低层Device仍供后台/专用工具使用。后台协议7，内嵌Agent暂禁用。 工程上下文固定于后台生命周期；删除旧PUT热切换入口，换工程须显式停止该探针后台再启动。 发现统一被动MI_04枚举，删除discover/自动连接全局锁/失败遍历与保存COM；底层自动连接也只接受唯一候选。 CDC和MSC共用probes不可变进程绑定，Bridge开口前后校验，lobby不访问硬件；不是原子句柄身份认证。
- 应用MicroKeen/release主索引，旧GitHub/updates与Gitee/updates兼容；探针固件独立firmware索引。V2 RBL仅附件。
- V4代码MicroLink_Plus/main=4bf704a；V3 MicroLinkV3/main=6a39d28；V2 MicroLinkV2/main=d32c56f，均已同步GitHub。Arm-2D/MicroBoot禁止随本任务修改、提交或上传。
- 正式包、唯一备份、验收证据和依赖缓存保留；本轮清理20项约1.68GiB，48个含链接临时目录留待人工检查。mklink-issues-pr自动任务维持暂停。

## 真机环境

- **state**：主V4+STM32F103RET6：Bootloader(0x08000000)+App(0x08005000)，512KiB。GUI RTT/两会话期间watch冲突不抢停；停止后SDK/CLI/MCP变量与数组读取、三轮周期退出及GUI再启停通过。第二探针仅版本查询，CDC/MSC独立。Boot20KiB/选项字节/VTOR/配置保持，tick推进；两后台及串口子进程实际退出。未reset目标、烧录、擦除、写RAM、改保护/OTP/VCC/时钟；每轮须重枚举。
- **installer**：本地仍为0.2.3/b0e0f61；0.3.0为源码开发分支，不代表安装/升级验收。
- **backups**：原始实机证据、发布包与清理清单保留在本地.build。

## 下一动作

1. 继续VOFA共享迁移：旧CLI是原生vofa.send/JustFloat，GUI已有VofaStreamManager（dump或内存读取），先核对采样/停止/订阅语义，复用现有管理器与准入，避免另造服务或悄悄降级。随后串口/分析等专用CLI、独立Agent/旧MCP及A7双设备长稳/拔插/休眠/NSIS。保持后台/串口子进程实际退出断言。不改下载器固件/WinUSB，不自动合并发布。
2. 需要清理剩余含链接目录时先人工核对链接目标，不强制删除或改ACL。

## 已知限制

- A5已收敛。A6活动MCP37工具，仍有旧能力待迁移。A7端口锁统一、旧锁兼容删除；已新增957项后台（含实际API、探针、配置、外设、批量内存、dump、flush、吞吐/流停止及发现/开口身份绑定）/79项GUI及构建CI。bfcache生命周期已修，但本机no-store阻止原生缓存命中，仅完成单测、受控恢复事件及普通返回验证；原生命中需补验。 Python/原生标准输出已统一轮转，启动文件只记录初始化前诊断；NSIS与非Windows仍待验收。 第二十一批已修复真实TCP reset复现的二进制流订阅退出卡住，使用框架任务组接收disconnect并清理；仍不能推断覆盖所有Windows Proactor错误/休眠/长稳，继续检查实际PID退出。
- 0.3.0第七阶段：VOFA/串口/分析等专用CLI、低层Device调用方与独立Agent未迁移；共享SDK不是完整Device替代；新增共享断点仅FPBv1，未制造真实HardFault。内嵌Agent、Bootloader重枚举升级及非Windows共享MSC仍受限。脱机部署、全新连接erase准备、操作中拔插/休眠、崩溃恢复、24/72小时长稳及安装升级未验收。共享SystemView缺RTOS事件实测。 MAP/C回退仅受限基本全局标量，新增源文件/声明须显式重载，不等于源码与固件匹配；HPM稀疏DWARF真机待验证。
- nRF54L15在线GUI加锁/CTRL-AP解锁闭环待真机验收，用户已明确接受该限制；历史Python配方不能外推。
- 有限缓冲、断线或长暂停不保证无损；外设轮询可漏短脉冲，多变量不是原子快照；packed奇地址写不保证原子性。
- HPM实时通道仅V4配套固件；HPM5301 OTP组18/19已永久锁定，禁止重放配方。VCC每次变更需确认，电源遥测未完成外部精度校准。
- STM32F767等重叠算法需匹配Bank模式；26个无可靠扇区表的FLM继续禁用扇区操作。
- Mac/Linux、跨主机Agent、物理Modbus及所有芯片组合未完整认证；新固件仅格式/CRC/发布校验，不等同于重新完成实机认证。
- Windows安装器无Authenticode签名，更新签名已验证；标准包不含离线WebView2。

## 延续协议

- 交接只保存现状、关键限制和报告索引；详细历史留在docs/verification。
