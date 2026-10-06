# SystemView timestamp frequency correction (2026-10-07)

SystemView INIT carries SysFreq (timestamp frequency) separately from CPUFreq.
The parser previously divided timestamp ticks by CPUFreq, which stretches or
compresses time when the target records using a separate timer. It now uses
the declared independent timestamp frequency. CPU-clock timebases retain the
existing runtime CPU hint correction when INIT declares equal frequencies;
missing/zero SysFreq keeps the previous CPU fallback. A new INIT replaces the
prior timestamp source. Dashboard backfill follows the same parser property.
Existing event names and wire format remain unchanged.

Validation: 135 parser, CPU-clock, analyzer, stream-manager, streaming, history
and session tests pass. New cases cover whole and fragmented packets, locked
CPU hints with an independent 1 MHz timestamp source, source replacement and
zero-frequency fallback, plus dashboard backfill without overwriting existing
time values. The local target recorder implementation's INIT encoding and
SysFreq parameter documentation were checked as the protocol reference.

Three captures on current V3 with the corrected 72 MHz STM32 fixture passed:
15772/15763/15750 events, 13 tasks, zero target overflow and parser loss,
trace/wall ratios 0.99835/0.99769/0.99804. Bootloader hash remained unchanged.
This is real core-clock regression evidence; the independent timer case is
protocol-test coverage, not independent-timer hardware qualification.

No probe firmware/SDK or UI assets changed. Existing installed desktop and
local Skill runtime do not contain this source fix yet. Actual updated GUI,
packaging/installation and independent-timer hardware remain separate gates.

## Local package qualification (2026-10-07)

Source cb1cf41b passed the complete Python suite (4406 passed, 2 skipped,
60 dependency warnings) and GUI suite (889 tests / 86 files passed). The
suite included actual isolated remote wheel and frozen Site Agent builds.
This does not supersede physical hardware or installed UI gates.

The standard unsigned local NSIS was built successfully, including newly
frozen sidecar and production Web assets, with validated 7059 targets and
2224 algorithm blobs. Local setup size is 96714299 bytes; SHA256
232424bb5a14d417ed25050e78129004a4d9e850c84c7dade684212779d6f154.
No signing key, release channel, tag or public updater was touched.

Overwrite installation was attempted once. Windows UAC approval did not
complete and Start-Process returned user-cancelled; the previously installed
desktop remains in place. Do not claim installation success or retry silently.
The setup and result logs remain in the ignored artifacts/reports directories.

The local public Skill was updated from the validated archive for cb1cf41b;
its production Web assets match the new build. Existing Skill was backed up
under the non-system build artifacts directory. Package SHA256:
d6251c9fdafc2e30c2b4a781c6a59dbf6d3db89335396a64c4498471b9006982.
Both the setup-extracted frozen sidecar (Windows-only PATH) and installed local
Skill passed real stdio MCP initialization, STM32 algorithm catalog lookup,
security capability query and CLI runtime status. No hardware was opened by
these checks. Frozen artifact checks are not installed desktop verification.

Logs: v3-stage45-python.log, v3-stage45-gui.log, v3-stage45-bundle.log;
artifact evidence: install-v3-cb1cf41b/package-entrypoints.json and
skill-install.json. Full-test temporary directory contains links and was
retained by the safe-cleanup policy; it was not forcibly deleted.
`nTracked generated index.html line endings were normalized after packaging; the retained installer/Skill archives preserve the exact built bytes and hashes above.
