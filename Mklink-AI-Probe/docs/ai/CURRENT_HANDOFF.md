# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-10-04T00:24:16+00:00`
- 分支：`codex/v0.3.0-shared-runtime`
- HEAD：`Based on main d4e73bd; finite Modbus loop completion and revisioned HTTP/SSE state fixed after 6f12ed6; see PR 30 and Git for exact tip.`
- 远端 HEAD：`Application release v0.2.3 fixed at b0e0f61; verify current main with Git.`
- 工作树：Isolated task worktree; main and firmware source unchanged. Use Git for current commit and PR status.
- 当前任务：持续循环评审/验证。第二十七批修复有限Modbus循环末次后额外等待、线程启动失败假运行、HTTP迟到响应覆盖SSE。复用既有生命周期锁及循环状态，加入单调revision跨重连排序，前端共用状态应用函数；共享协议8，旧后台须显式停止。后端1091、相关GUI34、类型/外置构建及真实Edge HTTP/SSE乱序验证通过；Modbus为模拟从站，未访问物理串口。6f12ed6远端三项全部通过，本批CI待精确核对。继续UART/Modbus共享CLI/MCP及独立端口准入。
- 状态：`in_progress`

## 里程碑

- **0.3.0 专用CLI共享迁移** — `development`。每探针独立后台；常用MCP、28类CLI（配置说明/生成及外设索引仍离线）及SharedDevice/connect_shared SDK共享；独占任务持久化，MSC绑定USB身份。专用CLI、低层Device调用方、独立Agent、安装版和长稳待后续。
- **0.2.3正式版** — `complete`。三个发布渠道及更新索引通过；本地安装版和Skill为b0e0f61。
- **2026-10-03固件** — `complete`。HPMLink/MicroLink V4.5.2、MicroLink V3.5.2、V2.8.1已三端发布；V2为RBL附件，不进入UF2自动更新索引。

## 验证证据

- **共享后台、多探针与AI共存**：docs/verification/v0.3.0-mcp-consolidation.md第二十七批：后端契约1091通过，相关GUI34通过、类型/外置构建通过；先复现2项后端/2项前端失败后修复。Edge真实HTTP/SSE验证count=1/interval=3600立即结束、终止事件先于启动响应、另一客户端新循环先于旧停止响应；3次模拟读取，无物理串口、浏览器错误，worker及HTTP服务退出。前批6f12ed6远端后端1089、GUI209/构建及feedback全部通过，VOFA回收前峰值增量74833264B。前批双探针真机验证边界见第二十五批；本批不是物理Modbus或长稳验收。
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

- **state**：主V4+STM32F103RET6：Bootloader(0x08000000)+App(0x08005000)，512KiB。双后台分别打开各自UART及Modbus手动会话，主WebGUI RTT/MCP/SDK并存；同端口竞争409、命令口400、浏览器恢复实际Modbus配置、关闭第二页面不影响会话、连续两次重连通过。第二探针仅版本查询和UART/Modbus开关，未初始化目标。Boot20KiB/选项字节/VTOR/配置保持、tick推进；后台及串口子进程实际退出。真机未发送UART/Modbus数据、reset/烧录/擦除/写RAM/改保护/OTP/VCC/时钟；每轮须重枚举。
- **installer**：本地仍为0.2.3/b0e0f61；0.3.0为源码开发分支，不代表安装/升级验收。
- **backups**：原始实机证据、发布包与清理清单保留在本地.build。

## 下一动作

1. 继续迁移UART/Modbus专用CLI与旧MCP能力：复用RuntimeClient/Session/现有管理器，定义target与UART会话领域、按串口的共享订阅/发送归属，分离lobby及目标任务期间的UART准入；审计HTTP断开时逐请求取消。不得让独立UART附着隐式初始化MCU，也不新增后台或OS锁。随后分析入口/独立Agent、A7双设备长稳、拔插/休眠和NSIS；保持实际进程退出断言，不改下载器固件/WinUSB，不自动合并发布。
2. 需要清理剩余含链接目录时先人工核对链接目标，不强制删除或改ACL。

## 已知限制

- A5已收敛。A6活动MCP37工具，仍有旧能力待迁移。A7端口锁统一、旧锁兼容删除；共享后台/API/多探针/VOFA及GUI契约与构建已进入CI，准确数量看精确提交报告。bfcache生命周期已修，但本机no-store阻止原生缓存命中，仅完成单测、受控恢复事件及普通返回验证；原生命中需补验。 Python/原生标准输出已统一轮转，启动文件只记录初始化前诊断；NSIS与非Windows仍待验收。 第二十一批已修复真实TCP reset复现的二进制流订阅退出卡住，使用框架任务组接收disconnect并清理；仍不能推断覆盖所有Windows Proactor错误/休眠/长稳，继续检查实际PID退出。
- 0.3.0第七阶段：串口/分析等专用CLI、低层Device调用方与独立Agent未迁移；共享SDK不是完整Device替代；新增共享断点仅FPBv1，未制造真实HardFault。内嵌Agent、Bootloader重枚举升级及非Windows共享MSC仍受限。脱机部署、全新连接erase准备、操作中拔插/休眠、崩溃恢复、24/72小时长稳及安装升级未验收。共享SystemView缺RTOS事件实测。 MAP/C回退仅受限基本全局标量，新增源文件/声明须显式重载，不等于源码与固件匹配；HPM稀疏DWARF真机待验证。 VOFA Web页复用旧全局绘图脚本，独立文档隔离，无网页通道编辑器；原生桌面不提供浏览器专用链接，集成待验。Float32图形不保留大整数低位，历史最多500点。 UART开口前后校验与COM别名规范化已统一；监控不自动重连，读错误须显式停止/重启。UART及Modbus REST均复用公共异步启停事务；Modbus排队超时/停止取消与执行中结果未知已明确。逐请求HTTP断开取消、独立UART在lobby的准入、跨客户端订阅/发送归属仍待迁移；尚无真实Modbus从站/拔插/OS开口阻塞验收。
- nRF54L15在线GUI加锁/CTRL-AP解锁闭环待真机验收，用户已明确接受该限制；历史Python配方不能外推。
- 有限缓冲、断线或长暂停不保证无损；外设轮询可漏短脉冲，多变量不是原子快照；packed奇地址写不保证原子性。
- HPM实时通道仅V4配套固件；HPM5301 OTP组18/19已永久锁定，禁止重放配方。VCC每次变更需确认，电源遥测未完成外部精度校准。
- STM32F767等重叠算法需匹配Bank模式；26个无可靠扇区表的FLM继续禁用扇区操作。
- Mac/Linux、跨主机Agent、物理Modbus及所有芯片组合未完整认证；新固件仅格式/CRC/发布校验，不等同于重新完成实机认证。
- Windows安装器无Authenticode签名，更新签名已验证；标准包不含离线WebView2。

## 延续协议

- 交接只保存现状、关键限制和报告索引；详细历史留在docs/verification。
