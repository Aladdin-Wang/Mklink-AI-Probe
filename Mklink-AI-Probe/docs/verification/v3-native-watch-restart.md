# V3 native Watch restart investigation

Date: 2026-10-07. Candidate application: cb1cf41b28ea, extracted NSIS payload.
This is candidate desktop evidence, not an overwrite-install acceptance result.

## Observation

With two probes attached, explicitly selecting V3 connected on the first attempt.
The target was the existing STM32F103 test fixture. One changing integer was
collected at a requested 1 ms interval; the displayed rate was approximately
1000 Hz. Point-only rendering was already enabled and was left unchanged.

After pausing, the visible time range was approximately 9.4–18.5 seconds.
Two wheel interactions over the time axis reduced it to approximately
11.3–17.3 seconds. The curve remained visible. Clicking **Start**, rather than
Resume, began a fresh acquisition. At about 9 seconds its view spanned the full
new history, and at about 23 seconds it spanned approximately 0–23.76 seconds.
Thus the desktop observation did not retain the selected absolute time span.
The previously reported half-empty plot was not reproduced in this run.

Collection was stopped, the selected variable removed, the search cleared and
the owned desktop window closed. No firmware or target program was changed.

## Investigation boundary

A new component/runtime test covers a finite paused zoom, Start, a stream reset,
unchanged channel metadata, and new history growing beyond the chosen span.
That test passes against the existing implementation. It does **not** reproduce
the native failure and must not be reported as its fix. The next investigation
must observe the actual runtime channel reconstruction and viewport lifecycle.

An attempted source Web GUI launch with explicit project/AXF arguments returned
HTTP 409 (`Detach before changing the session scope`). A launch without those
arguments started, but browser automation refused the local URL with
`net::ERR_BLOCKED_BY_CLIENT`. No Web UI acceptance is claimed. The unattended
launcher expired and released its client. No cancelled installation was retried.

Validation: WaveformViewer.test.ts: 108 passed. Project memory validation and git diff --check passed. Final runtime status was an empty list.

## Follow-up: first full buffer overwrites explicit zoom

A second native run reproduced the widening view after Start. A read-only
acquisition-status snapshot reported zero CRC errors, parser frame drops,
firmware sample-drop flags and backend dropped items. These counters describe
transport integrity; they do not prove uniform target sampling.

Inspection of the owned test WebView showed that initial capacity attachment
arms `superwatchTimelineCapturePending`. When the first full history arrives,
`captureSuperwatchTimelineSpanIfReady` unconditionally replaces the current
span with half the measured buffer duration, including after a user zoom.
A regression demonstrated an explicit 0.4-second view changing to 7.5 seconds.

The source now distinguishes explicit zoom from the initial default. It still
learns the measured default for axis reset, but preserves the chosen span and
lag when that default becomes available. An explicit axis reset clears that
choice. Stream restart leaves it intact.

Validation: 109 waveform tests passed; Vue type checking and production build
passed. Native post-fix validation remains pending; this proven overwrite path
must not yet be claimed to explain every native restart symptom. Both owned
windows were closed, runtime status was empty, and the temporary loopback
WebView diagnostic listener was no longer present. No firmware was modified.

## Native post-fix verification

The native frontend built at ac29feac was exercised with the unchanged
cb1cf41b sidecar. This mixed candidate isolates the frontend change; it is
neither a new installer nor installed-version acceptance evidence.

An initial shell-launched diagnostic instance failed probe selection with
HTTP 500. Its lobby log located WinError 5 at subprocess.Popen while creating
the probe runtime, before target connection. After closing that owned instance,
the exact same payload launched through the normal desktop application path
connected to explicitly selected V3 on the first attempt with both probes
attached. This supports a launch-context dependency, not a firmware failure;
the underlying Windows job constraint was not independently proved or changed.

In the normal native run, one changing byte was collected at 1 ms. At about
28108 points, Pause followed by a wheel zoom selected an approximately
11-second time window (2 s/div). Clicking Start reset the acquisition history.
At about 16242 new points the visible axis covered approximately 5–16 seconds;
after reaching the full 50000-point history it covered approximately
40–51 seconds, still at 2 s/div. At Stop around 65 seconds it retained that
span. The curve remained visible across the plot and the displayed rate was
approximately 1000 Hz. Thus this native sequence now preserves explicit zoom
across restart and first full history. It does not certify every zoom, pan,
trigger or multi-channel combination. Sampling was stopped and the owned
window closed normally. No probe or target firmware was changed.

## Packaged native recheck: 3e65f1ad

Exercised the extracted NSIS desktop and matching frozen backend, with its
footer and process path confirming 3e65f1ad. The launch helper initially resolved
the older installed application by basename; that window was closed normally
and excluded from qualification. Launching the explicit process path selected
the candidate correctly. No installer was executed.

With both probes attached, explicitly selecting V3 connected on the first
attempt. The KK startup animation displayed. RTT channels 0–7 each received
their matching channel/sequence output in the three-column layout. Counters
increased, with buffer zero and drops 0/0. Stopping acquisition succeeded.
Several terminal viewports remained at earlier sequence positions while their
line counters increased, following window maximization and panel scrolling.
This needs an isolated terminal follow/resize investigation; it is not evidence
of firmware packet loss or a completed terminal usability acceptance.

