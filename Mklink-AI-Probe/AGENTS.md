# Repository Agent Protocol

Resolve the project source root before using any relative path in this file.
The source root is the directory containing this `AGENTS.md`,
`docs/ai/project-memory.json`, `scripts/ai_memory.py`, and
`skills/maintaining-mklink-ai-probe/SKILL.md`. It may be a direct child of the
Git/workspace root. Do not assume the current working directory or Git
top-level is the source root.

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

## Prerelease Branch Workflow

- Maintain features, fixes, tests, and documentation continuously on the active
  prerelease branch recorded in project memory (currently
  `codex/v0.1.9-development`). Do not create a branch or worktree per issue, and
  do not restart each fix from `master`. A new release branch requires an
  explicit maintainer request.
- Before editing, reconcile the working tree and fetch the corresponding
  GitHub branch. Preserve unrelated changes; resolve divergence without force
  pushing or rewriting shared history. Never develop directly on `master`.
- Finish one issue at a time: run the affected regression checks and applicable
  build/real-surface verification, update project memory, and run
  `git diff --check`. Commit each completed fix separately and promptly push it
  to the matching branch on GitHub `origin`; do not accumulate unrelated fixes
  locally. The maintainer gives standing authorization for these prerelease
  commits and pushes. Verify the remote tip after pushing and report failures.
- Record unavailable checks and existing environment failures honestly. A
  prerelease push is not evidence that the complete release gate passed.
- Merging into `master` still requires explicit maintainer authorization and
  the full final gate below. If `master` advances or code changes after final
  verification, incorporate the changes and rerun that gate before merging.
  After merging, verify that `master` contains the tested prerelease tip,
  project memory validates, and the working tree is clean.

## Authority

- Make the smallest change that fully solves the developer's actual need.
- Before changing a product, interaction, architecture, workflow, or testing
  strategy, present the observed problem, viable options, tradeoffs, recommended
  choice, and concrete acceptance criteria to the maintainer. Do not implement
  the strategy until the maintainer explicitly confirms it. Once a strategy is
  confirmed, root-cause fixes that preserve it may proceed without asking again.
- Ask only when ambiguity materially changes the result or requires new
  authority; otherwise use a small reversible assumption.
- Never discard unrelated user changes.
- Never infer authority to sign or publish a release. Official release and
  Gitee synchronization are maintainer-only operations described in the skill's
  `references/releasing.md`.

## Build Storage (maintainer requirement)

- All build/test scratch data belongs in the main checkout's ignored `.build/`
  directory, currently `E:\software\HPM5300\Mklink-AI-Probe\.build`.
  Worktrees share this location. Never use C: or the Windows system drive.
- Run build/test commands through `scripts/build_workspace.ps1`; see
  `docs/ai/build-storage.md`. Do not create ad hoc build or pytest directories
  in skills, source directories, `%TEMP%`, or other drives.
- Preserve reusable compiler/dependency caches. Remove per-run temporary files
  after verification; leave logs in `.build/reports/`. Never commit or upload
  `.build/`, caches, installers, temporary environments, or hardware logs.
- Preserve the checked-in `gui/dist` runtime assets and official release
  assets. For inaccessible paths or directory links, stop automatic deletion,
  report exact paths, and let the maintainer clean them manually.

## Final Verification

For every runtime or user-facing feature and bug fix, run the full Python and
GUI suites plus the production build on its branch before merge. Complete a
real-hardware closed loop on the affected Web, Tauri, or device workflow before
merge and release; mocked or component tests alone are not integration or
release evidence. If the required hardware surface is unavailable, stop and
obtain an explicit maintainer waiver instead of silently reducing the gate.

Run the required verification and `git diff --check`. Update
`docs/ai/project-memory.json`, then run `python scripts/ai_memory.py render` and
`python scripts/ai_memory.py validate`. Commit and promptly push each completed
fix under the prerelease workflow above, and leave the worktree clean. This
standing push authorization does not cover merging `master`, tags, signing,
release publication, update-channel pointers, or Gitee synchronization.
