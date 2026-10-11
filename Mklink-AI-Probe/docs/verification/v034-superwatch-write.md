# 0.3.4 SuperWatch variable write acknowledgement

Source: `267b175f`; 2026-10-11. This supersedes the readback-success contract in the historical SuperWatch live-write reports.

## Problem and behavior

On V3 with STM32F103, writing the continuously incrementing `vofa_test_count` during capture reproducibly returned `Multiplex write readback mismatch` and stopped the worker. The test target increments this byte every millisecond. A separate read after a successful write therefore need not equal the requested value.

At the user's explicit request, SuperWatch writes now complete on the device write acknowledgement. MUX, legacy compatibility-gap, and idle writes issue no additional readback. The response contains the encoded/decoded requested value, `acknowledged=true`, and `verified=false`; the UI says “已写入”. This does not claim the running target will retain that value. Variable type, generation, writable-range checks, command acknowledgements, and unknown-outcome handling remain in place. No write is automatically replayed. Flash verification and explicitly requested memory verification are unaffected.

Legacy SW01 firmware performs an internal readback that cannot be removed by a host change. Inspection of V3 and V4/HPM implementations confirms statuses 3 and 5 mean successful SWD write followed by failed/different readback. Only this protocol accepts 0/3/5 as write acknowledgements and returns the requested payload. Invalid requests, SWD write failures, stale generations, unknown statuses, CRC errors and mismatched identities remain errors. MUX status 5 still means command failure and is not reinterpreted.

The existing worker owns write serialization. Successful live writes preserve worker identity, time origin, metadata version, history and paused state; legacy compatibility writes still have the documented sampling gap. A real transport failure or missing acknowledgement is not hidden.

## Validation

- 385 Python tests passed: MUX, live write/worker lifecycle, RTT/SuperWatch streaming, dump session and memory completeness. Regression cases forbid readback calls, exercise subsequent writes and continuing samples, validate all known/unknown SW01 status outcomes and no replay after failed writes.
- 72 GUI tests passed across variable panel, symbol catalog, SuperWatch tab and replay. TypeScript and production Web build passed.
- V3.6.4 / STM32F103, original test project ELF used in place: 30 MHz debug clock, 1 ms sampling, two waveforms and RTT concurrently. Twelve pairs of dynamic-byte and static-word writes (24 total) all acknowledged; capture continued, metadata unchanged, 4,450 cycles and zero read errors at the checkpoint; RTT had 31 lines and no error.
- Independent test-only read after writing a different static marker confirmed RAM actually changed, then the marker was restored. This read belongs to the hardware test, not the product write operation. At that checkpoint capture had 70,605 cycles, zero read errors and no error.
- Real production browser wrote `vofa_test_count=12` while capturing: “已写入: 12”, running state, 1 kHz and continuing waveforms visible. Left the updated WebGUI and SuperWatch capture available for the user; stopped the extra RTT test capture.

Local-only evidence: `live-write-before.json`, `live-write-after.json`, `write-only-independent-check.json`, `superwatch-write-only.png`, Python/GUI/build logs in the configured build artifact directory. An initial backend reload was refused by the shared-page guard; releasing the test page allowed the normal disconnect/restart, without bypassing the guard. The attempted hardware script before reload still reproduced the old error and is not counted as fixed-code validation.

Legacy/HPM behavior is source inspection and simulated-wire regression coverage, not new physical-device qualification. No probe firmware, voltage, installer, merge or release was changed by this fix.
