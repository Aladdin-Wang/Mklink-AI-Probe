# AI 项目记忆设计

## 目标

让 Codex、Claude、Gemini 或其他代码模型在没有原始聊天记录时，仅靠 Git 仓库即可恢复项目目标、当前断点、验证证据、硬件约束和下一步动作，并在每次会话结束时持续更新这些信息。

## 结构

- `docs/ai/project-memory.json`：机器可解析的单一事实源。只保存结构化事实，不保存推理过程或原始大日志。
- `docs/ai/project-memory.schema.json`：稳定字段契约，阻止关键上下文被随意改名或遗漏。
- `docs/ai/CURRENT_HANDOFF.md`：面向人和模型的快速入口，由 JSON 中的事实同步而来。
- `scripts/ai_memory.py`：无第三方依赖的校验与 Markdown 渲染工具。
- `AGENTS.md`、`CLAUDE.md`、`GEMINI.md`：不同模型的仓库入口，统一要求会话开始读取记忆、结束更新记忆。

## 更新协议

1. 会话开始先运行 `python scripts/ai_memory.py validate`，再读 `CURRENT_HANDOFF.md` 和当前计划。
2. 开始工作前，把 `current_session.status` 改为 `in_progress`，记录当前任务与基线提交。
3. 每个可验证检查点更新提交、测试和限制；不把计划结果写成已经完成。
4. 会话结束前更新 JSON，运行 `python scripts/ai_memory.py render`，再运行 `validate`、`git diff --check`，提交并推送当前分支。
5. 若会话异常中断，下一模型以 Git HEAD、测试结果和 `current_session` 三者交叉核对，不盲信陈旧字段。

## 安全与体积

- 探针 ID 只保留型号和末四位；不记录 COM 端口、令牌、用户名路径或凭据。
- 只记录小型摘要、哈希和可重复命令；截图、构建产物、Pack 和原始采集日志不进入 Git。
- JSON 的 `updated_at`、`head`、`working_tree` 和 `next_actions` 是每次交接必须更新的最小字段。

## 验收

- JSON 可被标准库解析并通过本地校验器。
- Markdown 可由 JSON 确定性重建。
- 新模型无需聊天记录即可找到工作树、分支、当前提交、已完成任务、未完成任务、硬件路径、验证命令和已知风险。
- 入口文件明确规定收尾更新流程，形成持续演进的项目记忆。
