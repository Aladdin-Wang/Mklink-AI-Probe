# 0.3.5 SuperWatch metadata clock repair

SuperWatch compared a batch timestamp from its injected clock (by default
`perf_counter`) against metadata publication times recorded with `monotonic`.
These clocks can have different reference points on Windows Python before 3.13.
A positive offset above one second republished channel metadata for every row;
a negative offset delayed periodic metadata. Redundant metadata competed with
sample batches in the same bounded client queue.

All metadata timestamp writes and elapsed-time comparisons now use the manager's
clock, including the path without a supplied batch timestamp. Cache replacement
and its timestamp update remain under the metadata lock. The high-resolution
batch clock, binary protocol, queue bounds and sampling settings are unchanged.

## Regression coverage

- Default clock with a simulated 34.8-second system monotonic offset.
- Injected clock with positive and negative offsets, with and without batch time.
  An independently frozen system clock cannot affect periodic publication.
- Exact one-second boundaries and repeated publication across multiple windows.
- A real StreamHub with a 64-batch queue retains all 1,000 sample rows when the
  sampling clock is offset by 34.8 seconds; only bootstrap metadata is queued.
- Existing metadata versioning, late subscribers, layout transitions, restart,
  sample alignment, batching and performance tests remain in the exercised suite.

The original implementation failed the default-clock and offset batch tests
before the fix (including 1,000 metadata messages for 1,000 rows). Windows Python
3.11.16 passed 152 streaming/performance/standalone-health tests after the fix.
Python 3.14.5 passed 392 tests covering those suites plus StreamHub, stream API,
loop delivery, live writes, alignment and VOFA streaming.

Audit of other `perf_counter` and injected-clock consumers found no corresponding
cross-clock subtraction in VOFA batching, RTT/SystemView deadlines, API polling,
transfer expiry or the standalone watch loop. Latest-sample age still intentionally
uses matching `monotonic` calls for both recording and reading its timestamp.

## Physical device and browser checks — 2026-10-13

The repaired source ran against a V3 probe and the maintainer's original STM32F103
project/AXF, one float channel, SWD 30 MHz and CDC MUX. A real headless Edge browser
loaded the existing production GUI and rendered SuperWatch. Each configuration
ran for approximately ten seconds; WebSocket frames received by that browser
were counted through Playwright. Sampling stopped and the SDK/browser sessions
were released after each interpreter's run. No firmware or power changes.

| Python | Requested interval | Backend rate snapshot | Browser samples received | Metadata frames | Sequence gaps / backend drops |
| --- | --- | ---: | ---: | ---: | --- |
| 3.11.16 | 1 us | 261,664 Hz | 2,731,389 | 11 | 0 / 0 |
| 3.11.16 | 50 us | 21,685 Hz | 203,280 | 10 | 0 / 0 |
| 3.14.5 | 1 us | 259,304 Hz | 2,711,323 | 11 | 0 / 0 |
| 3.14.5 | 50 us | 21,676 Hz | 204,840 | 10 | 0 / 0 |

All four runs reported zero read/CRC/parser errors and zero firmware sample-drop
flags. Browser telemetry showed `transport 0 / backend 0/0`. Backend rate is an
instantaneous window, while received totals include screenshot/stop/drain time;
they must not be divided to infer a delivery ratio. Queue high-water marks were
at most 11. Visual inspection confirmed the curve rendered in both environments.

Python 3.11 used QueryPerformanceCounter for `perf_counter` and GetTickCount64 for
`monotonic`; Python 3.14 used QueryPerformanceCounter for both. This machine's
3.11 offset was about 0.39 seconds, not the customer's 34.8 seconds. The larger
positive and negative offsets were tested deterministically, not presented as a
reproduction of the customer's physical environment.

Initial browser harness attempts navigated before app initialization completed
and timed out on the configuration page. The harness was corrected to use the
visible Dashboard and SuperWatch controls; completed runs are reported above.
No product navigation change was needed. One third-party deprecation warning in
the Python 3.11 Starlette test client does not affect these results.