With RTT stopped, collected one changing byte at a 1 ms interval. Paused at
about 24140 points and zoomed the horizontal axis from 2 s/div to 1 s/div,
leaving roughly a ten-second visible span. Start reset acquisition history.
At 20476 points the plot covered approximately 11–20 seconds. After reaching
the 50000-point buffer it covered approximately 51–60 seconds, still at
1 s/div, with data across the plot. Stop around 71 seconds retained that span.
Displayed rate was about 996–1000 Hz. This confirms the specific pause/zoom/
Start/first-full-buffer sequence in the complete candidate, not every gesture
or sampling configuration.

Closed the owned desktop normally. At an eight-second post-close check no
candidate desktop or sidecar process remained; the V3 console reopened and
closed without sending commands. This check is not a precise shutdown timing
measurement. Firmware, target Flash, voltage and protection were unchanged.
The earlier cancelled overwrite installation and blocked browser qualification
remain separate, unresolved gates.

## Terminal follow investigation: controlled browser exclusions

Ran the current xterm 6 dependency and then the actual RttTerminalPanel Vue
component in a local Chromium fixture, with eight panels and synthetic text.
No device backend was involved. Read the public active-buffer baseY and
viewportY rather than inferring reception from screenshots alone.

All eight components followed output while offscreen: after 200 lines both
positions were 181. Switching from a one-column 950-pixel container to a
three-column 1600-pixel container changed columns from 119 to 64 without
separating the positions. Another 100 lines moved both to 281; scrolling the
outer grid to the last panels retained equality. Clear followed by 100 lines,
switching back to the narrow layout, hiding the grid during another 100 lines,
showing it, and continuing output also retained equality on every panel.

Explicitly scrolling one terminal back by 50 lines produced base 281/view 231.
Another 30 lines advanced its base to 311 while view stayed 231; the other
seven remained at 311/311. Resizing again preserved that intentional history
position. Thus unconditional scroll-to-bottom on writes or resize would break
valid history reading and is not justified by the native observation.

These exclusions do not reproduce or fix the desktop symptom. Native WebView
scroll events and the full acquisition-to-terminal path still need isolation.
The local fixture servers and owned browser session were closed. Production
code, dependencies and firmware were unchanged; fixture files remain only in
ignored build reports.

## Native reproduction confirmed, reception distinguished from scrolling

A fresh run of the same candidate connected V3 on the first attempt with both
probes present. Started eight channels in the small desktop window, waited for
output, maximized into three columns, then scrolled the outer grid to channels
6 and 7. Their visible text remained at sequence 24620 while line counters
increased from 450 to 833 and then 937, with drops 0/0. A downward wheel action
inside channel 7 revealed sequence 24909 and later records; channel 6 remained
at the earlier position. This confirms buffered newer output and a viewport
follow symptom, rather than proof that the terminal stopped receiving.

The browser component fixture was extended to resize during continuous writes:
400 records with a width change after 900 ms, followed by 300 records with a
panel-height change after 200 ms. All eight viewports still equalled their
buffer bases (381 and 672 respectively), including after revealing the last
row. This controlled case does not reproduce the WebView behavior. The bundled
dashboard includes the current xterm viewport synchronization implementation;
there is no evidence here supporting a dependency downgrade or a firmware fix.

Stopped acquisition and normally closed the owned desktop. Candidate processes
were absent at the subsequent check. The owned browser session and local
fixture server were also closed. No production patch is claimed. Next
investigation should capture WebView buffer/viewport and scroll-event ordering
at the resize boundary, preserving intentional history browsing.

## WebView component and channel-layout exclusions

Ran synthetic eight-panel fixtures inside the exact candidate's WebView2
engine (Edg/130.0.2849.56), with the current Vue terminal component and global
theme/viewer CSS. During continuous output, a real native maximize changed
columns from 75 to 71. All eight baseY/viewportY pairs remained equal at 2578,
including after revealing the lower row, and advanced together to 2678.
Reading the native accessibility tree during another maximize run did not
change that result.

Expanded the fixture to the actual RttChannelPanel layout and its terminal
child. Synthetic text entered the child's exposed write method; device streams
were disabled. All eight pairs progressed 75/75, 275/275 and 375/375 across a
container-width change and outer-grid scrolling. This excludes those controlled
layout cases, not the production worker/stream path or the original native bug.
No production fix is claimed. Next capture should instrument the full native
acquisition page, including input and scroll events, rather than add another
unconditional scroll-to-bottom patch.

Owned fixture processes and temporary loopback diagnostic listeners were
closed; subsequent checks found no candidate desktop or listeners on the two
diagnostic ports. No hardware or production source was changed in this step.

The maintainer clarified the V3 performance policy: RAM footprint is secondary
to acquisition continuity. Future batch-work experiments may use additional
bounded buffers where measured headroom permits. Compare P99/maximum gaps,
average throughput and DAP preemption against the retained baseline; smaller
work units alone do not establish an improvement. V3 has no display.
