# SuperWatch live variable writes — 2026-10-02

## Cause and change

Previously the symbol write transaction stopped and restarted the entire stream manager. Restarting advanced metadata and reset the capture origin, clearing the GUI history across the very step being measured.

The acquisition worker now owns writes as well as reads. On capable firmware it sends a framed write request during continuous dumping; the firmware executes it between complete sample frames/batches and returns a binary acknowledgement with device timestamp and verified readback. The manager, capture origin and GUI history stay intact. GUI write markers and exported raw-log write events identify verified operations. Older firmware uses a worker-owned stop/write/readback/resume transaction, retaining history but with a sampling gap.

## Protocol

- Capability: an exact `DUMP_WRITE=1` line from `cmd.get_version()`, checked before streaming.
- Request: RS (`0x1e`), 56 hexadecimal characters, LF. The decoded 28 bytes are `<4sIIB3x8sI`: `SW01`, request ID, address, width, three reserved zero bytes, padded data, CRC32 over the first 24 bytes. Little endian.
- Widths: 1, 2, 4, 8 bytes; the entire write must lie inside the ARM SRAM address window `[0x20000000, 0x40000000)`. Symbol catalog writability/generation checks still apply. The window is not a guarantee that every address is populated SRAM on every target.
- ACK: dump magic `MPMDMPMD`, device timestamp (8 bytes), total length 42 (2 bytes), region count 0, kind `0x57`, request ID (4), address (4), width (1), status (1), readback (8), CRC32 (4). All multibyte fields little endian. Timestamp is taken immediately before the write, not at browser receipt.
- Firmware status: 0 verified, 1 invalid request, 2 write failure, 3 read failure, 4 stale generation, 5 readback mismatch.
- One pending request; the USB receiver only frames/validates/queues. SWD write and readback run in the acquisition owner. ACK backpressure does not repeat a write; an identical last request ID/payload within the same generation replays its ACK. Timeout/disconnect reports an unknown outcome without automatic retry.
- Sampling and writing share SWD, so finite jitter remains. Multi-variable reads and wide writes are not atomic target snapshots. Old firmware cannot provide a device write timestamp.

## Verification

Windows, MicroLink V4 and STM32F103RET6; actual target software PID plant, no physical motor. Candidate firmware built with SEGGER Embedded Studio 8.24 and upgraded by UF2; read-only capability query confirmed the new firmware. Candidate SHA-256: `c37bdb2572c2785b3ea32fddc7dada91ab54cb0a7819af0c8d088c5cb8723376` (1,609,216 bytes). This is a V4.5.2 development candidate, not a channel release.

| Check | Result |
| --- | --- |
| Targeted Python parser/session/manager/API tests | 235 passed |
| Targeted GUI tests | 128 passed |
| Production GUI build | Passed |
| MicroBoot documentation strict build | Passed (`python -m mkdocs build --strict`) |
| Native firmware control harness | CRC/framing, duplicate ID, ACK backpressure, invalid bounds/width, stale generation, failed readback and partial packet timeout passed |
| Live 8/16/32/64-bit RAM writes and restores | Verified at both rates below |
| 30 MHz, 1 ms requested | 1,344 samples, mean 1,000 us, maximum gap 1,176 us; write brackets 1,064–1,176 us |
| 30 MHz, fastest requested | 243,840 samples, mean 5.477844 us, maximum gap 461 us; write brackets 183–461 us |
| HIL parser CRC errors / firmware error flags | 0 / 0 |

Real Chrome Web GUI validation used the production build, AXF symbols and one shared stream. Manual writes did not change capture metadata. The 19-second waveform recording contains 190 original canvas frames and 19,165 complete target/feedback/output groups. Device sample times increase strictly, maximum gap 1.194 ms; sample brackets across the upward/downward writes are 1.072/1.068 ms. Backend sample drops, read errors and parser CRC errors were zero. The additional WebSocket subscriber reported 30 sequence gaps across metadata/subscription traffic; this is not claimed as a zero-gap WebSocket transport test. Initial parser discarded-byte counts include command/prompt text, not CRC-corrupted samples.

The GIF in the MicroBoot STM32F103 case shows manual 800 → 1200 → 800 target writes, with gains 2/8/0 and automatic stepping disabled for that capture. It contains real GUI data, not generated traces. Actual GUI raw-log export contains verified write timestamps. Original target RAM parameters and automatic stepping were restored and read back; the probe was disconnected afterward.

## Integration boundaries

Host changes are an isolated PR. Companion firmware source is maintained in the separate firmware checkout: only the four task files were changed and an exact pre-task-to-final patch plus source hashes are retained in local build reports. Existing unrelated firmware changes were preserved. Firmware binary, hardware identifiers and raw local logs are not committed here. The MicroBoot case and GIF are updated in that documentation checkout, preserving its existing edits. No official release or merge is implied. Legacy behavior is covered by component tests; this run did not downgrade the physical probe for a second old-firmware HIL run.
