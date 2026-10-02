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

**No V3 or V2 probe was upgraded or physically tested in this run.** The previously connected V4 and its target were not modified. Compilation and native control tests do not certify USB scheduling, sampling jitter or upgrade success on those two hardware variants. Verify each matching probe with the host branch before release; never cross-flash model variants.

Candidates and exact source patches remain local; no firmware channel, official asset, version tag or installer was published. Source edits reside in their respective firmware checkouts. This report accompanies the host PR so integration can track all three supported firmware implementations without claiming that V4 hardware evidence certifies V3/V2.
