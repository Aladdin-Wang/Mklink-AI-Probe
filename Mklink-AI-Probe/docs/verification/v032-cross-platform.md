# 0.3.2 macOS/Linux 桌面与 USB 枚举

本次是用户授权的新修复分支 `codex/0.3.2-fixes`，不修改已发布 0.3.1 标签、安装包或更新索引。

## 已定位的问题

- 旧 `usb_interface_number` 将 hwid/location/interface 拼接后匹配末尾数字。
  macOS 的 `0-1.3.4.2.1` 是物理 USB 拓扑，错误返回接口 1，命令口 MI_04 未入选。
  “接口身份冲突”不是这段筛选代码直接产生的结论。
- Linux pyserial 的 location 为 `bus-port:configuration.interface`；拼接非空接口名后，
  旧末尾正则也可能匹配不到真实接口。
- 桌面后端查找和进程启动包含未隔离的 Windows 代码，非 Windows 构建缺少启动函数。

## 改动与候选包

- macOS 通过 ioreg plist，将具体 BSD 节点关联到同一设备的 USB 接口祖先；核对 VID/PID/序列号。
  不推断 BSD 节点后缀。CDC 数据接口只在同设备控制接口类、子类、功能名均符合已知 MKLink
  配对时归一化。缺失或冲突返回未知，不打开串口探测。每次枚举使用一次新快照。
- Linux 单独解析包含 configuration/interface 的 location，缺失时查询对应 tty 的 sysfs。
- Windows 保留 MI 和 `:x.N` 解析；拒绝普通点分拓扑作为接口证据。
- 原生 GitHub 构建机分别构建 Apple Silicon、Intel DMG 和 Linux x64 DEB/AppImage；
  内置本平台 PyInstaller 后端和 Go STCP 库，算法来自已发布且 SHA-256 固定的 0.3.1 Skill。

## 验证边界

执行结果待本轮追加。回归 fixture 证明解析和身份边界，不等同用户 Mac USB 真机测试。
云构建机无探针；冻结 CLI/MCP、后端健康、Web 资源与退出检查不等同交互式安装及硬件验收。
Mac 包仅 ad-hoc 签名，无 Apple Developer ID 公证；不签署更新包，不自动发布。
现有远程服务密钥保存和原生剪贴板仍为 Windows 专用实现；本轮不得宣称这些功能跨平台验收完成。
