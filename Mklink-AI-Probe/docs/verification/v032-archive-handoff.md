# 0.3.2 归档入口

2026-10-10 已正式发布。当前结论见 [正式发布交接](v032-release-handoff.md)，不再使用旧候选状态判断发布是否完成。

唯一维护入口是原 Mklink-AI-Probe 的 docs/ai/CURRENT_HANDOFF.md。Git 根 `.build/artifacts/v032-official/` 已逐项哈希核验保存正式安装包、更新签名、清单、实际 Windows 安装证据、三平台 CI 检查及渠道回读。`.build/artifacts/v032-handoff/` 保留 V3/V4 原始真机证据、唯一目标备份所在索引和旧用户文件；历史 checkpoint 文档只代表当时状态。

版本标签对应源 3d511e94742ac95ccd93c30e60349e1b560ee7a4。收尾 PR 只同步最终编译 Web 资源和交接，不重编或覆盖正式包。原 MK-Firmware 保持用户指定最新固件，不恢复旧 stash。固件交接及备份位于原 MicroLinkV3、MicroLink_Plus 工程。

临时工作树在收尾 PR 合并和主线核对后移除，实际清理实录见本地 `v032-official/cleanup.json`；缓存不视为额外维护工作空间。Mac/Linux 客户实机后验及 30 MHz 目标读错等边界以正式交接为准。
