# 0.3.4 发布后工作区清理

维护者授权清理构建垃圾、保留 0.3.4 修复分支并精简交接。本轮不改产品代码、不重新发布、不操作下载器；发布资格仍以 [正式交接](v034-release-handoff.md) 为准。

## 分支

清理基线为 `microkeen/main` 的 `185678c59623`（PR41 已合入）。保留 `codex/0.3.4-fixes`，先快进至该主线，再提交本轮交接整理。删除前确认只有主工作树、没有未关闭 PR，以下分支的本地/远端提交一致，且均为主线祖先；随后删除本地及 `microkeen` 同名分支。

| 已删除分支 | 删除前提交 |
| --- | --- |
| `0.3.3修复分支` | `20bdba19684323d8a241fecd8e0de263eae231c3` |
| `codex/0.3.1-fixes` | `dac0a6c1ecf3aaa6454daa54da5c668339ad96cf` |
| `codex/0.3.2-fixes` | `83ed5334dd26a6e399e5b5779c605ad8d18ec18d` |
| `codex/0.3.4-release-handoff` | `3fdfb99f90b8eb1ad04c93560089adba2c3b76a1` |
| `codex/v033-intel-dmg-diagnostics` | `81fd430c80961e4eadc9c0b0e1a7b1fea8be62de` |

历史提交仍可从 main 追溯。main、release、firmware、全部标签及其他贡献者仓库均未删除；`v0.3.4` 仍指向 `a8fd3fab04034f06b95e1cdf2e03a518af297358`。

## 构建文件

共删除 615 个清单路径，按删除前文件长度回收 **3,635,787,546 字节（约 3.64 GB / 3.39 GiB）**，无删除失败。原工作区 `.build` 为 990,485,633 字节，另一个配置构建根为 2,645,301,913 字节。此数字不包含发布阶段已清理的下载分片。

- 清理结束的无联接 run，以及含联接 run 内单独核对安全的 tmp/work/pytest-cache 子目录。
- 清理正式安装包、Skill、Site Agent 的重复副本；重复文件逐份核对 SHA-256 后保留 canonical release 文件。
- 清理原生 CI 归档的大体积解压载荷；先核对完整 ZIP 的 GitHub 摘要，再核对每个被删文件与 ZIP 条目大小/摘要，完整 ZIP、报告和清单保留。
- 清理旧候选安装包的解压目录、体积审计解压基线及旧生成 Web 文件；保留原安装器、截图、日志和真机证据。

全程持有两个构建根的独占清理锁；删除前确认绝对路径在指定构建根内、祖先及内容无联接且无运行中的载荷。使用 PowerShell 原生路径删除，未执行通配符全盘清理或强制绕过权限。

**保留项：**全部正式 release 及三平台完整 CI ZIP、旧正式归档、用户/Skill 备份、客户现场资料、唯一 HIL/回归证据、共享依赖/缓存、固件/Pack/FLM 和受跟踪 `gui/dist`。同大小但摘要不同的中间 Skill ZIP 未按重复文件删除。

**仍需人工处理：**150 个历史 pytest run 含联接，联接所在目录未删除；本轮边界检查另产生 1 个含测试联接的 run，同样保留。旧 0.3.3 安装器占用的内容未动。清理前树清单、保留路径、删除计划与结果、分支提交快照及旧记忆快照保存在配置构建根 `reports/v034-cleanup-*.json`、`v034-deleted-branches.json`、`v034-memory-before-cleanup.json`，不上传本地路径或日志。

## 交接与验证

精简 `project-memory.json` 并重新生成 `CURRENT_HANDOFF.md`：删除重复的逐轮测试叙述，修正协议为 52、PR41 已合入及固定窗口后台决策，保留客户未闭环问题、Gitee 100MB 限制、供电权限和长期验证暂停状态。历史报告继续保留。

交接正文由 7,983 字符压缩到 3,758 字符。记忆 render/validate、生成结果一致性及 11 个相对链接通过；`test_ai_memory.py`、`test_issue_queue.py`、`test_skill_context_boundaries.py` 合计 **70 通过**。17 个正式载荷重新核对大小及 SHA-256，全部一致；615 个已删路径均不存在。`git diff --check`、远端分支及标签核对通过。没有运行无关产品全量回归或新增硬件测试。
