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
