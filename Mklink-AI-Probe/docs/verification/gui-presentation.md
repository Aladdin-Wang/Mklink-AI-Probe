# Optional AI GUI presentation

2026-10-07. Shared capabilities `gui_windows` and `gui_present` reuse the existing
per-window presence WebSocket. Only upgraded local windows advertise support.
Presentation selects one window in the attached probe backend; multiple windows
require an explicit ID. No windows means no implicit launch. Supported dashboard
tabs are allowlisted; arbitrary URLs, scripts and device mutations are rejected.

One request per window, a three-second acknowledgement deadline, and a frontend
expiry check prevent queued/reconnected presentation replay. Only GUI acknowledgement
returns displayed; disconnect, timeout and navigation rejection are distinct.
It does not start/stop/reconfigure capture or reserve the CDC hardware operation lock.
Desktop focus/minimization and remote GUI presentation are not part of this interface.

Skill policy: ordinary diagnostics/capture remain in the background. Present only
when the user asks or when reviewing the result visually is useful. Use existing
capture/control APIs separately and keep their ownership/write boundaries.

Validation: 64 shared runtime/MCP/presence/presentation tests, 55 Skill boundary/link
checks and 27 GUI tests passed. Production TypeScript/Vite build passed. A real
browser moved from configuration to SuperWatch via the API; after manual RTT
selection a second request returned to SuperWatch. No hardware was connected in
that isolated navigation check. Installed desktop and live acquisition follow-up
are recorded separately when completed.


## Installed acceptance

Local unsigned NSIS built from 3cccf80d and overwrote the existing installation
with exit code 0. All three installed binaries matched the extracted NSIS
payload; all 39 bundled Web files matched the production build. The sidecar and
updated local Skill include the 7059-target/2224-blob algorithm catalog.

In local Chrome using the installed desktop proxy, Skill MCP inherited the
connected STM32 symbols, started the uint8 test counter at 1 ms, and requested
SuperWatch on the single selected window. The GUI acknowledged displayed;
Chrome visibly showed the waveform at 1000 Hz. Read cycles increased from 2006
to 27015, with zero reported read errors or backend drops. MCP stopped its own
capture and detached without closing the device. The browser remains open with
the captured waveform. No algorithm parameters or firmware were changed.

The first desktop launch from the agent shell hit Windows access denied while
spawning a probe backend (before serial access). After normal desktop launch,
the first connect succeeded. This environment-specific launch failure was not
silently retried as a hardware command and has not been claimed as a code fix.
Native foreground/minimize behavior and remote windows remain outside this
presentation interface. This acceptance is not full GUI or long-soak regression.
