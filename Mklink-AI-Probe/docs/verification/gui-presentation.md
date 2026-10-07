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
