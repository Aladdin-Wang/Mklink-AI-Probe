# V3 Watch raw frames and batch setup reuse

2026-10-07. Development candidate, not an installer or firmware release.

## Wire contract

HELLO capability bit 4 (value 16) advertises Watch event version 2. The existing
16-byte MLX1 header retains length, epoch and sequence; opcode 0x41 version 2
has no four-byte CRC trailer. Payload and actual per-record timestamps are
unchanged. Commands, replies and RTT remain CRC-protected version 1.

The host accepts version 2 only for advertised Watch events. Fragmentation,
length limits, session checks, event ordering counters and Watch payload parsing
remain active. Payload bit corruption is no longer detected by a Watch CRC;
valid shape/sequence is not proof of data integrity. Existing clients cannot
consume this firmware's Watch stream and must be updated together with firmware.
The updated host still reads existing V4/V3 version-1 streams.

## Firmware changes

V3 drops incremental Watch CRC and short-frame CRC correction/cache work.
Tracked SWD SELECT/CSW can survive sampling batch boundaries; ownership changes,
failed transfers and exhausted WAIT retries invalidate them. Ordinary memory
operations retain fresh setup. A fully drained successful fixed-address batch
may reuse its setup only if no intervening bus transfer, ownership invalidation,
or address change occurred. The next DAP reservation prevents reuse and reads.
No outstanding posted read is carried across the released target mutex.

This is a small-state experiment, not a double-buffer/USB zero-copy redesign.
No SDK, WinUSB, V4 firmware or target bootloader change was made.

## Measurements

Same V3/STM32 fixture, Watch only, one or four separated 32-bit words. Each
configuration is a bounded two-second capture; the requested periods are
1 (full speed), 20, 50 and 100 microseconds.

| Full-speed case | Baseline | No Watch CRC | SELECT/CSW reuse | Fixed setup reuse |
|---|---:|---:|---:|---:|
| One word samples/s | 239639 | 246870 | 258395 | 260135 |
| One word inter-batch median, us | 48 | 48 | 33 | 22 |
| One word inter-batch P99, us | 105 | 104 | 87 | 64 |
| Four words groups/s | 19575 | 19577 | 19816 | 19897 |
| Four words inter-batch median, us | 67 | 67 | 65 | 65 |
| Four words inter-batch P99, us | 133 | 148 | 153 | 158 |

One-word median gap improves about 54%, throughput about 8.6%. Four-word
tail improvement is not established. One SELECT/CSW run observed a 634 us
maximum; its repeat observed 157 us. This is not a worst-case latency guarantee.
The single-word 10 us absolute gap goal remains unmet. Four-word normal
intra-batch median is already 47 us, so its relevant goal is less than 10 us
additional batch-boundary overhead, also unmet by this candidate.

All captures checked exact benchmark data and zero reported transport sequence
gaps/host Watch drops. These counters do not prove that every target transition
was sampled, and CRC-free frames cannot detect arbitrary payload corruption.

## Validation and deployment boundary

Host mux suite: 114 passed, including every split of a raw event, CRC reply
coexistence and rejection of unadvertised/non-Watch version-2 frames.
V3 production-native application contracts: 21 suites passed; SES Debug built.
Tests cover buffer boundaries, every mocked SWD transfer failure, cache
invalidation, changed address, intervening access, DAP reservation, RTT8,
backpressure, session expiry, partial batches and timestamp conversion.

Final candidate OpenOCD connected/halted in 0.272 s under RTT8 plus Watch,
preempted MUX access, single-stepped, downloaded 113352 APP bytes in 4.897 s,
and verified them in 1.631 s. Bootloader readback was unchanged. Explicit
capture restart recovered all eight RTT channels and Watch with zero reported
transport gaps/drops. Connection/halt time includes OpenOCD/USB startup; it is
not a measurement of firmware reservation-to-yield latency.

Local evidence is stage77/78/79 build, upgrade, phases, contracts and OpenOCD
reports under the V3 ignored build directory. Source and candidate are retained;
no new installer, local Skill or V4 update is claimed. Candidate GUI acceptance
and complete multi-entry regression have not been repeated for this wire change.

Final repeated captures: one word 258731 samples/s, gap median/P99/max
22/69/145 us; four words 19936 groups/s, 65/146/166 us. All eight
configurations passed again. The user explicitly authorized a new overwrite
installation and requested leaving the candidate firmware in place. Packaging
and actual installation qualification follow separately.


## Installed host and shared Skill acceptance

The authorized local NSIS overwrite returned exit code 0. Installed executable,
sidecar and STCP hashes matched the installer payload; 39 bundled Web files
matched the production build. This is a local unsigned development installation,
not a published release. V3 keeps the candidate firmware; V4 remains unchanged.

With the installed desktop connected, the local Skill MCP attached to the same
backend instance and inherited its loaded symbols. Parameterless rtt_start
returned subscribed/reused. All eight channels returned 16384 bytes each;
a framed memory read succeeded during capture. MCP disconnect returned
device_closed=false, leaving GUI and RTT running.

A second MCP session added a uint8 variable and started, read, paused, resumed,
and stopped SuperWatch while RTT8 continued. The short concurrent capture
reported about 224k samples/s, 438531 samples at the status check, and zero
reported parser drops, sample-drop flags, read errors or backend queue drops.
This is a coexistence smoke test, not a new timing benchmark or proof of
payload corruption detection. No physical reset or firmware restore was needed.

Skill instructions now default to shared connection even when GUI is open,
reuse existing capture without reconfiguration, keep per-channel cursors, and
detach only the AI client. Old direct serial RTT startup recipes were removed.
Supported GUI control means declared shared backend capabilities, not arbitrary
window automation. Full GUI regression and long-duration qualification have
not been rerun for this documentation/install step.
