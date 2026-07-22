# Repository Agent Protocol

All coding agents and models must use the repository-bundled skill at
`skills/maintaining-mklink-ai-probe/SKILL.md`. It is the shared maintenance
workflow; global or user-installed skills are optional and must not be required
for another contributor to continue the work.

## Start

1. Run `python scripts/ai_memory.py validate`.
2. Read `docs/ai/CURRENT_HANDOFF.md` and `docs/ai/project-memory.json`.
3. Run `git status --short --branch`, `git log -12 --oneline`, and
   `git worktree list`; reconcile live state with the handoff.
4. Read and follow `skills/maintaining-mklink-ai-probe/SKILL.md`.

Do not modify code or repeat completed work until the current state is clear.
If repository memory is stale, verify reality and correct the memory.

## Authority

- Make the smallest change that fully solves the developer's actual need.
- Ask only when ambiguity materially changes the result or requires new
  authority; otherwise use a small reversible assumption.
- Never discard unrelated user changes.
- Never infer authority to sign or publish a release. Official release and
  Gitee synchronization are maintainer-only operations described in the skill's
  `references/releasing.md`.

## Finish

Run proportional verification and `git diff --check`. Update
`docs/ai/project-memory.json`, then run `python scripts/ai_memory.py render` and
`python scripts/ai_memory.py validate`. Commit and push when authorized, and
leave the worktree clean.
