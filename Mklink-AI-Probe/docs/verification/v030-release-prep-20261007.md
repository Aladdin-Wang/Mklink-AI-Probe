# 0.3.0 release preparation, 2026-10-07

## Host fixes

The Windows Web launcher now uses a persistent per-user workspace rather than
inheriting the shell working directory. Launching from System32 previously made
AXF uploads fail when the backend tried to create its upload directory there.
Upload storage failures return an actionable 503 response and close the upload.

SuperWatch displays the structured busy response when changing debug speed
during acquisition. It does not stop other clients' shared acquisition. The
symbol-reload banner asks users to verify their firmware/symbol match without
claiming acquisition is still stopped after another client has restarted it.

The shared-runtime heartbeat test now checks causal independence from a blocked
UART worker instead of asserting a fragile wall-clock threshold.

## Completed source verification

- Full Python suite: 4,471 passed, 2 skipped, 60 warnings.
- Full GUI suite: 902 passed in 87 files.
- GUI production build passed; tracked production assets regenerated.
- V4 firmware candidate `3bc7ef7` compiled with SES 8.24; SWD layout checks,
  37 native application test scripts and USB/DAP reset-recovery test passed.
- V4/STM32 Keil 10 MHz: real download Verify OK; eight RTT channels and a
  four-region 1 ms SuperWatch subscription resumed automatically. Run, halt,
  single-step, resume and debugger exit passed in a bounded 120-second run.
  Running one-second windows were 900–1,004 samples, usually near 1,000.
- V4 OpenOCD 1 MHz: 450 samples/2 s running and 471/2 s halted, eight RTT
  channels, memory checks, step and application-only download verification pass.
- V4 no-DAP, one-word full-speed 30-second test with RTT off: 271,576.69
  samples/s, maximum adjacent interval 73 us, no interval above 1 ms and no
  recorded transport loss.

The firmware report is `docs/dap-stream-coexist-20261007.md` in MicroLink_Plus.
Run-to-main entry reads precede test-pattern initialization; their zero values
are not evidence of corruption. Debug traffic reduces sampling throughput;
programming/reset intentionally interrupts sampling. These tests do not prove
zero missed target transitions or a worst-case latency bound.

## Remaining delivery gates

Generate a local unsigned NSIS from the exact host commit, overwrite-install,
verify the real Web-only AXF upload, desktop/Web shared acquisition, frozen
stdio MCP with a Windows-only PATH, local Skill package and idle cleanup.
These installed-surface gates remain pending until separately recorded.

V3 hardware and HPM/JTAG debugger coexistence are deferred at the user's
request. Long-duration validation remains paused. Other physical limitations
in the existing function matrix remain explicit. This report authorizes no
tag, signed release, update-channel publication or host-main merge.
