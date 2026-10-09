# 0.3.1 候选真机验收（现有硬件范围完成）

日期：2026-10-09。产品源码 `aad53020`，测试断言修正 `72962eda`，生产 Web
提交 `66a5d0fb`。运行标准 NSIS 提取出的冻结 sidecar，只有 Windows PATH，
源码桌面代理转发包内 Web；浏览器、冻结 MCP/CLI 和共享 SDK 连接同一后台。
这不是覆盖安装验证；用户明确允许跳过需要人工确认的管理员权限验证。

## V4.6.2 初轮硬件与恢复依据

- 收到固件会话明确最终交接后操作；物理 USB 身份每次绑定，具体序列号仅存本地。
- V4.6.2 UF2 SHA256：`5b810fd8ae4d7fab80a1a65ca46d3ef511a8ee854c8d43d96a2046aaa7ee2ddf`。
- STM32F103RE，APP `0x08005000`，SWD+NRST；UART5 PC12 TX / PD2 RX。
- 原程序 AXF SHA256：`c72821223afd176d09c990d94767c7ffc731cbda50d410f30f51b3ac0ed788a0`。
- 烧录前读取全部 512 KiB Flash，AXF 的 113304 字节装载段与备份相同。
  只回烧原 APP 及末尾已备份扇区填充，未改变 VCC、选项字节或未知程序。
- 烧录后再次读取全部 512 KiB：与原备份逐字节一致，SHA256
  `59853f642252c18e0060b024cf0ded2621d9dde3a508f267e88a9a6029a1f3ac`。
  自建脱机脚本/镜像/算法文件先归档，再按精确路径清理，原文件保留。

## 已实测通过

| 场景 | 结果与证据 |
|---|---|
| 连接、符号和采集 | 冻结后台0.3.1/协议50，AXF内置解析5909变量；8路RTT与4路SuperWatch采集 |
| GUI/MCP/CLI共存 | 浏览器与冻结stdio MCP、CLI共用后台；MCP/CLI退出不停止GUI采集 |
| 在线烧录 | 已备份APP擦除/写入/校验/复位完成；RTT+Watch自动暂停恢复，整片Flash不变 |
| 脱机部署及触发 | 精确STM32F103RE内置512 KiB算法，一轮下载完成；部署和触发均恢复两类采集 |
| AI共享flash | 27.2秒完成、readback verified=true，修复后的嵌套锁路径无死锁，恢复两类采集 |
| 失败与停止 | 只读校验使用故意不匹配副本得到failed；另一只读校验主动停止得到stopped；两者恢复采集，无擦写 |
| 调试器共存 | OpenOCD运行→halt→step→resume→shutdown；RTT8/Watch4持续，未改目标Flash |
| GUI退出 | 关闭浏览器和代理后，AI仍能使用；AI接管并停止原GUI所有的RTT/Watch，无手工杀后台 |
| 全部退出释放 | 最后客户端退出后5.63秒冻结后台自动退出，endpoint删除；命令口/UART都可重新打开并关闭 |
| RTT搜索 | 已知RAM窗口真实扫描与精确AXF地址两种方式启动成功；伪签名跳过另由组件测试覆盖 |
| 串口基础/扩展 | UART5实际help/version响应；2条命令队列完成、广播、原始文件发送、文件记录完成；记录区分TX/RX |
| 串口界面 | 四项扩展默认隐藏，运行时“记录中”仍显示；真实页面展开显示四项，终端显示目标shell输出 |
| 固件检查 | 实读V4.6.2；发布渠道推荐V4.6.0，未降级。另一个AI客户端存在时维护升级正确拒绝，未刷写 |

本地证据：主工作区 `.build/artifacts/v031-candidate-72962eda/hil/` 的
`12-capture-coexist.json`、`14-online-run.json`、`16-offline-run.json`、
`17-shared-flash.json`、`21-openocd.json`、`22-online-negative.json`、
`28-gui-exit.json`、`30-serial-extensions.json`、`32-final-checks.json`、`33-release.json`。
截图在 `.build/reports/v031-hil-*.png`。令牌、原程序备份、设备身份和原始日志不提交。

辅助脚本的 OpenOCD 默认 SDK 缺少 stm32f1x.cfg，改用固件会话已准备的目标配置后通过；
最初脚本误读 SuperWatch 状态字段等脚本错误单独保留，不作为产品失败。

## 新发现：1 kHz Watch 饿死串口前台服务

同一原程序、接线和115200 8N1，发送 `version`，等待2秒：

| 并行采集 | UART返回 |
|---|---:|
| 无采集 | 154字节，完整RT-Thread版本 |
| RTT8 | 154字节 |
| Watch4，默认约1000 Hz | 0字节 |
| RTT8 + Watch4，约1000 Hz | 0字节 |
| Watch4，100 Hz | 154字节 |
| Watch4，10 Hz | 154字节 |
| 停止采集后 | 154字节 |

证据：`29-serial-matrix.json`、`30-serial-extensions.json`。期间DHCSR为
`0x01010000`，不能把此失败解释成目标halt。OpenOCD暂停/继续后曾释放积压shell输出；
早期“端口可打开且TX成功”不代表目标已及时收到或返回数据。

固件会话只读定位：1ms及以下Watch使priority7采集线程持续fast-service不yield，
而UART/RS485桥接前台四个服务仅由priority10主线程调用，导致空闲后的DMA/USB传输
无法及时启动。当时交由原固件会话修复、重新构建与真机回归，等待新的明确交接。
不通过降低上位机默认采样率掩盖故障，也不把原V4.6.2分项结果当成修复后二进制结果。
完成整片读回及退出释放后，已明确把设备交还原固件会话；其修复期间本会话不再触碰硬件。

