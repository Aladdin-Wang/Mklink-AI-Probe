# 0.3.4 正式发布交接

维护者明确授权覆盖本地安装、更新本地 Skill 和正式发布。PR [40](https://github.com/MicroKeen/Mklink-AI-Probe/pull/40) 的精确头 `68f5f7be2362` 三项检查通过后合并，正式源及不可变 `v0.3.4` 标签为 `a8fd3fab04034f06b95e1cdf2e03a518af297358`。合并树与已检查的 PR 头完全一致。正式 Web 资源和交接已通过 PR [41](https://github.com/MicroKeen/Mklink-AI-Probe/pull/41) 合入，合并提交 `185678c59623`；发布标签未移动。后续工作区整理见 [清理记录](v034-workspace-cleanup.md)。

## 发布与本地更新

- [正式下载](https://github.com/MicroKeen/Mklink-AI-Probe/releases/tag/v0.3.4) 含 Windows NSIS、两种 Mac DMG/更新 tar、Linux AppImage/DEB、五份更新签名、Skill、Windows Site Agent 和完整性文件，共 17 个附件。
- 正式文件与验证证据保存在配置的 `MKLINK_BUILD_ROOT/artifacts/v034-official/`，原生附件在相邻 `v034-official-native/`。主工作区磁盘空间有限，保留构建根归档，不重复复制到源码盘。
- 本机先从 0.3.3 实际覆盖安装候选，再覆盖最终主线 NSIS。两次安装器均退出 0；最终安装目录三个核心载荷 SHA-256 与最终安装包一致，版本 0.3.4。
- 本地 Skill 已更新 0.3.4，所有发布 ZIP 文件逐字节一致，离线 CLI、F407VE 外设目录和真实 stdio MCP 通过。旧 Skill 已备份在构建归档，已运行的 AI 进程需重启加载新代码。
- 保留既有更新公钥、应用标识及全部旧更新端点。本次未修改供电或烧录探针固件。

## 验证证据

Python 全量回归及受影响文件复跑合计 4800 通过、2 跳过，保留早先失败记录，不声称单次全绿；GUI 两轮全量各 89 文件 / 941 项通过。合并前 CI 的后台合同测试 2964 通过（406.60 秒），GUI/生产构建和 feedback-contract 通过。新增的 CI 失败来自 pymodbus 3.16 将串口 OSError 包装成 ConnectionException，测试兼容两类传输失败而保留单次请求、配置恢复及终止扫描断言；3.13/3.16 各 15 项通过，未改产品行为。

最终已安装程序在 Windows-only PATH、无外部 Pack 环境下通过冻结 CLI、MCP、跨解压目录稳定外设 ID、38 个生产 Web 文件字节/MIME、健康检查与正常退出；无 Python 子进程。原生窗口和实际浏览器均显示 `0.3.4 · a8fd3fab0403`，浏览器无控制台错误，正常关闭后测试后台及端口释放。

最终安装后 V3/F103 原测试工程 ELF 复核：30 MHz / 1 ms、两波形与 RTT 并行，24 次写应答且 verified=false，5766 个采集周期零读错误、47 行 RTT。同后台两探针切换、旧 AI 会话失效、共享采集断开、SDK 往返切换均通过，后台 PID/端口/实例保持不变。第二只下载器未接目标板。独立双后台占用保护和互不影响的实物证据来自同运行时代码的候选。SystemView 最终短测 54 字节 / 0 事件只证明启动/断开生命周期；较早候选短测 6230 事件，不代表长期性能。

正式 macOS ARM/Intel/Linux 均来自同源 [CI 38144587775](https://github.com/MicroKeen/Mklink-AI-Probe/actions/runs/38144587775)。各原生归档 ZIP CRC、清单源提交、全部文件大小/SHA-256、冻结 CLI/MCP/Web/正常退出资格报告已核对。五份更新签名用既有公钥实际验签。Mac 为 ad-hoc 签名、未做 Developer ID 公证；Windows 无 Authenticode 发布者签名。Mac/Linux 物理 USB/MSC 及原地升级仍按维护者先前决定由客户后验。

最终 Windows Site Agent 冻结包另外完成两个生命周期测试（22.58 秒）：启动、重启、相邻实例隔离、退出清理及不依赖外部 Python；载荷和清单均来自最终正式源。

## 资源与渠道

正式 NSIS 为 176582092 字节，比 0.3.3 多 24723 字节。0.3.3 相比 0.3.2 的体积增量约 99.9% 来自补齐的 Pack/SVD。73 个 Pack 的摘要、许可、PDSC 引用、ZIP 内容无缺失或重复条目，0.3.4 内置 2299 项 FLM/Pack 与 0.3.3 逐字节一致。7059 FLM 目标、2224 blobs、4800 SVD 目标完整；少量有运行时引用的算法重叠不删除。详见 [体积审计](v034-package-size-audit.md)。

两个 GitHub 仓库各 17 个附件匿名完整下载并校验后，最后更新三个渠道索引。MicroKeen/release、旧 GitHub/updates、Gitee/updates 均回读为 0.3.4，五个平台 SHA-256、大小、签名及 Skill 源提交一致。

按维护者最新要求，Gitee 尝试上传 Windows 安装包和 Skill ZIP，其他 15 个附件仅在 GitHub 发布。Gitee 明确拒绝 176582092 字节 Windows 安装包，HTTP 400 原因是“文件大小已超出限制：100 MB”，因此安装器索引回退到 GitHub。98690236 字节 Skill 已成功上传 Gitee 并完成匿名下载核验，确保 GitHub 不可达时 AI 有实际备用载荷；没有用 GitHub URL 冒充 Gitee 回退。Gitee 实际附件 1 个，实际附件列表已回读核对。安装后的 Skill 更新脚本另经进程内模拟 GitHub 断网、真实 Gitee 索引和完整 Skill 下载校验。

客户原始持续 MUX 超时、30 MHz 并行读错及其他芯片场景仍需现场复核；本地修复和回归不等于每个客户问题根因闭环。既有固件性能限制及其他长期未验证项保留，不扩大本次应用发布范围。

## 正式载荷

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `MKLink-Site-Agent-v0.3.4-windows-x86_64-portable.manifest.json` | 2391 | `a492e4192cc0d1e510ff84d25ca6edf66d3c93b7ca37440aa48607f96402814b` |
| `MKLink-Site-Agent-v0.3.4-windows-x86_64-portable.zip` | 66902355 | `1477f8d5714f60bf349227b9c082dc487929dd9028d2ea9d91fb792776323b7f` |
| `Mklink-AI-Probe-v0.3.4-Skill.zip` | 98690236 | `a74e9536390e3c703c4bd25121854ba3ffd8e27b842385179f9f18cc3db03b64` |
| `Mklink-AI-Probe-v0.3.4-aarch64-apple-darwin.app.tar.gz` | 164970893 | `b04e4c4b59a0c787b5f75830cfdb5d0b7ae9b99f7bfceccac4917cf7e05c0eac` |
| `Mklink-AI-Probe-v0.3.4-aarch64-apple-darwin.app.tar.gz.sig` | 452 | `1657d26b90e2131c5ef714ede3afc15599df190327e562bac15f1d6413f9fc35` |
| `Mklink-AI-Probe-v0.3.4-aarch64-apple-darwin.dmg` | 165232510 | `cab4a5386ebf8734db00e1a54af5048586ed8b86baeda46375c7e48ff9862f43` |
| `Mklink-AI-Probe-v0.3.4-x64-Setup.exe` | 176582092 | `5f7a2666e3b04e9f2653feb16c419051066eac62d326b57f237a56ca5eb4be62` |
| `Mklink-AI-Probe-v0.3.4-x64-Setup.exe.sig` | 428 | `d131c00a61ae6a2f2390cb932d6340ee71fa6a12e03c703b41e131043583cbd2` |
| `Mklink-AI-Probe-v0.3.4-x86_64-apple-darwin.app.tar.gz` | 165396219 | `519e955d1d1de350e60c460debe286b3a07c571a4ccd6faa675b24a7735fa858` |
| `Mklink-AI-Probe-v0.3.4-x86_64-apple-darwin.app.tar.gz.sig` | 452 | `d7a1695458baf08b17023f60289b391c8167398292c8abd44d514a0e34204eae` |
| `Mklink-AI-Probe-v0.3.4-x86_64-apple-darwin.dmg` | 165618719 | `32ae210e410f1f8f46945227774a6b34fd305cabad0fca8b3341fa4f78b8ce8a` |
| `Mklink-AI-Probe-v0.3.4-x86_64-unknown-linux-gnu.AppImage` | 261544440 | `2f748104a681bfe280ba9e1d4ef0b18e2307c4f103371ed6adb3e4973db9760e` |
| `Mklink-AI-Probe-v0.3.4-x86_64-unknown-linux-gnu.AppImage.sig` | 456 | `9fe2fc59b9d30d0d3b33d08352d36aab65495981d0655991a7c4e4199feb8697` |
| `Mklink-AI-Probe-v0.3.4-x86_64-unknown-linux-gnu.deb` | 183654332 | `40fd085d2cc8a5de7312f412869197a6dd8252a639ee77eade406633a464193f` |
| `Mklink-AI-Probe-v0.3.4-x86_64-unknown-linux-gnu.deb.sig` | 448 | `347ef49f9b9a676b689a417dfd0fc7469ebab1adee5ecb6e5bd80e97533823f9` |
