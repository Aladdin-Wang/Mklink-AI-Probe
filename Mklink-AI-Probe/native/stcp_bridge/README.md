# MKLink in-process STCP bridge

This directory builds the official FRP v0.69.1 client packages as
`mklink-stcp.dll`. The library is loaded into the existing Site Agent or
engineer process. It never extracts, renames, launches, or requires
`frpc.exe`.

Build on Windows with Go 1.25 or newer and a C compiler:

```powershell
go mod download
go build -buildmode=c-shared -trimpath -ldflags="-s -w" -o mklink-stcp.dll .
```

The runtime accepts only:

- an STCP provider that forwards to a loopback service;
- an STCP visitor that binds a loopback listener;
- token-authenticated TLS connections to an operator-supplied LAN `frps`.

The DLL is a transport component only. Site Agent authentication remains a
separate protocol layer and its access token must not be reused as the FRP
authentication token or STCP secret.
