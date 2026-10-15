# 0.3.5 本机测试包与覆盖安装

2026-10-15，用户明确要求将修复分支标为 0.3.5，重新打包、覆盖安装并同步本机 Skill。

## 版本与构建

- 版本及中英文更新记录：`bdd3c3e3ef32`。GUI 显示此构建标识，Python/runtime、桌面和 Skill/plugin 均为 0.3.5；Site Agent 源码版本元数据同步，但本轮未构建独立 Site Agent 包。
- 生产 Web 归档：`53b4ebb2`；Skill 从该提交创建。NSIS 与 Skill 的 Web 资源对应同一版本说明和功能实现。
- 通过维护构建入口生成标准 `--local-bundle` NSIS。没有读取更新签名私钥、创建版本标签、合并 main 或发布更新渠道。此包供本机测试，Windows 安装程序仍未作发布者代码签名。
- 内置资源检查：7,059 型号、2,224 去重 FLM、4,800 SVD 型号。候选和证据保存于构建根 `artifacts/v035-local-bdd3c3e3`，SHA256SUMS 已生成。

## 验证结果

- 版本/更新器/runtime 启动测试：26 passed。初跑发现 Site Agent 版本仍旧，补齐版本一致性后通过；未放宽测试。
- GUI 全量：949 passed；TypeScript、生产构建、PyInstaller 和 NSIS 构建通过。
- 解包和实际安装各验证一次：195 个 Python 源文件、38 个 Web 资源与当前代码一致；四个实际安装载荷与 NSIS 解包内容 SHA-256 一致。
- Windows-only PATH、隔离用户/Pack 目录：冻结 CLI 查询 STM32F407VE、真实 stdio MCP 初始化及 inspect_mcu/security_status、HTTP health、全部生产 Web 文件和在线探针枚举均通过。进程树不依赖 python.exe/pythonw.exe，正常退出成功。
- NSIS 实际覆盖安装退出 0；Windows 安装登记为 0.3.5。
- 实际本机 Skill：0.3.4 → 0.3.5，原版本先备份到构建证据目录，2600 个归档文件逐一匹配。editable Python 包元数据更新为 0.3.5；实际 Skill CLI、内置 SVD 查询和 stdio MCP 均通过。保留本机配置；既有 AI/MCP 会话需要重新加载后使用新版。
- 真实原生 WebView：后端正常，底栏显示 `v0.3.5 · bdd3c3e3ef32`，版本面板包含五项本轮修复。
- 真实 Edge 使用已安装冻结后台：仪表盘/SuperWatch/芯片外设正常，内置 STM32F407VE 搜索、手动 SVD 入口、版本说明通过。
- 正常关闭原生窗口后，无 MKLink 进程、runtime endpoint 和 8765 监听残留；随后重新打开常用安装版供用户测试。

本轮是打包与安装验收，没有重新操作目标板或改下载器固件。时钟/位域的既有真机证据见对应报告，用户下一步进行新包复测；不将本轮离线检查表述为新包全部硬件功能验收。客户一次性 DLL 解压权限拒绝在重启后恢复，本次未为该现象引入推测性改动。
