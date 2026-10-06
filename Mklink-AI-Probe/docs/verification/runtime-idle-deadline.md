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

## Packaged candidate and local Skill follow-up

Built a local unsigned v0.3.0 NSIS from source 3e65f1ad using the repository
builder, with fresh frozen backend and production GUI. No signing key was
loaded, installer executed, update channel changed or release published.
Previously cancelled overwrite installation remains unqualified.

Extracted the NSIS payload and compared all 39 bundled Web files byte-for-byte
with this production build. The validated algorithm manifest has 7059 targets
and 2224 blobs. Installed the public Skill archive through its existing updater,
with its prior contents backed up on the build drive. The Skill records source
3e65f1ad; its GUI matches this build and idle-monitor source matches after
normalizing Git line endings. No maintainer content was added to the Skill.

Both frozen MCP and newly installed Skill MCP initialized with a Windows-only
PATH and returned STM32 catalog/security queries without opening hardware.
The extracted sidecar then passed V3 shared-client hardware verification:
two SDK clients shared one protocol-49 backend, CLI read exact RAM bytes, and
installed Skill MCP read RTT channels 0–7. Observer detachment preserved the
owner's RTT acquisition. Final detach released the port in 5.241 s and exited
the process in 5.427 s; serial reopening succeeded. The backend process tree
contained no Python interpreter. These results qualify the extracted payload,
not an overwrite installation or a new rendered GUI acceptance run.

Candidate SHA256:

- NSIS: ee96d94c3ad90fc216ce5cea04c44a6b1650903fa1462cf56e77e93f5581c0b4
- Sidecar: 01f79d9d098d99d13e75103eebc541da22a9325ab650df76adb287e669194d06
- Desktop: 4947da8c624d9bac7855ae21d1092e072054eb93d7fdf5995268178c702305a2
- Skill ZIP: a5db4de7ce9db635c5b1503b27939ee21071193b2c95a4aa2c03df627d081eb6

Local evidence: stage67-local-bundle.log, stage67-shared-clients.json and the
candidate artifact directory's payload.json, entrypoints.json and
skill-install.json. Generated Web resources are retained in the source branch.
Long-running AI clients need a restart to load the updated Skill runtime.
After recording package hashes, normalized only the tracked generated HTML's
mixed CRLF/LF endings to LF for repository whitespace checks. Candidate and
installed Skill retain their tested bytes; the normalized HTML has identical
content after line-ending normalization. No package hash is changed by this
source-only normalization.
