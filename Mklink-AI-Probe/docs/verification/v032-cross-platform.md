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

本地首轮 75 项通过（USB/发现/桌面打包/构建目录）。MSC 修复后接口/磁盘 48 项、
固件升级/脱机下载/部署/身份/构建目录 160 项、运行时版本/桌面打包 57 项通过。
首次扩展回归因未指定本地算法资产目录出现 21 项失败，绑定既有资产后 160 项全部通过。
原生 CI 首轮两台 Mac 缺少 Go，已补工具链安装；第二轮三平台安装包构建成功，
包内容检查暴露测试脚本漏传 JSON 参数，Linux 还发现旧测试全局修改 os.name 引起 pathlib
异常；两项测试问题均已修正。共享后台版本未随产品版本升级的遗漏也已修复。
最终候选来自 `d8b083045a96f87ed5c21053ba814d41ee288efa`，后续提交仅维护报告/交接。
[原生构建 37895715688](https://github.com/MicroKeen/Mklink-AI-Probe/actions/runs/37895715688)
三个 job 全部成功，每平台 USB/MSC 回归 47 通过、1 项 Windows 专用测试跳过。
冻结 CLI/MCP、后端健康、生产 Web 资源和正常退出全部通过；启动用时 ARM Mac 3.651 秒、
Intel Mac 7.993 秒、Linux 4.391 秒，仅代表本次云机测量。
Mac 从 DMG 挂载并复制应用后检查；Linux 从 DEB 提取后运行后端，另检查 AppImage 提取内容。
共享后台 CI 2754 项、GUI 契约 328 项及反馈契约通过，见 PR35 检查记录。
产物包含 build-manifest.json、SHA256SUMS.txt、qualification.json，分别记录精确源码、
包哈希和未验证项目。回归 fixture 证明解析和身份边界，不等同用户 Mac USB 真机测试。
客户另行报告通过 IOKit 精确节点读取 bInterfaceNumber/bInterfaceClass 并转换已知 CDC
数据/控制配对后，三个端口分别识别为 2/4/6，probes list 可列出设备。
这是客户补丁的实测结果，未取得原始设备树或在本候选包复测，不继承为候选包 HIL 通过。
云构建机无探针；冻结 CLI/MCP、后端健康、Web 资源与退出检查不等同交互式安装及硬件验收。
Mac 包仅 ad-hoc 签名，无 Apple Developer ID 公证；不签署更新包，不自动发布。
现有远程服务密钥保存和原生剪贴板仍为 Windows 专用实现；本轮不得宣称这些功能跨平台验收完成。
MSC 卷绑定现按系统识别：Windows 保留卷 GUID；macOS 由 IORegistry 中 IOMedia BSD Name
沿 USB 设备祖先关联 VID/PID/序列号，再用 diskutil plist 读取实际挂载点与卷名；Linux 由
mountinfo 的设备号关联 lsblk 卷元数据和 sysfs USB 祖先。不使用卷名/目录名猜身份，不按
枚举顺序选盘。每次解析重新盘点；POSIX 挂载点在返回前检查设备号与 inode，卸载后残留目录、
链接、身份改变、重复匹配均拒绝。运行态与 UF2 升级共用解析，保留已知 UID 映射和板型检查。
未挂载的卷交给操作系统/用户挂载，程序不会自动提权或挂载其他磁盘。
这不是从发现到所有后续文件操作的原子句柄认证，不能宣称拔盘/重挂载竞态完全消除。
新增系统元数据 fixture 覆盖多设备同卷标、错身份、过期挂载、空序列号及 UF2；Mac/Linux
真实脱机写入和重枚举仍待客户候选包复测。Linux DEB 携带限定 VID/PID 的 udev 规则；
AppImage 同目录提供该规则，权限配置需客户按实际发行版管理。

## 候选交付

四个安装文件已下载到主工作区 `.build/artifacts/v032-desktop-candidates/`，归档 CRC 和
安装文件 SHA-256 均验证通过。同目录附客户复测说明、Linux 规则和汇总 SHA256SUMS.txt。
原生构建、包内资格检查成功，不替代客户的实际 USB/脱机写入/安装验收。

| 文件 | SHA-256 |
| --- | --- |
| Mklink-AI-Probe-v0.3.2-aarch64-apple-darwin.dmg | `50187b51faf2b968ec8f376c8dae7e8817583bd184335334c766b8157e27d84d` |
| Mklink-AI-Probe-v0.3.2-x86_64-apple-darwin.dmg | `209f3118535ee607e56be026dfad9c9172111e4e999a48ad4a41c0dfd0a8a130` |
| Mklink-AI-Probe-v0.3.2-x86_64-unknown-linux-gnu.deb | `c95c16a50b2bed392d3b4d8be7fcbe47c0fc7f83257af80742d85566b63d60bb` |
| Mklink-AI-Probe-v0.3.2-x86_64-unknown-linux-gnu.AppImage | `f75c33271b260e62026c8821cf810aa47768bf962eda7019dd6aa98aa70a0392` |
