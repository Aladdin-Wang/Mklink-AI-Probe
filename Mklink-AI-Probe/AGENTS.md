# Repository agent protocol

Every coding agent must treat `docs/ai/project-memory.json` as the durable cross-model project memory.

## Session start

1. Run `python scripts/ai_memory.py validate`.
2. Read `docs/ai/CURRENT_HANDOFF.md`, then the active plan named in the JSON.
3. Reconcile the recorded branch/HEAD/working-tree state with `git status --short` and `git log -12 --oneline`.
4. Resume `current_session.current_task`; do not skip an unfinished review gate.

## Session end

1. Update the JSON with factual results only: timestamp, HEAD, remote HEAD, working tree, current task, milestones, verification, limits, and next actions.
2. Run `python scripts/ai_memory.py render` and `python scripts/ai_memory.py validate`.
3. Run tests proportional to the changes and `git diff --check`.
4. Commit the memory update with the related checkpoint and push the current branch when authorized.
5. Redact full probe IDs, COM ports, credentials, usernames, raw logs, screenshots, Pack files, and build artifacts.

If chat context conflicts with the repository, verify the live repository and hardware state, then correct the memory rather than silently following stale text.
