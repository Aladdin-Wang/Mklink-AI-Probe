# Mklink Site Agent package v0.1.4

This ZIP is the standalone Windows field-side Site Agent. It includes the
Python runtime and remote-agent dependencies; the field machine does not need
Python, Node.js, Rust, Codex, an engineer Skill, or a source checkout.
The candidate is unsigned and intended only for same-LAN or managed-VPN
connections. It supports direct WebSocket connections and an optional
in-process FRP/STCP client in `mklink-stcp.dll`. It never extracts, renames,
launches, or requires `frpc.exe`; it does not bundle `frps`, NAT traversal, or
public-relay components.

## Start and readiness

Set a token in the process environment and keep the agent in the foreground:

```powershell
$env:MKLINK_REMOTE_TOKEN = Read-Host -MaskInput "Site token"
.\mklink-remote-agent.exe start --host 127.0.0.1 --port 8766
```

The default host is loopback. Binding a LAN or managed-VPN address requires
both `--allow-lan` and a token. Wildcard listeners are rejected. A successful
start emits one compact JSON line with schema
`mklink.site-agent.lifecycle.v1`, event `ready`, the bound port, PID,
probe state, and `owned_children: 0`. The process remains in the foreground.

Use `--ready-file PATH` when a service manager needs atomic file-based
readiness. The file contains the same non-secret event and is removed during
an orderly stop.

For file-based authentication, pass `--token-file PATH`. The file must already
have owner-only permissions. Tokens are never accepted as command-line values.
`--no-token` is limited by the listener policy to loopback development.

## LAN STCP without frpc.exe

Run an operator-managed `frps` on a LAN address. Keep the Site Agent listener
on loopback, then provide three distinct secrets through environment variables:

```powershell
$env:MKLINK_REMOTE_TOKEN = Read-Host -MaskInput "Site Agent token"
$env:MKLINK_STCP_AUTH_TOKEN = Read-Host -MaskInput "LAN frps auth token"
$env:MKLINK_STCP_SECRET = Read-Host -MaskInput "Site STCP secret"
.\mklink-remote-agent.exe start `
  --transport lan-stcp `
  --host 127.0.0.1 `
  --port 8766 `
  --stcp-server-addr 192.168.1.10 `
  --stcp-server-port 7000 `
  --stcp-user field-a `
  --stcp-proxy-name mklink-field-a
```

The in-process provider becomes part of the foreground Site Agent lifecycle;
`owned_children` remains `0`. The LAN server address must be concrete, the
forwarded service must be loopback, and the three credentials must not be
reused. Use the corresponding `--*-file` options for owner-only files.

On the engineer host, start an in-process visitor and register its local URL:

```powershell
python -m mklink remote stcp visitor `
  --server-addr 192.168.1.10 `
  --server-port 7000 `
  --user field-a `
  --proxy-name mklink-field-a `
  --bind-port 8767
python -m mklink remote sites add field-a ws://127.0.0.1:8767
```

The visitor binds only a loopback IP. Neither side starts a separate FRP
client executable, and no server port exposes the Site Agent payload publicly.

## Health and lifecycle

Each control command loads the same token source and emits structured JSON:

```powershell
.\mklink-remote-agent.exe health --host 127.0.0.1 --port 8766
.\mklink-remote-agent.exe status --host 127.0.0.1 --port 8766
.\mklink-remote-agent.exe stop --host 127.0.0.1 --port 8766
.\mklink-remote-agent.exe restart --host 127.0.0.1 --port 8766
```

`stop` requests cooperative shutdown through the authenticated public
protocol. `restart` requests that shutdown, waits for the listener to close,
then the invoking process becomes the replacement foreground agent. The
package creates no product worker or supervisor child. Windows may attach an
operating-system `conhost.exe` console host; it is not a Mklink worker and
exits with the foreground agent. The readiness field `owned_children: 0`
means zero product-owned worker children.

Exit code `0` means the requested lifecycle operation completed. Exit code `2`
is a redacted configuration, authentication, connection, or runtime failure;
`130` means the foreground process was interrupted.

## Removal

Stop the listener, verify the foreground process has exited, and delete the
extracted package directory. Runtime uploads are stored below the configured
`--project-root` (the current directory by default), not inside this package
unless that directory is chosen as the project root.
