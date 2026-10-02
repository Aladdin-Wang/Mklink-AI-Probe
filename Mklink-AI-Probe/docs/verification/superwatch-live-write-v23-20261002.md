# SuperWatch live writes: V3 / V2 firmware port

## Scope

Both firmware variants now advertise `DUMP_WRITE=1` and implement the same request/ACK wire format as the [V4 implementation](superwatch-live-write-20261002.md). The host implementation in this branch requires no further changes. The updated protocol is only used after capability negotiation, leaving older host sampling commands intact.

- V3: the USB console parser queues a bounded framed request. The acquisition task performs the SWD write and readback only at a complete frame/batch boundary, with no retained batch or partial multi-block sample pending. Configuration changes cancel queued control requests. The device timestamp is sampled immediately before execution.
- V2: USB parsing and sampling share the foreground loop. The parser queues the request; `pt_dump_mem` services it after any retained sample frame is sent and before the next sample is built. The implementation uses the existing microsecond clock for both write timestamps and packet timeout, with no RT-Thread dependency. Generation changes or stopping acquisition discard stale pending requests.
- Both: SRAM scalar widths 1/2/4/8 bytes, address and overflow checks, request CRC, verified readback, immutable ACK under USB backpressure, same-generation duplicate request replay without another SWD write. A request ID reused with different contents is ignored. The target SRAM address window is a protocol guard, not proof that every address is populated on every device.

## Build and verification

Built both actual source projects with SEGGER Embedded Studio 8.24 using the repository build workspace wrapper. Build projects, object files, candidate binaries and logs are isolated in local build storage. Existing firmware checkout changes were preserved; exact pre-task backups and task-only patches were saved separately.

The original V2 generated project contains duplicate `linker_output_format` attributes. The build-only generated copy selects `bin` and resolves source paths, without altering the original project. Post-build device tools and debugger autostart are disabled. Existing compiler warnings remain; neither build reported errors.

Native C harnesses compile the actual receiver/service code and original CRC implementations from each variant with `-Wall -Wextra -Werror`. Both passed malformed CRC, fragmented control framing, duplicate IDs, conflicting IDs, ACK backpressure/exactly-once writes, invalid width/address/end overflow, stale generation, failed readback, partial-packet timeout and successful 1/2/4/8-byte writes. Receiver calls perform no target write before the acquisition service runs.

| Candidate | Application binary | Packaging | SHA-256 of packaged candidate |
| --- | ---: | --- | --- |
| V3 live-write development | 386,814 B | UF2, 773,632 B; family `0x0A4D5048`, base `0x80023000` | `e38b5eeb90716e8774d45e13b4c42c4169964a0bd1bcb1c0cf4f899b46ef2cdf` |
| V2 live-write development | 390,914 B | RBL, 391,010 B; raw uncompressed payload, base `0x80010400` | `cecdd76551ace9c5b1e188332ed296c19224268eca567ade437592b93e2f7753` |

ELF load addresses and binary lengths were checked. Both binaries contain the capability string. Every V3 UF2 block was checked for magic, family, address, block order/count and byte-for-byte payload reconstruction. The V2 RBL layout was checked against its bootloader source: header CRC32, body CRC32, part name, algorithm and raw/packed lengths. The V2 payload fits its `0x60000` application partition, leaving **2,302 B**; future changes must recheck this small margin. RBL packaging version is `2.8.0-live-write-dev`; runtime versions remain the existing development baselines, with capability negotiation identifying support.

## Limits and integration

The initial port/build run did not upgrade or physically test either model. The user subsequently upgraded and connected V3, then V2; their follow-up HIL results are below. These tests cover the connected STM32F103RET6 and stated sampling configurations, not every target or USB host. Never cross-flash model variants.

Candidates and exact source patches remain local; no firmware channel, official asset, version tag or installer was published. Source edits reside in their respective firmware checkouts. This report accompanies the host PR so integration can track all three supported firmware implementations without claiming that V4 hardware evidence certifies V3/V2.

## V3 hardware follow-up, 2026-10-02

