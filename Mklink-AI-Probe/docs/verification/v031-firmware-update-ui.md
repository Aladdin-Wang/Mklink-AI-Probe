# 0.3.1 固件升级界面与自动/手动路径

日期：2026-10-08。分支 `codex/0.3.1-fixes`，PR #33。

用户要求：老下载器不支持进入 Bootloader 时不报错，提供下载至本地和按键手动升级；
支持进入时自动升级。本批只修改上位机，不修改或烧写下载器固件。

## 原因及实现

截图错误由 RuntimeGate 对 firmware-upgrade 的无条件 409 返回造成，请求尚未进入
原升级函数。旧页面仅在返回可下载固件详情时显示手动区域，且将手动结果当作错误 toast。

现在共享后台保留所选 USB 身份，经独占操作准入执行升级，不再统一拦截。即使未连接
目标 MCU，也可按所选下载器命令口进入 Bootloader；不初始化 MCU、不另开另一台设备。
存在其他客户端、采集（含 UART/Modbus）、在途任务时仍拒绝重启探针；升级执行期间
也拒绝新 UART 操作。请求取消后沿用运行时 settle 规则保留操作直至实际退出。

Windows 卷枚举包含 Bootloader 卷，正常 MSC 操作继续筛选 MICROKEEN。升级通过原
VID/PID/序列号和卷 GUID 查找，允许已确认的 V3/V4 正常态 16 位 hex → Bootloader
32 位 hex 前缀映射，并要求唯一匹配及 `INFO_UF2.TXT` 的 MicroKeenLink Board-ID。
拷贝前再次核对，不能因盘符相同、卷标相同或只有一个新盘就写入。升级后只从原 USB
身份的应用盘读版本；复制后未确认、可能部分写入都不能宣称成功或自动重放。

映射的只读源码依据：MicroLink V3 的 microlink_app_v3/src/usb_configuration.c、
V4 的 microlink_app/src/usb_configuration.c 均以 OTP 88/89 生成正常态 USB serial；
相应 microlink_bootloader/src/msc_bootuf2.c 及 V4 hpmlink_bootloader 使用 OTP 88..91。
本批没有拿这些源码事实冒充客户安装 Bootloader 的实测。不同历史描述符不匹配时转手动。

进入指令异常、命令口不可用、等待 Bootloader 超时或磁盘身份变化均返回正常手动引导。
手动页面提供固件保存、V3 眼睛中间按键/V4 侧边拨轮按键、USB 插拔、UF2 复制步骤；
未知型号必须显式选择。保留真实 HTTP/文件下载异常，避免把下载失败伪装成保存成功。

## 验证

- 最终 Python 311 项通过：固件升级、卷绑定、共享准入、MCP/GUI 相关运行时、UART、
  设备发现、重连和脱机下载。覆盖无指令、无盘、身份变化、拒绝另一设备/重复候选、
  命令口不初始化 MCU、正常复制并读回版本，以及升级与 UART 的双向互斥。
- GUI 54 项通过：旧版手动结果无错误 toast、下载保存调用、未知型号选择与自动完成。
- TypeScript 和生产构建通过；生产资源已更新。固件测试加入共享 Runtime CI。
- 真实浏览器加载生产资源、模拟 API：手动区域正常显示，无红色错误提示；支持自动
  升级的模拟结果显示“升级完成”。截图在本地 `.build/reports/v031-firmware-manual.png`
  和 `v031-firmware-automatic.png`。保存对话框在内置浏览器中取消，未宣称实测文件落盘；
  二进制下载 API 与保存调用由测试覆盖。该浏览器验证不涉及硬件。
- 既有 websockets.legacy/大前端 chunk 警告保留。测试链接目录
  `.build/runs/run-20261008-224834-3a438252` 按包装器策略保留，未强删。

未构建或覆盖 NSIS，未安装到客户电脑，未执行真实 UF2 升级。旧固件按键、USB 再枚举、
多探针及复制后返回应用模式需对应硬件验收。固件会话仍持有实机，本会话没有碰硬件。