## V4.6.3 最终补验

固件会话完成修复并明确交还设备后，核对新 UF2 SHA256
`605686ab804c983ac844ccb5b14b9070edb9d5eac15db2bca786f2d524f478eb`，
恢复后 AXF SHA256
`03a01fd6588de63713350fb9b7e8257334e262eb3955febcb1721f82d3731c8d`。
同一 USB 身份、STM32F103RE、UART5 与原接线，未改变供电。
固件将 UART/RS485 服务移至较高优先级 USB 传输线程，避免被快速 Watch 饿死。

本次重新运行冻结候选，隔离工程、运行时及 Pack 缓存均在 E 盘；先备份全片再烧录。
新证据独立存于主工作区 `.build/artifacts/v031-candidate-72962eda/hil-v463/`，
前节 V4.6.2 的失败记录保留作历史。

| 场景 | 新固件结果 |
|---|---|
| GUI/MCP/CLI 与采集 | RTT8、Watch4 及实际冻结 MCP/CLI 共存，所有 RTT 通道都有数据 |
| 原生提取候选启动 | Windows-only PATH 下真实桌面程序约6.006秒后台就绪；其进程退出后 AI 仍可使用，无外部 Python 子进程。非覆盖安装或原生关闭按钮交互 |
| 在线、脱机、AI共享烧录 | 原APP擦写校验成功；在线15.50秒、脱机部署及触发20.75秒、共享27.03秒，均恢复RTT/Watch |
| 校验失败及停止 | 只读不匹配校验失败、另一任务主动停止，两类采集均恢复；未擦写 |
| OpenOCD | halt、step、resume、shutdown完成，RTT8/Watch4仍可用 |
| 串口扩展 | 真实shell help/version、队列、广播、文件发送、记录通过；浏览器显示收发数据及默认折叠扩展 |
| GUI退出AI接续 | 浏览器和代理退出后采集继续；AI显式接管并停止原GUI采集，串口仍响应 |
| RTT8+Watch4+UART | 100Hz、1kHz及请求1µs间隔各5次version请求，全部返回154字节完整版本与shell提示；Watch读错误0，周期增长，RTT各通道有数据。请求间隔不等于保证实际采样频率 |
| 搜索和全片恢复 | 真实RAM RTT搜索通过；最终512KiB逐字节等于本轮备份，SHA256 `40aab8a117e7db22dfeffd13a2a592ab596bdd28a66fcd4a26443d2e72548732`；仅归档清理本轮创建的四个探针文件 |
| 重连和全部退出 | 旧endpoint显式connect重新发现同一探针的新冻结后台；最后退出6.018秒，endpoint删除，命令口及UART可重新开关 |

证据：`14-online.json`、`16-offline.json`、`17-shared-flash.json`、
`22-online-negative.json`、`21-openocd.json`、`30-serial-extensions.json`、
`28-gui-exit.json`、`31b-uart-watch-final.json`、`32-final-checks.json`、
`33-reconnect-release.json`。实际界面截图在 `.build/reports/v031-hil-v463-serial.png`。
`31-uart-watch-final.json` 是辅助脚本重复启动已有串口导致的预期409，
在同一AI所有者停止串口后重新启动补验通过，不是新产品缺陷。
固件会话另有最终V4.6.3的2Mbps UART/RS485环回与帧校验证据；本会话未重复该接线，
不能把它称为本会话独立RS485外部设备验收。

## 尚未覆盖

- 真实旧版下载器手动按键升级、更新UF2的自动bootloader/复制/重新枚举；当前固件
  高于公开版本，不能降级或伪造版本制造升级通过。界面/控制流组件证据单独记录。
- 实体拔插、V3/HPM、多探针、客户CS32L015、IAR、外部RS485/Modbus从机、
  客户私有协议及YMODEM接收端；现有设备不能代替这些夹具。
- 原生桌面完整交互和覆盖安装不等同提取sidecar/Web验证；UAC项明确豁免，其余
  缺口保留给正式发布验收，不标记为已通过。

现有硬件可覆盖的本轮验收已完成；剩余夹具与安装态限制保留，不声称全部型号认证。
发布准备仍需维护者审核、合并及正式构建/签名/发布授权，候选包未发布。


## 2026-10-09 用户安装后重新打开的文件检查缺陷

旧候选72962eda在原生在线文件选择入口仍可能出现本地检查409，
此前完成结论仅适用于上文所述矩阵，不能作为新反馈已经覆盖的证据。
已修复于acdcc997，生产资源d89c0827；相关192 Python/118 GUI及三项CI通过。
新NSIS提取原生桌面在RTT8+Watch1下，文件对话框加载、实际烧录10.73秒、
采集自动暂停恢复通过，10MHz整片512KiB读回相同，正常退出释放端口。
原30MHz采集连接的大块读偶发target status5，降到10MHz通过；固件会话仅源码核查，
不能将低频结果称为30MHz已修复。新包实际覆盖安装被WinError740阻挡，
等待用户人工安装后补验；安装态与提取包明确区分。
详细根因、NSIS哈希及证据见[v031-desktop-image-inspection.md](v031-desktop-image-inspection.md)。
旧Skill/SiteAgent候选未包含本次修复，正式发布需从同一最终提交重新构建全部产物，
并按精确tip重新完成发布门槛；本会话未合并、签名、发布或更新渠道。
