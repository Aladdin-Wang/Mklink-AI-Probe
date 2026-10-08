# MKLink 0.3.0 standalone remote service

Builds require the same complete, integrity-checked built-in FLM bundle as the
desktop package. Set `MKLINK_BUILTIN_FLM_ROOT` to that local asset directory
when it isn't installed in the checkout. The existing desktop asset validator
checks the catalog and every blob before building and again in the final bundle.
Only manifest-listed built-in FLMs are allowed; unrelated firmware, Packs and
FLMs remain prohibited. These assets are package inputs, not committed binaries.

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
listener has no supervisor worker. Connecting a physical probe can start a
separate shared runtime using the same executable, or attach to an existing
runtime. That runtime serves GUI/AI clients independently and is not stopped
when this listener stops. Windows may also attach a `conhost.exe` console host.
The readiness field `owned_children: 0` describes listener-owned workers only;
it is not a count of shared runtimes or all operating-system descendants.

Exit code `0` means the requested lifecycle operation completed. Exit code `2`
is a redacted configuration, authentication, connection, or runtime failure;
`130` means the foreground process was interrupted.

## Removal

Stop the listener and verify the foreground process has exited. Before deleting
or replacing the package directory, also detach its other GUI/AI clients and
explicitly stop any shared runtime running from this executable through the
shared runtime controls. Do not terminate another probe's runtime or assume
listener shutdown released the package's executable files. Runtime uploads are stored below the configured
`--project-root` (the current directory by default), not inside this package
unless that directory is chosen as the project root.


## Shared target operations in 0.3.0

Choose the command interface with `--device-port` when multiple probes are
present. A remote client calls `agent.reconnect` before target operations;
the selected USB identity remains fixed for the service lifetime. There is no
fallback to a direct exclusive CDC connection. Stop/restart the service to
choose another probe.

RTT and SystemView use shared subscriptions with version-2 read contracts.
Stopping a borrowed subscription does not stop another client's acquisition.
Offline deployment resolves uploaded references and passes through the shared
backend's identity and operation admission checks. `jobs.status` queries retained
flash/erase/reset and version-2 offline deployment jobs. Deployment requires a
stable `request_id`; keep it before sending and query `jobs.status` with that ID
on the same probe after a lost response. The Python client generates an ID if
omitted and exposes it as `error.request_id` on failure. Direct RPC requests
must supply it explicitly. Querying never resubmits. At most 64 records remain;
a missing record does not prove that an operation did not execute. Incomplete
rollback retains its backup path in the job record for manual inspection.
The GUI provides the same request ID and result-query controls. This journals
file deployment only; it does not turn deployment into a flash trigger.

The listener being ready does not prove target connectivity, packaged algorithm
coverage, physical deployment, or long-duration operation. Check the capability
handshake and operation result. This package does not include FLM/Pack assets or
target firmware; upload the algorithm and firmware needed for offline deployment.
BIN deployment also requires exact target metadata to validate the Flash range;
an uploaded FLM alone does not supply that catalog entry. Never substitute a
similar part number to pass validation. The remote dependency set includes
pyOCD for catalog and geometry queries, and the frozen package must include its
dynamic modules and resources.
