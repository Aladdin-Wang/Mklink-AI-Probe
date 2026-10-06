# Shared runtime idle-deadline wakeup

The idle monitor slept one second between checks, rounding the five-second
idle deadline up by as much as one additional polling interval. Shutdown then
still needed the existing Uvicorn and device cleanup. Historical six-second
measurements therefore did not imply a six-second lease.

The monitor now sleeps to an earlier idle deadline when it is less than one
second away. It retains the normal one-second scan when the deadline has
expired but an owner still prevents shutdown. All admission, session expiry,
in-flight operation, job and remote-client checks remain unchanged. Activity
during sleep is checked again before shutdown; no hardware operation is killed.

Deterministic monitor tests cover a fractional 5.35-second deadline and renewed
activity at that wakeup, which correctly defers exit to 10.35 seconds. Idle,
shutdown and shared-runtime suites passed: 44 tests. Existing checks include
owners, operations, GUI sockets, stale leases and bounded network shutdown.

## V3 hardware comparison

The same STM32 fixture and current V3 image were used for two short runs of
the source runtime. Two SDK clients shared one backend; the installed Skill
MCP read RTT channels 0–7 and memory, and CLI read the same memory. Detaching
observers did not stop the owner's RTT acquisition. Final shutdown used the
normal lifecycle, with successful serial reopening afterward.

| From final detach | Baseline | Deadline wakeup |
|---|---:|---:|
| Serial port released | 5.633 s | 5.232 s |
| Backend process exited | 5.841 s | 5.420 s |

These are individual short runs, not a percentile or hard real-time bound.
The deterministic improvement removes polling quantization; Windows scheduling
and cleanup can still add latency. The prior packaged sidecar took 6.144 s to
release its port in a separate run and is not the baseline for the 0.401 s
source comparison. No packaging/installation or rendered GUI change is claimed.

The local harness initially selected the Windows Python execution alias, which
could not be hashed; after resolving the actual interpreter, an assertion
specific to a packaged sidecar rejected the source runtime's Python child.
Those harness failures were corrected before the two completed comparisons;
they are not successful hardware evidence. Test backends exited normally.

Local evidence: stage66-{baseline,candidate}-clients.json and MCP logs in the
firmware application's ignored reports directory. No device IDs, local project
paths or raw logs are needed in this document. No firmware, target Flash,
voltage, permanent protection, SDK or submodule code changed.
