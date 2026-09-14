# MKLink Repository Maintenance

These rules apply when the user asks to change or maintain MKLink itself.
Installing or using MKLink to flash/debug another project is an end-user task:
use the root `SKILL.md`, without loading repository memory or build/release
workflows. Do not copy this file or maintainer skills into a user installation.

Paths below are relative to the source root containing this file and
`scripts/ai_memory.py`; it may be one level below the Git root.

## Start And Authority

- On first entry, read `docs/ai/CURRENT_HANDOFF.md`, validate it with
  `python scripts/ai_memory.py validate`, and reconcile `git status --short
  --branch`, recent commits, and `git worktree list`. Read the underlying JSON
  only when updating memory or investigating inconsistencies. During the same
  task, check changed state instead of rereading unchanged instructions.
- An explicit request to fix/build/change authorizes in-scope edits and
  non-destructive validation without another planning approval. A review or
  diagnosis alone does not authorize implementation. Ask when a choice changes
  scope materially, breaks compatibility, or introduces destructive operations.
- Preserve unrelated user changes. Never infer authorization for merging
  `master`, signing, tags, releases, update pointers, or Gitee synchronization.

## Shared Development And Publication

- Canonical development/issue repository is `MicroKeen/Mklink-AI-Probe`, default
  `main`, remote `microkeen`. See `docs/ai/repository-governance.md` for the live
  branch rules and publisher boundary. Existing client update URLs are unchanged.
- Start each authorized fix/feature from current `microkeen/main` in an isolated
  `codex/<task>` branch/worktree, or continue its existing task branch. Push that
  branch to `microkeen` and submit a PR. Never push directly to `main`.
- `Aladdin-Wang` and `su5176` are the repository administrators and PR integrators.
  Main requires another person's approval and the `feedback-contract` check;
  neither administrator has a bypass of those gates. An AI must still obtain
  explicit merge authorization, and must not weaken rules to complete a task.
  Exception authorized on 2026-09-15: an explicitly authorized version release
  may merge without a second person's approval after full release qualification
  and a successful required CI check. For that release only, temporarily set
  approval count to zero and disable last-push/additional approval requirements;
  keep PR, CI, discussion-resolution and force-push rules active. Pin the exact
  qualified PR head and restore/verify the original rules in a finally block,
  whether merging succeeds or fails. Ordinary PRs retain the normal review gate.
- Only `Aladdin-Wang` may update the `release` and `firmware` channels or official
  `v*` / `firmware-assets` tags. Development authorization does not authorize a
  publication, signing, credential change, or migration of client update URLs.
- Authorized Issue automation follows `docs/ai/issue-maintenance.md`: use an
  isolated `codex/issue-<number>` worktree from `microkeen/main`, push only that
  branch to `microkeen`, and submit a PR plus test report for human review.
  This is not permission to merge, publish, change credentials, or operate hardware.
- Do not restart development from the legacy `master`. A source release branch
  or a new publication requires a maintainer request.
- Fetch the matching GitHub branch before editing; reconcile divergence without
  force pushes or rewriting shared history.
- Finish each issue with the relevant checks, `git diff --check`, and an update
  to `docs/ai/project-memory.json`; run `python scripts/ai_memory.py render` and
  `python scripts/ai_memory.py validate`. Commit separately and promptly push
  to the task branch on GitHub `microkeen` under standing maintainer authority.
  Verify the remote tip, report failures, and leave unrelated work untouched.

## Verification

- For each fix, test the changed behavior and its affected surface: real browser
  for Web behavior, actual installation/upgrade for installer behavior, and
  physical hardware for device behavior. Documentation changes need document,
  link, packaging, or instruction-boundary checks, not unrelated hardware runs.
- Before an authorized merge/release, run the full Python and GUI suites,
  production build, and affected real-surface gates. Reconcile current
  `microkeen/main` first; subsequent code changes invalidate earlier evidence. Verify the merged
  tip and clean state. Missing required facilities need an explicit waiver.
- Record environment failures and unverified behavior. Component tests or
  fixtures do not prove real installation/hardware success; a prerelease push
  does not mean release qualification.

## Storage And Product Constraints

- Run build/test commands through `scripts/build_workspace.ps1`. All scratch
  belongs in `MKLINK_BUILD_ROOT` when configured, otherwise in the main
  checkout's ignored `.build`; never use the Windows system drive.
  Reuse caches, clean per-run scratch, and never upload `.build` or local logs.
  Preserve tracked `gui/dist` and official `release` assets. Report inaccessible
  or linked cleanup paths for manual handling; do not force deletion.
- Default ELF/DWARF parsing is bundled `pyelftools`; external tools require an
  explicit choice. HPM uses ROM API, never FLM or a second generic SWD reset.
  VCC changes require confirmation of the specific voltage for each operation.
- Standard installer output is NSIS. MSI/offline WebView2 needs authorization.
  Do not commit firmware, Packs, FLM, screenshots, device identifiers, local
  hardware paths, or secrets without a specific applicable exception.
- Public Skill packages contain only runtime files. Keep maintainer memory,
  tests, build/release instructions, and maintainer skills out of user packages.

## Read Only When Needed

- Build storage/commands: `docs/ai/build-storage.md`.
- Source development: `docs/ai/development.md`.
- Desktop packaging: `skills/tauri-gui-builder/SKILL.md`.
- Explicitly authorized publication:
  `skills/maintaining-mklink-ai-probe/references/releasing.md`.

The maintainer Skill is an optional reference index, not a second mandatory
workflow. Installed/global skills are not required for repository maintenance.
