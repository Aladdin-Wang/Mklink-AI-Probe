# Issue #8: standalone SuperWatch stream health

## Scope and cause

Based on main `9758c677`. The standalone `superwatch --visualize` page had an
unbounded raw-log text node, rebuilt the trigger selector on every point, accepted
malformed regions as timestamp-only points, and lacked a valid-sample watchdog.
An SSE connection alone therefore did not establish that acquisition was healthy.

The desktop dashboard has a separate waveform implementation. This fix targets
the standalone path reported in #8; it does not replace the dashboard transport.

## Changes

- Validate firmware error flags, region identity, complete region lengths and
  variable lengths before emitting values.
- Stop and synchronize the old dump session before bounded recovery; stop trying
  when synchronization fails or three consecutive recovery attempts are exhausted.
- Expose last valid sample age, arrival-based rate and fault state through status.
- Bound raw logs to 5,000 lines and throttle rendering; cache trigger options.
- Reset render generation and time/rate state after session reset or SSE reopen.

## Verification (Windows, 2026-10-02)

- Focused Python suite: `test_standalone_superwatch_health.py`,
  `test_dump_memory_session.py`, `test_rtt_superwatch_streaming.py`: 140 passed.
  Tests run through `scripts/build_workspace.ps1`.
- Real Chrome, real standalone server: injected 600,000 points through
  `processPoint` while live hardware samples arrived. Finished in 10.9 seconds;
  raw-log storage and DOM both stayed at 5,000 lines; channel buffers at 500.
- V4 probe reported V4.5.2; target STM32F103RET6, eight scalar channels, 50 ms
  interval. Existing firmware build identity matched the local project.
  Normal live sampling ran for several minutes at approximately 20 Hz.
- Host-side fault injection while reading that physical target: discard frames
  for six seconds, then inject a region-error frame. Both caused a serialized
  stop/start recovery. A 90-second run emitted 6,584 nonempty data points with
  two recoveries and two timeline resets. A repeat run verified live Chrome
  resumed after both resets without a page reload.
- Replaced the browser EventSource connection against the running `/stream`
  endpoint: render generation advanced from 3 to 4, sample time advanced and
  39 fresh points arrived in two seconds. This tests SSE reopen, not a physical
  USB unplug.

No target/probe firmware was rewritten. No voltage, protection or flash changes
were needed. Raw hardware logs and screenshots remain local and untracked.

## Limits

This is finite-duration Windows/V4.5.2 verification, not a seven-hour soak or a
reproduction on the reporter's Linux ARM64/V4.4.0 setup. Faults were deliberately
injected on the host; the current probe did not spontaneously corrupt regions.
Malformed old-firmware output is rejected and recovery is bounded, rather than
claiming that every firmware-origin failure is repaired.

## Playback inspection

SuperWatch currently exports CSV and supports examining retained live-session
history while paused. Both viewer implementations load display/channel settings
from project JSON, not sample logs. Neither exposes log-file replay, playback
speed or an offline replay timeline. SystemView's JSONL replay is separate.
