# V2 RBL 固件更新兼容与实机验收

2026-10-18：接续 V2 固件会话，维护者授权发布既有已验收的 V2.9.0 RBL，
补齐上位机自动升级并验证真实版本变化。未改 Bootloader、分区或目标板固件。

## 行为

- V2 使用正常运行的 MICROKEEN 卷。校验 RBL 名称/型号、包头版本、分区、CRC32、
  长度、对齐和应用元数据边界，再复制一次，由现有固件提交并重启。
- 共享后台在复制前重新核对 USB 身份及卷，关闭已有 CDC/MUX，拒绝正在采集、
  AI 会话、独占任务和盘上遗留 RBL。不进入 UF2 模式，不重放结果未知的复制。
- 只有原 USB 身份重新报告期望版本才返回 updated；同版/更新版本返回 up_to_date。
  复制后未确认版本返回 copied_unverified，禁止据此自动重试。
- Web、CLI `runtime firmware check|upgrade --probe ...` 和 MCP `probe_firmware`
  复用同一 API。升级必须明确 confirm，操作本身不创建目标调试会话。
- V2 单独使用 latest-v2.json。旧 latest.json 完全不变，保留 V3/V4 UF2 客户端兼容性。
  Gitee 尚未发布 V2 独立索引；本次 V2 在线来源为 GitHub。

## 发布

原已验收文件仅改发布名称为 `MicroLink_V2.9.0.rbl`，未重新打包：

- 长度 364216 字节；载荷 364120 字节。
- SHA256：`eec5199ec0d9073485e883fa7020c851d24fb36e029f0fca14b19fa1be667d57`。
- MicroKeen firmware 索引提交：`5b496dd3851273dde8b5a78fc2baaf91b191c34e`。
- Aladdin-Wang 兼容索引提交：`aafb99f6ae4fd6ad7e97b450210bc0e2dea0d82a`。
- 两处 firmware-assets 附件匿名下载的大小/SHA256 均匹配。旧索引 blob 保持不变。
  兼容索引首次 PATCH 遇网络 EOF，读取确认 ref 尚未变化后才继续发布；不盲目重放。
  发布器只增加独立索引和新附件，使用非强制 ref 更新，不改既有标签或附件。

## 验证

- 核心固件/卷/共享后台/MCP 组 158 项通过；CLI 及相关组 127 项通过；
  最终新增发布树与 HTTP RBL 下载覆盖后，V2 专项 29 项通过。各组有重叠，不相加。
- GUI 配置/API 62 项通过，TypeScript 与生产 Vite 构建通过。
- 用户自行回退后，同 USB 身份 readme 确认 V2.8.0。新版生产 Web 点击升级，
  经 GitHub 下载、校验和 MSC 复制，页面确认“升级完成：V2.9.0”。
- 实际 CLI 检查返回 V2.9.0；实际 stdio MCP 检查一致，同版升级返回 up_to_date。
  MCP 连接后识别 F103，CPUID 读取 `31c21f41`，随后 detach。没有把同版检查算作升级。
- 本地遗留 V2.8.0 包头为 V1.0.0 且未对齐，本会话未写入该旧包；回退由用户完成。

本地证据保存在构建根 `artifacts/v035-v2-rbl`。本轮是 V2 固件发布及 Windows 针对性
验证，不是 0.3.5 上位机正式发布，不替代全量/跨平台/全部芯片验收。

## Windows 安装与 Skill

- 运行代码/安装包标记 `5be3dcf7`，生产 Web 与 Skill 归档提交 `6ddd59ab`。
- NSIS 覆盖安装退出 0，提取及安装后 198 份 Python、40 份 Web 与源码一致，
  GUI/sidecar/STCP/notice 四份载荷与安装包一致。
- 安装包 SHA256：`4d41a9c02ba63c1ce64cd9adbcd0ab6049063874747b57b59e975310a93dde86`。
- 冻结环境 Windows-only PATH 下 CLI、SVD、实际 stdio MCP、HTTP 和退出检查通过；
  全局 Skill 2605 文件与归档一致，CLI、SVD、实际 MCP 通过。
- 安装版生产 Web 显示 V2.9.0 和“当前已是最新固件”。安装版冻结 MCP 与全局 Skill
  MCP 均检查同版并返回 up_to_date，随后连接 F103、读取 CPUID `31c21f41` 并 detach。
  全局 Skill CLI 版本检查一致。同版检查没有被计为第二次升级。
- AI 会话已退出，共享后台已显式释放下载器；原生窗口关闭与退出核对待用户完成。

安装证据保存在构建根 `artifacts/v035-local-5be3dcf7`，未将本机路径、硬件身份、
截图或安装包提交到源仓库。保留旧 Skill 备份；含联接的测试临时目录不强制删除。
