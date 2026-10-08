# 0.3.1 候选真机验收（进行中）

日期：2026-10-09。产品源码 `aad53020`，测试断言修正 `72962eda`，生产 Web
提交 `66a5d0fb`。运行标准 NSIS 提取出的冻结 sidecar，只有 Windows PATH，
源码桌面代理转发包内 Web；浏览器、冻结 MCP/CLI 和共享 SDK 连接同一后台。
这不是覆盖安装验证；用户明确允许跳过需要人工确认的管理员权限验证。

## 硬件与恢复依据

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
无法及时启动。已交由原固件会话修复、重新构建与真机回归；本会话等待新的明确交接。
不通过降低上位机默认采样率掩盖故障，也不把原V4.6.2分项结果当成修复后二进制结果。
完成整片读回及退出释放后，已明确把设备交还原固件会话；其修复期间本会话不再触碰硬件。

## 尚未覆盖

- 新固件修复后的1kHz及最大速率Watch/UART完整并发矩阵；最终包重连、全部退出释放。
- 真实旧版下载器手动按键升级、更新UF2的自动bootloader/复制/重新枚举；当前固件
  高于公开版本，不能降级或伪造版本制造升级通过。界面/控制流组件证据单独记录。
- 实体拔插、V3/HPM、多探针、客户CS32L015、IAR、外部RS485/Modbus从机、
  客户私有协议及YMODEM接收端；现有设备不能代替这些夹具。
- 原生桌面完整交互和覆盖安装不等同提取sidecar/Web验证；UAC项明确豁免，其余
  缺口保留给正式发布验收，不标记为已通过。

截至本报告，完整验收未结束，0.3.1不应标为发布就绪；候选包仅供预发布验证。
