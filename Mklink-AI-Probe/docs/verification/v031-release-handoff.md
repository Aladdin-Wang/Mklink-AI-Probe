# 0.3.1 official publication handoff

The maintainer explicitly authorized application 0.3.1 and the supplied MicroLink V4.6.3 UF2 publication on 2026-10-09. Publication and channel readback are complete.

- PR #33 merged the exact checked head `c9fa5a3a1e94e32e8b0db37e100e303dbf92685f`; feedback, shared-runtime and shared-GUI CI passed. The designated integrator rule was used without weakening the independent PR/CI rules.
- Immutable application source/tag: `1d61159d8990fe2f9e879100d149be50b32b9a33` / `v0.3.1`.
- Clean isolated main equalled MicroKeen/main at publication. Existing changes in the primary checkout were preserved.
- Product code equals the fully tested `f586fd94` tree; the intervening changes are documentation. Python 4576 passed / 2 optional hil_core tests skipped; GUI 912, desktop Rust 21 and Site Agent Rust 6 passed. The release clone additionally passed 88 GUI files / 912 tests in 81.29 seconds after a clean locked dependency install.
- Standard NSIS and updater signature were rebuilt from merged main. Windows Authenticode signing is still absent; updater signing is separate.
- UI build identity remains `77d4849c5f73`. Fresh generated Web resources were preserved in the signed sidecar and substituted into the source-archive Skill payload; the exact compiled Web hashes are retained locally. Runtime sources came from the tagged commit, and both packages have the same actual compiled resources. Generated checkout files were restored after preservation to satisfy clean-main publication.
- The unchanged, already qualified STCP DLL was reused after checking its SHA256 and absence of STCP source changes. First clean-clone build stopped because that non-tracked input was absent; the corrected signed build succeeded.
- Skill algorithm validation: 7059 targets / 2224 blobs. Site Agent core and native portable bundle were rebuilt and their audited manifests retained.

## Exact package qualification

The newly signed NSIS was extracted for qualification. Administrator/UAC installation verification was explicitly waived by the maintainer; extraction is not an overwrite-install claim.

- Windows-only PATH: actual frozen stdio MCP initialized, inspect_mcu/security_status passed, CLI runtime status passed.
- Isolated frozen lobby health, production resources and probe enumeration passed, with no target connection. Startup 4.825 seconds; 36 compiled assets matched the served bytes.
- Native extracted desktop opened its configuration page with the expected build identity; startup 10.340 seconds. Its process tree contained no Python process. No target connect, power change, flash or reset was performed.
- The qualification window closed normally; all its processes and endpoint files disappeared. The user's already-running installed application was preserved. Global ports need not be empty while that application remains open.
- Earlier physical acceptance and timestamp evidence remain scoped to their exact binaries and firmware in v031-hardware-acceptance.md and v031-dump-queue.md; this publication check does not repeat every hardware matrix.

## Publication

Identical seven-file releases exist on MicroKeen GitHub, legacy Aladdin-Wang GitHub and Gitee. The publisher checked anonymous GitHub asset downloads and Gitee installer/Skill downloads against SHA256 and size before updating indexes. Readback of MicroKeen release/latest.json, legacy GitHub updates/latest.json and Gitee updates/latest.json confirms 0.3.1, the exact source, payload hashes and updater signature. No source branch was pushed to the legacy mirrors.

| Payload | Bytes | SHA256 |
| --- | ---: | --- |
| Mklink-AI-Probe-v0.3.1-Skill.zip | 18758779 | `601721e0b8051b1c3c876fe4170fb6c507ba8e9679d5657ddea9a843d98cafe6` |
| Mklink-AI-Probe-v0.3.1-x64-Setup.exe | 96805960 | `c1dcaa1c385493403366647633a3b7562fa204c0910c6770249f9625932304c9` |
| Mklink-AI-Probe-v0.3.1-x64-Setup.exe.sig | 428 | `30252438c165daa23c2afb999dee184ca3ee76d8c7793eb0db8f7c242846b5f8` |
| MKLink-Site-Agent-v0.3.1-windows-x86_64-portable.manifest.json | 2391 | `d4f7aa78f8733a031189eeb04c02f6e57bfad7eb4c5dcb2258b454d4ca052508` |
| MKLink-Site-Agent-v0.3.1-windows-x86_64-portable.zip | 66847654 | `d33da4f0787c0506a5c1f7995a51793c0fea704e7dcbc8f48f6d173c2696a6a5` |

Release URLs: https://github.com/MicroKeen/Mklink-AI-Probe/releases/tag/v0.3.1 and https://gitee.com/Aladdin-Wang/Mklink-AI-Probe/releases/tag/v0.3.1 .

## Supplied V4.6.3 firmware

The user specifically supplied the newly rebuilt MicroLink_V4.6.3.uf2: 1625600 bytes / 3175 valid UF2 blocks, SHA256 `e960cb70c83ce769442933658bad3c25bcb077f39d2eb031820d94bc764a6937`. That exact file was uploaded and downloaded/hash-verified on both GitHub repositories and Gitee; all three firmware/latest.json indexes read back V4.6.3 with this hash. Other family/model versions are unchanged.

This is different from the previously flashed and physically accepted V4.6.3 binary (`605686ab804c983ac844ccb5b14b9070edb9d5eac15db2bca786f2d524f478eb`, 1627136 bytes). The firmware session verified UF2 framing, equality to the adjacent BIN payload and ten critical SWD entry addresses. The new binary has not inherited the earlier binary's physical acceptance statistics; the user was informed of the distinction before publication.

## Next-version work and evidence

At the maintainer's request, the unresolved 30 MHz Flash128B / 1kHz continuous-read status 5 limitation is kept in this handoff and earlier verification reports, omitted from official release notes and updater notes. The explicit 10 MHz alternative is not a proof of a 30 MHz fix. Firmware follow-up remains with its original session; do not automatically lower the clock or suppress errors.

Missing physical fixtures, old-model upgrade coverage, optional private hil_core tests and installation waiver retain their earlier limits. The mklink heartbeat and long-running validation remain paused. VCC changes still require a specific voltage confirmation.

Evidence: `.build/artifacts/v031-official-20261009/` contains signed files, release-manifest, compiled-web hashes, build/test logs, frozen/native checks, firmware-indexes.json and public-indexes.json. `.build/reports/v031-official-firmware-*.log` records firmware publication. No local identifiers, screenshots, firmware binaries or signing secrets are committed with this report.