The user upgraded and connected V3 to the STM32F103RET6 test project. Read-only firmware query returned `V3.5.1` and `DUMP_WRITE=1`. The probe confirmed the 30 MHz SWD profile. This verifies the running capability, not a readback hash of the entire installed probe image; the upgrade itself was performed by the user.

Each rate exercised 8-, 16-, 32- and 64-bit RAM variables, with a write followed by restoration for each variable: 16 acknowledged transactions across the two rates. All readbacks matched and final independent reads confirmed original bytes. Samples retained strictly increasing device timestamps.

| Measurement | 1 ms requested | Fastest requested (1 us) |
| --- | ---: | ---: |
| Complete samples | 1,329 | 239,296 |
| Mean device interval | 999.998 us | 5.565302 us |
| Maximum interval | 1,167 us | 378 us |
| Intervals spanning writes/restores | 1,083–1,167 us | 233–378 us |
| Host acknowledgement latency | 3.687–6.241 ms | 3.926–6.555 ms |
| Parser CRC errors / dropped frames | 0 / 0 | 0 / 0 |
| Firmware error / sample-drop flags | 0 / 0 | 0 / 0 |

The real SuperWatch manager was then exercised against the same device with three watched RAM values (a float fixture, guard and heartbeat). Its production stream hub accepted the binary batches. The float changed `1.25 → 3.125 → -1.5 → 1.25` in one capture: 1,320 continuous samples, maximum interval 1.140 ms, and write brackets of 1.095/1.140/1.086 ms showing the expected before/after values. Worker identity, time origin and metadata epoch stayed unchanged. A further verified write while paused preserved the paused state; resume succeeded. Guard bytes, original float and all earlier test values were preserved/restored. Read drops/errors, binary publication drops, CRC errors and firmware error flags were zero in this final manager run.

The first manager harness omitted its stream hub and therefore reported local publication drops; it was corrected to use the production hub and rerun. Both raw records remain local. This follow-up validates device transport and manager lifecycle, **not a new browser-rendering or WebSocket subscriber test**. Initial parser discarded-byte counts (46/49 bytes in the low-level runs) were command/prompt text; no zero-discard claim is made. No target firmware, PID parameters or power settings were changed. All sessions were stopped and disconnected.

## V2 hardware follow-up, 2026-10-02

After the user's upgrade and connection, `cmd.get_version()` returned `V2.8.0` and the separate capability line `DUMP_WRITE=1`. At 30 MHz SWD, the same STM32F103RET6 fixture passed 16 live write/restore transactions across 8/16/32/64-bit variables and two sampling rates. All acknowledged readbacks matched; independent reads after stopping confirmed original bytes.

| Measurement | 1 ms requested | Fastest requested (1 us) |
| --- | ---: | ---: |
| Complete samples | 1,591 | 303,552 |
| Mean device interval | 1,001.231 us | 5.277719 us |
| Maximum interval | 1,136 us | 350 us |
| Intervals spanning writes/restores | 999–1,136 us | 235–350 us |
| Host acknowledgement latency | 3.557–4.166 ms | 3.764–5.567 ms |
| Parser CRC errors / dropped frames | 0 / 0 | 0 / 0 |
| Firmware error / sample-drop flags | 0 / 0 | 0 / 0 |

The real SuperWatch manager and production stream hub also passed a three-variable capture. In one continuous capture the float fixture changed `1.25 → 3.125 → -1.5 → 1.25`; all transitions were present in 1,607 samples with strictly increasing device timestamps. Maximum interval was 1.005 ms; write brackets were 1.002/1.001/1.001 ms. Worker, time origin and metadata epoch were unchanged. A verified write while paused preserved pause, followed by successful resume. Read errors/drops, binary publication drops, CRC errors and firmware error flags were zero. The guard stayed intact and the original float was independently verified after stop.

This run used the user's upgraded probe without re-flashing it or reading back its full firmware hash. It did not repeat browser rendering or WebSocket subscriber delivery tests. Parser discarded-byte counts included command/prompt text (44/47 bytes for the low-level runs). Target firmware, PID settings and power were unchanged; all test values were restored and the connection released. V2, V3 and V4 now each have real-device live-write evidence within their respective documented test scopes.
