# 0.3.2 正式发布交接

> 发布后用户报告普通启动后台离线及 SuperWatch CDC 读取失败停采/断连。按用户最新要求，本轮仅初查、归档，留下一会话修复；详见 [发布后故障交接](v032-postrelease-incidents.md)。既有验收不代表这两项已通过。

2026-10-10：已授权完成正式发布。不可变标签 `v0.3.2` 对应 `3d511e94742ac95ccd93c30e60349e1b560ee7a4`；PR [35](https://github.com/MicroKeen/Mklink-AI-Probe/pull/35) 整合功能与固件，PR [36](https://github.com/MicroKeen/Mklink-AI-Probe/pull/36) 修正最新版本说明和日期。后续交接/生成 Web 资源提交不改变正式标签或已发布载荷。

## 维护和下载入口

- 唯一上位机工作空间是原 `Mklink-AI-Probe`；从 `docs/ai/CURRENT_HANDOFF.md` 进入，详细报告在 `docs/verification/`。
- [正式版下载](https://github.com/MicroKeen/Mklink-AI-Probe/releases/tag/v0.3.2)：Windows x64 NSIS、macOS Apple Silicon/Intel DMG、Linux x64 AppImage/DEB、各自更新载荷及签名、Skill、Site Agent。
- 原工作空间 Git 根 `.build/artifacts/v032-official/release/` 保存全部正式文件；`archive-manifest.json` 记录逐项复制后 SHA-256；`qualification/` 保存安装、原生构建、签名和渠道证据。
- `.build/artifacts/v032-handoff/` 保存此前 V3/V4 真机证据和用户旧文件备份。阶段交接是历史快照，不再作为当前状态。F 盘仅为构建缓存，正式结果无需从 F 盘或聊天记录找唯一副本。

## 最终验证

产品运行时代码自 `b06bd1d723057a2e44a1e6e5b866429deb7a298d` 后未改变，后续是固件文件、报告与静态更新说明。全量 Python 4647 passed / 2 skipped，682.98 秒；GUI 最终说明更新后重新全量运行 914 passed / 88 文件，79.87 秒；Rust 桌面 21、Site Agent 6 通过。磁盘耗尽中断的旧运行不计通过。

Windows 从正式主线完成锁定依赖和生产构建，实际 NSIS 覆盖原 0.3.1 至 0.3.2，安装器退出 0，注册版本及安装文件哈希均匹配。安装态限制 PATH 后 CLI/MCP、后端健康和 36 项 Web 资源字节/MIME 检查通过，lobby 3.420 秒；原生桌面启动 8.605 秒、无 Python 子进程。实际界面已观察到 `0.3.2 / 3d511e94742a`、日期 2026-10-10、MHz 输入和本轮六项更新说明。正常 Alt+F4 后本次主/子进程及运行端点全部退出。此为实际覆盖安装，不再沿用先前“仅提取包、UAC豁免”的结论；此安装检查未另行连接硬件。

三平台原生 [CI 38028928283](https://github.com/MicroKeen/Mklink-AI-Probe/actions/runs/38028928283) 使用同一正式源全部成功。下载 ZIP CRC、清单全部载荷 SHA-256、冻结 CLI/MCP、生产 Web、正常退出均核验。Windows、两种 Mac 更新 tar、Linux AppImage/DEB 的五个更新签名均用配置公钥实际验签。Mac/Linux 的物理 USB/MSC、实际安装与原地自升级仍由客户后验，用户明确接受先发；Mac 仅 ad-hoc 签名，未做 Developer ID 公证。签名及索引成功不等同于跨平台实机安装通过。

发布器验证两个 GitHub 仓库全部公开附件，并验证 Gitee 已有附件。Gitee 报告仓库附件 1 GB 配额已满，用户清理部分历史标签后仍不足，随后明确选择缺失镜像使用 GitHub；缺少的 Intel Mac DMG 与 Linux 载荷/签名使用已校验的 GitHub 文件，已有 Gitee 文件保持不变，再最后写入渠道。事后回读 MicroKeen/release、旧 GitHub/updates、Gitee/updates 均为 0.3.2，五个平台的文件大小、哈希、签名、Skill 来源提交均匹配。全部正式载荷和独立固件索引已核对；Gitee 当前不是完整附件镜像，Linux 自动更新从该索引跳转 GitHub，未来需有足够配额再补镜像。此次按用户授权用本地发布适配脚本完成，不修改冻结运行时代码；下次跨平台发布需先检查 Gitee 配额或明确镜像策略。不得覆盖或移动已发布标签。

## 真机回归及下版问题

最终 V3.6.4 与 V4.6.8 已完成后台固件升级、Keil 先 Run 再新启 RTT8/Watch4、暂停/单步/继续/退出、在线/脱机/共享烧录成功及失败/停止恢复、UART 并行、OpenOCD、GUI 退出 AI 接续、重连与最后客户端端口释放。详见 `v032-keil-capture-start.md`、`v032-v4-final-closure.md`。两台目标最终 512 KiB SHA-256 均为 `c1e51c22ae9530ee4afea9042ff6e710421bc24b6d8bf8ddd6e0992794a18bf8`。未改 VCC，已释放设备。

V4.6.8 在 30 MHz RTT8/Watch4/UART 并行时，1 kHz / 最大速率分别有 +1 / +273 目标读错；10 MHz 两档为 0。旧 V4.6.6 原始记录也有 +1 / +224，原报告漏计已更正。上位机不停止采集、不误报断开、UART 完整。这是待归因的目标读取问题，不能称为上位机接收队列字节丢失，也不能声称 30 MHz 无损。用户明确接受继续发布，限制仅交接，下版处理。此前 30 MHz Flash 连续读取偶发 status 5 同样未证明完全修复。

V3 不带屏幕；V4.6.4 Keil 断点时屏幕由用户确认已连接，但不冒作 V4.6.8 屏幕实测。完整 SES、外部 RS485 夹具、真实 Modbus、旧固件无 bootloader 命令硬件、多物理主机与全部芯片/拔插/睡眠场景未全覆盖。HPM/SES 未发 DAP_Disconnect 的占用可能遗留，不能任意超时抢走 IDE 所有权。VCC 后续仍须每次确认具体电压，只回烧已备份的已知程序。

## 固件与工作空间

| 文件 | SHA-256 | 证据边界 |
| --- | --- | --- |
| MicroLink_V3.6.4.uf2 | `06e7a6b9a0116627eab57b8b93913ffb0f0b05ae95ba271473f3aef6ba7ccc6a` | 最终 V3 真机矩阵 |
| MicroLink_V4.6.8.uf2 | `9e97abd8d5fdbe964d7bff35e06ac13ae76c8e191c0ae90bda61141ec2c570bb` | 最终 V4 真机矩阵 |
| HPMLink_V4.6.8.uf2 | `36d004edb2016f040a4cd4d9757faf9fbdb2b36664e3e165f672faea33c912be` | 用户指定编译包，UF2/公开下载校验；未单独 HPM 真机复测 |

原 `MK-Firmware/` 与 GitHub 保持上述最新版，按用户最新要求不恢复旧用户固件。旧文件和二进制补丁在 `v032-handoff/original-user-files/`；对应 stash 仅备份用途，不要自动 pop。

固件已回原 MicroLinkV3/main `409c6071f6dccd313ef1769b7665c1545cde80fc` 和 MicroLink_Plus/main `78e4027d00751a2ebe2c9852a9d3abea0005c164`，与各自远端核对；保留原用户 Arm-2D/MicroBoot 子模块改动。固件会话已归档并删除 V4-fixes 工作空间，原固件工程 `firmware-releases/` 保存必要记录。

本交接及正式编译 Web 资源经 PR 合入 main 后移除 031、desktop-platforms 临时工作树；实际路径、忽略文件盘点、分支已合入证明和删除结果记录于原工作空间 `.build/artifacts/v032-official/cleanup.json`。后续仅维护原上位机及原固件工程，保留必要证据和依赖缓存，不删除项目测试源码。后台自动跟进维持暂停。

## 正式载荷清单

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `Mklink-AI-Probe-v0.3.2-aarch64-apple-darwin.app.tar.gz` | 81654434 | `f406c7a066ba17bc7d47b96148eb3be80a0a96e6901341db32cd385482c1b651` |
| `Mklink-AI-Probe-v0.3.2-aarch64-apple-darwin.app.tar.gz.sig` | 452 | `2383c3c592234eb6f8cad495ba5097b066461f07647f5dea62fe59cf9aa97418` |
| `Mklink-AI-Probe-v0.3.2-aarch64-apple-darwin.dmg` | 81960110 | `8ef678b19fa1ac5b5c29081e81889a803aab94aff45cc249bad246663b57f028` |
| `Mklink-AI-Probe-v0.3.2-Skill.zip` | 18766670 | `b5b7eb989d171cdfdcff36d1b21c2572ccbf1181f7967fd56a2ee0a00dc7dca1` |
| `Mklink-AI-Probe-v0.3.2-x64-Setup.exe` | 96829674 | `3e72fae43380f7b060aac2c44b2f7e813259c7dd2e33f3ea59b78d41d46a2498` |
| `Mklink-AI-Probe-v0.3.2-x64-Setup.exe.sig` | 428 | `d07130623e1d51ad7669c6ea2af0c951cff070c97edc68200182cc2d46113f6c` |
| `Mklink-AI-Probe-v0.3.2-x86_64-apple-darwin.app.tar.gz` | 82083534 | `29b2e5d8b38dfd380c70a10bd33f44f09e1ab551e80f8b5ec6af3181c8ee9c39` |
| `Mklink-AI-Probe-v0.3.2-x86_64-apple-darwin.app.tar.gz.sig` | 452 | `88cc3542a95032611d592b80db7b943e97cc846675b864785828307fc3d23eac` |
| `Mklink-AI-Probe-v0.3.2-x86_64-apple-darwin.dmg` | 82349511 | `25dd813350bcc0c3e0bb87269ae9a061c90a7f47c50bf99418fa8c7e252a22f7` |
| `Mklink-AI-Probe-v0.3.2-x86_64-unknown-linux-gnu.AppImage` | 178919928 | `d834479a1b9bc0d3af69f77e8a6dc44d1b0af20935b38e2c164a8163ae3021f5` |
| `Mklink-AI-Probe-v0.3.2-x86_64-unknown-linux-gnu.AppImage.sig` | 456 | `26c72e8cb526b86bd2064d6f7900d3e2150180875ee8ebc5ed96f2c68ab9f053` |
| `Mklink-AI-Probe-v0.3.2-x86_64-unknown-linux-gnu.deb` | 100979670 | `a71596a1b580459fba3486c8fe93694196ee8f5bc55f7ecc88132255639cc401` |
| `Mklink-AI-Probe-v0.3.2-x86_64-unknown-linux-gnu.deb.sig` | 448 | `f979ab807b0c8fb8bb1eb3197297c3b6ff0eb15355398eb09080023031e75085` |
| `MKLink-Site-Agent-v0.3.2-windows-x86_64-portable.manifest.json` | 2391 | `501cfe9242992f548b02ea13643ca48136b6dd3928e96eab1cb9be2913eba778` |
| `MKLink-Site-Agent-v0.3.2-windows-x86_64-portable.zip` | 66865098 | `02ec7ed659160d2d052b74b7d7b6449bca9a0cf8f5eb355c37f92dccacd78ad4` |
