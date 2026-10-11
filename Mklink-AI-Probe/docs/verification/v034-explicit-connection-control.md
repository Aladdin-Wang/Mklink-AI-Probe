# 0.3.4 Explicit connection lifecycle

Sources: `34834d08`, final request fencing `5f4b9728`; protocol 52. This replaces the shared-client/capture refusal policy in the earlier window-owned-backend report. One GUI client still owns one fixed backend.

## Behavior and architecture

A GUI or AI explicit disconnect/switch is admitted even when target acquisition, AI attachments, other pages or remote operators are present. A lifecycle queue reserves intent, blocks new target operations, drains admitted work, stops target workers, closes the old device, retires target sessions and clears target data. Independent UART sessions remain intact. Successful transitions increment device generation so all local pages rebuild target panels and symbols. PID, endpoint and backend authentication remain unchanged.

Already accepted synchronous operations and asynchronous flash jobs finish on the original target before release. Admission rechecks asynchronous jobs after obtaining the operation lock, because a draining HTTP operation can itself start a job. Cancellation/loss of the requesting HTTP connection cannot prematurely release hardware ownership. Historical uncertain jobs retain their original identity and are never replayed.

Old AI/SDK target sessions are invalid after retirement; clients must explicitly reattach. Remote GUI captures their original probe/generation, and physical requests carry target identity. The gate rechecks identity under admission after receiving the body, preventing a delayed old body from reaching a newly selected target. Remote target handles retain an identity snapshot. A different independent backend still exclusively owns its probe; failed destination reservation leaves the current device intact.

MCP `disconnect` and SDK `RuntimeClient.disconnect()` now perform physical disconnection. MCP `detach`, SDK `close()` and context/lifespan cleanup only leave the caller's attachment. Explicit SDK/MCP `connect(probe=...)` switches its existing backend in place, without launching another backend. Ordinary hardware calls do not rediscover or replay. The management release action remains available while work drains. Source Skill and references document the distinction; installed Skill packages were not replaced.

## Validation

- Broad regression: 830 Python tests passed (runtime, API, remote bridge/target, live write). Earlier runs exposed old refusal/cleanup expectations and a child-process fixture missing the new field; fixtures were updated to the intended contract.
- Final queue/SDK adjustment: 115 Python tests passed. Final delayed-body guard: 71 tests passed, including a body deliberately stalled across a completed switch. These are sequential broad and focused passes, not a claim that the final source had one full-repository run.
- 87 GUI tests passed for configuration, backend management, API and dashboard generation handling; TypeScript/production build passed. Existing bundle size and dependency deprecation warnings remain.
- V3.6.4 / STM32F103, original ELF used in place, 30 MHz and 1 ms: two AI clients attached to RTT/SuperWatch; physical disconnect automatically stopped both captures and retired their sessions. Stale memory requests were rejected.
- Active capture plus shared AI: switched to the second physical probe, cleared old capture state and retired the old AI. AI physical disconnect also stopped both captures. SDK explicitly switched A→B→A in the same backend. Final source repeated this entire sequence with unchanged PID, endpoint and instance; restored capture had zero read errors.
- Two real production browser pages: clicked disconnect during capture, both pages became disconnected; reconnected A, started capture, clicked switch to B, both pages reported B and the old capture stopped. Switched back to A. No manual subscriber detachment or capture stop was needed for these actions.
- SystemView worker plus AI subscription: explicit AI disconnect stopped SystemView and restored the original connection afterward. The short check observed 54 input bytes and zero decoded events; it proves lifecycle cleanup, not new trace decoding/performance qualification.

The second probe had no MCU attached, so its target acquisition was not tested. Flash/erase drain races, delayed bodies and remote target invalidation were verified with deterministic fixtures; this round did not interrupt a physical flash job. Probe firmware, VCC, installer, merge and release were not changed.

Evidence remains local in the configured build artifact directory: `lifecycle-hardware.json`, `lifecycle-systemview.json`, `lifecycle-disconnected.png`, `lifecycle-switched.png`, `lifecycle-final.png` and regression/build logs. The first hardware helper used incorrect response keys (`running` versus `state`, and a nonexistent runtime-status `port`); the helper was corrected and the complete sequence rerun successfully. One current WebGUI is left on the original probe for the user; the extra browser test page is closed.
