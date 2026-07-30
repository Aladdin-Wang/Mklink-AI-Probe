# MKLink Site Agent Portable

This is the independent field-side control application. It owns the bundled
`runtime/mklink-remote-agent.exe` while the portable GUI/tray process is
running. It does not use the engineering GUI, FastAPI, a Windows service, or
any public tunnel.

The GUI supports direct LAN/VPN connections and optional LAN-local STCP. The
STCP client is embedded in `bin/mklink-stcp.dll` and loaded by the owned core
process. No `frpc.exe` is installed, extracted, renamed, or launched. LAN STCP
requires an operator-managed `frps` reachable by both endpoints; that server
is not included in the portable package.

The release layout must contain `portable.mode` next to
`MKLink-Site-Agent.exe`; the audited standalone core lives below `bin/`.
Runtime data is stored only below `data/`.

In STCP mode the Site Agent listener and the engineer-side visitor both remain
on loopback. The Site Agent token, FRP authentication token, and STCP secret
must be distinct. The GUI stores all three with Windows DPAPI CurrentUser;
plaintext is passed only to the owned core through inherited environment
variables and is never written to `config.json`, command lines, or logs.