Local JSON, screenshots and execution logs are retained under the ignored build
root's `reports/v035-superwatch` directory; device identifiers, paths and raw
customer evidence are not published. This is a targeted source repair, not a
release qualification or a guarantee of lossless sampling at arbitrary loads.
The customer's exact machine and installed package still require post-update
confirmation. No version tag or release channel was changed; local candidate
installation is recorded below.

## WebGUI, Skill and Windows desktop package consistency

The repaired backend is shared by the WebGUI, SDK/CLI/MCP Skill and frozen
desktop sidecar. The fix is commit `cf118751`; production Web assets were rebuilt
and preserved in `75a73a5a`. Local NSIS and Skill candidates were generated from
these revisions. They retain the existing 0.3.4 product version and are development
candidates for the 0.3.5 repair branch, not a published 0.3.5 release.

Package comparison checked all 195 Python source files and 38 production Web
files. Python sources match byte for byte; 19 Skill Web files differ only in line
endings, while frozen Web files match byte for byte. The four changed manager
methods' frozen bytecode also matches compilation of the repaired source. Built-in
resource validation covered 7,059 target entries, 2,224 FLM blobs and 4,800 SVD
targets. Distribution/runtime/MCP tests passed 107 with one optional `hil_core`
test skipped; the four affected GUI suites passed 206 tests.

The actual extracted Skill and NSIS sidecar were each launched through stdio MCP,
then connected to the same V3/F103 board and original AXF. Real Edge pages consumed
their streams. MCP ping, MCU inspection, security metadata, watch control, latest
values, stream display, stop/detach and normal backend exit passed. The frozen
process ran with Windows-only PATH and no host Python path or source overrides.

| Distribution | Interval | Backend rate snapshot | Browser samples | Metadata frames | Sequence gaps / backend drops |
| --- | --- | ---: | ---: | ---: | --- |
| Extracted NSIS sidecar | 1 us | 265,675 Hz | 2,868,807 | 12 | 0 / 0 |
| Extracted NSIS sidecar | 50 us | 21,681 Hz | 206,300 | 10 | 0 / 0 |
| Extracted Skill | 1 us | 264,377 Hz | 2,745,486 | 11 | 0 / 0 |
| Extracted Skill | 50 us | 21,679 Hz | 206,480 | 10 | 0 / 0 |

All four package runs had zero read, CRC, parser and firmware sample-drop errors.
The native desktop executable from the NSIS payload also started with Windows-only
PATH. Its real WebView rendered SuperWatch at about 260 kHz. A 35-second 1 us run
completed 9,230,741 reads with zero read errors and backend drops; the backend rate
snapshot was 267,080 Hz. The watch stopped, SDK detached, and closing the native
window normally released both desktop and sidecar processes. This validates the
desktop payload, not the Windows installer transaction.

The first elevated overwrite installation was cancelled at Windows elevation.
After the user explicitly requested another attempt, the NSIS installer completed
with exit code 0. All four installed payload files match the candidate hashes.
The actual installed sidecar then passed stdio MCP and real Edge/V3/F103 checks
with Windows-only PATH: 1 us produced a 261,696 Hz backend snapshot, 2,745,486
browser samples and 11 metadata frames; 50 us produced a 21,650 Hz snapshot,
206,500 samples and 10 metadata frames. Both runs had zero sequence gaps, backend
drops, read errors, CRC errors and firmware sample-drop flags. Stop, detach and
normal backend exit passed. The installed native window also started and closed
normally. Global Skill installation was not replaced; its candidate was validated
in extraction. Package checks establish consistency for the affected SuperWatch
path and bundled implementation, not a new certification of every product feature
or every supported chip.

Candidate hashes and detailed package/desktop evidence are retained in the local
build artifact directory `v035-clock-cf118751`. The isolated worktree initially
lacked its native STCP build artifact; supplying the existing built dependency
allowed packaging to complete. No runtime fallback to host Python was introduced.
PR: [#43](https://github.com/MicroKeen/Mklink-AI-Probe/pull/43).
