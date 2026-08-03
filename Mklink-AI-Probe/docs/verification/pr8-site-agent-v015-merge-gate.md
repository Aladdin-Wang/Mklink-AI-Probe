# PR #8 Site Agent v0.1.5 merge gate

> Date: 2026-08-03 (Asia/Shanghai)
>
> Target: `su5176/Mklink-AI-Probe#8`
>
> Tested runtime tip: `efbc44f1a289782b60f5741a00ce144b2764e3f4`

## Scope and version strategy

The Site Agent core, build provenance, wheel/distribution audit, portable GUI
manifest, GUI status, package README, and third-party notice now use product
version `0.1.5`. The core builder reads the project version from
`pyproject.toml` and rejects provenance, wheel, or bundled distribution
metadata that does not match it. The GUI packager separately pins the exact
qualified core ZIP, core executable, and in-process STCP library hashes.

No signing, tag, Release, updater-manifest, latest-channel, or Gitee operation
was performed.

## Reproducible artifacts

Two independent clean core builds and two independent portable GUI bundle
builds were byte-identical.

| Artifact/input | Size | SHA-256 |
|---|---:|---|
| Site Agent core ZIP | 18,500,552 bytes | `BF67DDF54C68F8DD7D36EB74DCB549CD83A019C829020398C3D9E06211F432EA` |
| Packaged core EXE | 5,336,211 bytes | `F7B1181B98B25CDBB9D574857A0A1A671608981129C005E2D30F7288E559351D` |
| Qualified `mklink-stcp.dll` | 15,822,336 bytes | `0D17B6CE89DE3D15E6629F4C5A087E0BBF1D809BF4516AA52786BE7175D2E9E9` |
| Site Agent GUI EXE | 9,354,240 bytes | `2BF666CE43702B382759A6ADF7B911530977610227686E657DC0B66DC81970CA` |
| Portable GUI ZIP | 21,246,847 bytes | `031DD8C564619C1DE67FFF4CFA00753FBCB4CE4CCA28518C8DC51877E9972E8F` |

Both manifests report bundle/core/product version `0.1.5`. The core package
contains `mklink-0.1.5` distribution metadata, removes local installation
origin metadata, contains no `frpc`/`frps`, and leaves no staging directory.

## Automated and production gates

| Gate | Result |
|---|---|
| Independent clean package/content audit | `4 passed` |
| Full Python suite | `1242 passed, 1 skipped` |
| Web GUI | 48 files, 491 tests passed |
| Web type check and Vite 8.1.5 production build | PASS |
| Site Agent Rust tests | 5 passed |
| Site Agent Rust release build | PASS |
| Runtime npm audit | 0 vulnerabilities |
| Full npm audit | 1 high, development-only transitive `brace-expansion` finding |
| `git diff --check` at the tested runtime tip | PASS |

## Packaged lifecycle and hardware evidence

The new `v0.1.5` core ZIP was extracted and run as the real packaged Windows
process. With credentials supplied only through process environment state, it
passed ready, health, status, capabilities, wrong-token rejection, cooperative
stop, site deletion, and listener/process cleanup. A project directory whose
inherited ACL could not be reduced to owner-only was correctly rejected; the
same candidate passed when run from a task-owned current-user directory whose
ACL could be enforced.

No MKLink CDC probe was connected during this final merge gate, so no new
physical-probe result is claimed. The integrated real-hardware qualification
recorded by commit `2bbbcc0b31e23256834866f1e3f1dad60b5f05fb` is an ancestor
of the tested tip. Between that evidence commit and the tested tip, the Git
trees for `mklink/remote` and `native/stcp_bridge` are byte-identical. The only
later affected files are version/build-contract code, package documentation,
and Site Agent GUI version reporting. The existing combined STM32 Site Agent
HIL therefore continues to cover probe reconnect, target identity, registers,
safe RAM restoration, RTT/SystemView, and cleanup, while this gate newly
qualifies the `v0.1.5` package identity and lifecycle.

Cleanup verification found zero temporary sites, listeners, Site Agent/GUI
processes, or `frpc` processes. Task-owned HIL directories were moved to the
Windows Recycle Bin. No plaintext credential file was created.

## Verdict

The `v0.1.5` version strategy and affected package surfaces are qualified for
merge. External managed-LAN STCP was not rerun because no independent LAN
`frps` endpoint was available; this remains an existing conditional limit and
is not represented as a fresh PASS.
