# Firmware Download Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the CPU debug CLI port resolver and make IDE, pyOCD, offline, and FLM selection priorities explicit and executable for future agents.

**Architecture:** Keep the existing download backends. Fix the shared CLI regression in place, reorder automatic algorithm discovery without overriding explicit user selection, and teach the repository Skill to select the existing backends in the approved order.

**Tech Stack:** Python, pytest, Keil uVision CLI, pyOCD, repository Markdown Skill, STM32F103 hardware fixture.

---

### Task 1: Repair CPU Debug CLI Port Resolution

**Files:**
- Create: `_maintainer/testing/tests/test_cli_debug_control.py`
- Modify: `mklink/cli.py`

- [x] Add tests that call `halt`, `resume`, `step`, and `break --status` without an explicit port and assert they use `_resolve_port`.
- [x] Run `python -m pytest _maintainer/testing/tests/test_cli_debug_control.py -q` and verify the undefined `_auto_detect_port` failure.
- [x] Replace the four stale resolver calls with `_resolve_port` while preserving explicit `--port` handling.
- [x] Rerun the focused tests and verify they pass.

### Task 2: Prefer Bundled Flash Algorithms

**Files:**
- Modify: `_maintainer/testing/tests/test_flash_algorithm_catalog.py`
- Modify: `mklink/cmsis_dap/algorithm_catalog.py`

- [x] Add tests proving bundled Pack/FLM algorithms precede installed Pack and automatic custom algorithms, while an explicitly selected custom algorithm remains honored by callers.
- [x] Run the focused catalog tests and verify the current installed-Pack-first behavior fails.
- [x] Reorder automatic discovery to bundled Pack, bundled DAPLink FLM, installed Pack, then custom-only fallback.
- [x] Run flash catalog, online flash, offline deployment, and HPM focused tests.

### Task 3: Update The Repository Skill

**Files:**
- Modify: `SKILL.md`
- Create: `references/firmware-download-priority.md`
- Modify: `references/triggers.md`
- Modify: `references/workflows.md`
- Modify: `references/commands-flash-rtt.md`

- [x] Run pressure scenarios against the old Skill and record whether agents choose IDE, pyOCD, offline, and FLM sources in the approved order.
- [x] Document Keil build-then-download as the default, download-only when explicitly requested with a valid artifact, pyOCD when IDE is unavailable/not applicable, and offline deployment last.
- [x] State that execution failures stop and report instead of silently changing backend; capability absence advances to the next backend.
- [x] State bundled FLM automatic priority and the explicit-user-selection override.
- [x] Repeat the pressure scenarios and verify compliant routing.

### Task 4: Qualify And Integrate

**Files:**
- Modify: `docs/ai/project-memory.json`
- Generate: `docs/ai/CURRENT_HANDOFF.md`

- [x] Run focused Python tests for debug CLI, catalog, online flash, offline deployment, and HPM behavior.
- [x] Run the complete Python suite, complete GUI suite, production GUI build, Rust tests, and `cargo check`.
- [x] On the STM32F103 fixture, run Keil build then Keil download, verify Flash readback and a changing runtime counter, and verify `python -m mklink resume` succeeds.
- [x] Run a pyOCD real-hardware download using the bundled algorithm and verify readback/runtime again.
- [x] Update and render project memory, run `git diff --check`, commit the branch, ensure `master` has not advanced, and fast-forward merge.
- [x] Rebuild the clean Codex global Skill from the tested commit, reinstall `mklink[gui,mcp]`, and rerun the download smoke checks from the global path.
