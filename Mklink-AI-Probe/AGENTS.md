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

## Branch Workflow

- Before editing a runtime or user-facing feature or bug fix, start from a clean,
  current `master` and create a dedicated `feature/<topic>` or `fix/<topic>`
  branch. A separate worktree is optional; the branch is mandatory.
- Do not develop or commit feature and bug-fix work directly on `master`.
  Documentation-only maintenance and release handoff work are exempt unless the
  maintainer requests a branch.
- Complete the required automated tests, production build, project-memory
  update, and affected real-hardware closed loop on the feature or fix branch
  before merging it into `master`.
- If `master` changes after final verification, update the branch with the
  current `master` and rerun the final gate. Any implementation or conflict
  resolution after verification invalidates the old evidence.
- Merge only after the branch passes its final gate. After merging, verify that
  `master` contains the tested branch tip, project memory validates, and the
  worktree is clean. Push only when authorized.

## Authority

- Make the smallest change that fully solves the developer's actual need.
- Ask only when ambiguity materially changes the result or requires new
  authority; otherwise use a small reversible assumption.
- Never discard unrelated user changes.
- Never infer authority to sign or publish a release. Official release and
  Gitee synchronization are maintainer-only operations described in the skill's
  `references/releasing.md`.

## Finish

For every runtime or user-facing feature and bug fix, run the full Python and
GUI suites plus the production build on its branch before merge. Complete a
real-hardware closed loop on the affected Web, Tauri, or device workflow before
merge and release; mocked or component tests alone are not integration or
release evidence. If the required hardware surface is unavailable, stop and
obtain an explicit maintainer waiver instead of silently reducing the gate.

Run the required verification and `git diff --check`. Update
`docs/ai/project-memory.json`, then run `python scripts/ai_memory.py render` and
`python scripts/ai_memory.py validate`. Commit and push when authorized, and
leave the worktree clean.
