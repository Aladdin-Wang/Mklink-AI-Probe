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
