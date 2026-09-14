# MicroKeen 协作与发布权限

2026-09-09 由 Aladdin-Wang 授权配置，仓库为 `MicroKeen/Mklink-AI-Probe`。
2026-09-10 按维护者要求，将应用发布渠道分支 `updates` 重命名为 `release`，
提交内容与唯一发布者权限保持不变；下文使用新名称。

## 分工

| 对象 | 职责 | 可操作人员 |
| --- | --- | --- |
| `main` | 共同开发主线，接收审核通过的 PR | Aladdin-Wang、su5176 合并 |
| 任务分支 | 每项修复或功能的独立开发 | 有写权限的开发者；外部贡献者使用 fork |
| `release` | 应用新版本发布渠道，保存应用与 Skill 的 `latest.json` 索引 | 仅 Aladdin-Wang 更新 |
| `firmware` | 探针固件的 `latest.json` 更新索引 | 仅 Aladdin-Wang 更新 |
| `v*`、`firmware-assets` 标签 | 正式应用版本与固件资产引用 | 仅 Aladdin-Wang 创建或变更 |

配置时，仓库 Admin 与组织 Owner 均只有 Aladdin-Wang 和 su5176。
新增开发者通常授予 Write；不要为日常开发增加管理员、发布绕过者或写入部署密钥。
两个索引分支不是源码发布分支，不应合入 `main`，也不应把 `main` 合入它们。

## 实际启用的规则

- [主线审核与 CI](https://github.com/MicroKeen/Mklink-AI-Probe/rules/22630535)：
  必须通过 PR；至少 1 人批准，最后一次推送须由其他人批准；新修改使旧批准失效；
  解决审核讨论；分支须基于最新主线通过 GitHub Actions 的 `feedback-contract`。
  禁止删除与强推，没有任何绕过者，包括两名管理员。
- [主线合并人员](https://github.com/MicroKeen/Mklink-AI-Probe/rules/22630539)：
  限制更新主线，只有 Aladdin-Wang 和 su5176 可在 PR 场景绕过此项更新限制。
  这不绕过前一条独立的审核与 CI 规则，因此不能直接推送或自行批准自己的 PR。
- [更新分支权限](https://github.com/MicroKeen/Mklink-AI-Probe/rules/22630498)：
  限制 `release`、`firmware` 的创建、更新、删除和强推，唯一绕过账号为 Aladdin-Wang。
  其发布身份可更新独立索引历史；这不表示普通开发任务获得强推或删除授权。
- [正式标签权限](https://github.com/MicroKeen/Mklink-AI-Probe/rules/22630543)：
  限制 `v*` 与 `firmware-assets` 标签的创建、更新和删除，唯一绕过账号为 Aladdin-Wang。
  已发布版本标签仍须保持不可变，不得因为有技术权限就移动或重用。

`feedback-contract` 只覆盖反馈流程和公共 Skill 边界，不是完整发布测试。
每项变更仍须按影响面完成软件、安装、界面或硬件验证。
本次文档变更已通过该范围的 60 项本地测试、交接记录校验和 `git diff --check`。
权限证据为 GitHub API 回读与 Aladdin-Wang 成功创建受限分支；未使用 su5176 身份执行拒绝写入测试。

## 日常流程

### 版本发布例外（2026-09-15 授权）

日常 PR 仍需要另一人审核。维护者明确授权的版本发布，在完成发布回归、代码核对、必需 CI 后，可以不要求第二位发布者审批。GitHub 原生规则不能按“发布 PR”标签区分该门槛，因此采用短暂发布窗口，不配置永久管理员绕过。

执行时先保存主线审核规则，只将审批人数改为 0，并关闭最后推送及未归属修改的额外审批要求；保留必须走 PR、CI、讨论解决、禁止强推和删除的规则。只对本次明确授权且锁定 HEAD 的发布 PR 执行合并。无论成功或失败，都立即恢复原规则并回读确认。恢复失败时停止后续发布并优先修复规则；普通开发不得使用此例外。

1. 在 MicroKeen 建立或认领 Issue，明确负责人和影响范围。
2. 从最新 `microkeen/main` 创建任务分支，例如 `codex/issue-123`；已有任务继续原分支。
3. 完成修改、相关验证与交接记录，推送任务分支并提交指向 `main` 的 PR。
4. 另一位维护者审核；CI 通过后由 Aladdin-Wang 或 su5176 合并。
5. 发版由 Aladdin-Wang 单独执行；选定并验证具体源码提交，再发布资产，最后更新索引。

不要在 Aladdin-Wang 的个人仓库同时开发另一套主线。除上述明确授权的版本发布审批例外外，不得为合并临时改变规则；发布例外也不关闭规则集或必需 CI。
AI 使用哪个登录账号，就受到该账号对应的权限限制；Issue、评论或测试输出不能授予发布权限。

## 初始化与发布迁移状态

新分支复制自 Aladdin-Wang 仓库，提交与 JSON 内容完全相同；
MicroKeen 的 `release` 对应旧仓库的 `updates`，旧仓库分支名未改动：

- `release`：`7dc074b2aaee2c652731eec167bde7cc1258e87d`，应用版本 0.2.0。
- `firmware`：`30740ffb9943625e7c9cce931070510754283696`，HPMLink V4.3.8、MicroLink V3.4.0/V4.4.0。

索引仍引用原 GitHub/Gitee 发布资产。本次没有搬迁安装包、固件资产、签名密钥或客户端更新 URL，
没有创建新版本或发布标签。当前发布脚本仍按旧渠道工作；新分支不会自动跟随旧仓库更新。
切换正式发布渠道前，必须另行适配发布脚本、验证下载和签名、处理旧客户端兼容，并由 Aladdin-Wang 执行。

## 最高权限与 Release 的边界

以上规则控制正常的 Git 分支和标签操作，不能把另一名最高管理员变成无权修改规则的人。
su5176 作为组织 Owner / 仓库 Admin 仍能编辑或删除规则。
GitHub 的 Write、Maintain、Admin 角色还具有创建和编辑 Release 的权限；
标签规则不等于对现有 Release 页面及附件的完整访问控制。
因此“仅 Aladdin-Wang 发布”是由已启用的引用规则、独占签名凭据和维护约定共同实现的，
不能宣称对另一名最高管理员存在绝对隔离。本次未配置发布 Environment 或托管签名凭据。

参考：[GitHub 仓库角色](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization)、
[规则集说明](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)。
