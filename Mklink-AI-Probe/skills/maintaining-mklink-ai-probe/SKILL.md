---
name: maintaining-mklink-ai-probe
description: Maintain Mklink AI Probe consistently across users and coding models. Use for repository coding, debugging, review, handoff, worktree, build, or release tasks to discover the real requirement, diagnose before editing, make proportional changes, verify results, and preserve project memory. Official signed releases require explicit maintainer authorization.
---

# Maintain Mklink AI Probe

This repository skill is the shared workflow. Do not depend on similarly named
skills installed on one developer's computer.

## Start From Live State

1. Read `AGENTS.md`, `docs/ai/CURRENT_HANDOFF.md`, and
   `docs/ai/project-memory.json`.
2. Run `python scripts/ai_memory.py validate`, `git status --short --branch`,
   and `git log -12 --oneline`.
3. Reconcile recorded state with Git and the running system. Correct stale
   memory instead of repeating completed work.
4. Check `git worktree list`. Reuse the current isolated worktree when one
   already exists; create another only when isolation is useful and authorized.

## Turn Requests Into Results

1. Identify the observed problem, the developer's intended outcome, affected
   users, constraints, and a concrete success signal.
2. Inspect the relevant code, tests, logs, UI, hardware state, and existing
   patterns before choosing a solution.
3. Ask only when an unanswered choice would materially change the result or
   require new authority. Otherwise state the smallest reversible assumption
   and continue.
4. Find the root cause. Keep the change within the owning module and avoid
   speculative abstractions or unrelated cleanup.
5. Use a short written plan for multi-step, risky, or cross-module work. Small
   fixes can proceed directly. Update the plan when evidence changes it.
6. Add regression coverage when it is useful and economical. Do not require a
   separate RED commit, a test-first ceremony, or broad tests for a narrow edit.
7. Prefer repository scripts and established APIs. Keep runtime dependencies
   bundled when users should not need a local toolchain.

## Project Invariants

- Default ELF/DWARF handling is bundled `pyelftools`. Invoke local
  `readelf`/`addr2line` only when the user explicitly selects the external
  backend.
- HPM targets use the dedicated ROM API and never load FLM.
- Generate only standard NSIS by default. MSI and WebView2-offline bundles need
  explicit user authorization.
- Put installer artifacts in the workspace-level `release/<build-time>/`
  directory and keep them out of Git.
- Prefer real Edge/Playwright/WebView2, computer use, and real hardware for
  behavior that depends on them; use focused automated tests for fast feedback.
- Never commit firmware, Packs, FLM files, logs, screenshots, full probe IDs,
  COM numbers, usernames, credentials, signing keys, or local hardware paths.
- Preserve user changes in a dirty worktree. Never discard unrelated work.

## Verify And Hand Off

1. Run checks proportional to the blast radius and `git diff --check`.
2. For user-facing or hardware changes, record what was validated on the real
   surface and what remains unverified.
3. Update `docs/ai/project-memory.json` with current facts, decisions, evidence,
   limits, and next actions. Run `python scripts/ai_memory.py render` and
   `python scripts/ai_memory.py validate`.
4. Commit and push only when authorized. Finish with a clean worktree unless
   the user explicitly leaves work in progress.

## Official Releases

Do not infer permission to sign, tag, publish, update `updates/latest.json`, or
sync Gitee. Contributors may prepare and verify release candidates, but only the
maintainer's computer or maintainer-controlled CI may publish an official
release. When publication is explicitly requested, follow
`references/releasing.md` exactly.
