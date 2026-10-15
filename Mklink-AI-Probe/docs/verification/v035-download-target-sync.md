# 0.3.5 download access and shared chip defaults

Date: 2026-10-15. Branch: `codex/0.3.5-fixes`, following `e3e2f4c0`.
This is source/production-Web verification, not a new installer qualification.

## Behavior

- Online probes and offline USB volumes can be discovered without first using
  Configuration → Connect. Before a download or online memory read, the GUI
  reserves the explicitly selected physical probe without opening a target
  debug connection. CMSIS-DAP serials resolve to exactly one inventory identity.
- Hardware requests carry that identity and device generation. Occupied probes,
  ambiguous inventories, stale requests and unknown-result receipts retain their
  existing protections. A failed reservation does not submit an online job.
- The download form survives the generation change caused by its own reservation.
  Other connection/disconnection or device-switch transitions still discard cached
  download state. This also avoids losing the first read result during status polling.
- Selecting an installed online target supplies the offline and peripheral defaults.
  Each page can override its model; returning to the online page with the same
  selection does not overwrite those choices. A new online selection supplies new
  defaults. Multiple SVD matches remain an explicit user choice.
- Pack import/install/removal/index completion notifies the consumer pages, which
  also refresh on activation. The peripheral “Refresh packs” button is removed.
  Offline algorithm lookup remains local when no probe is bound, including legacy
  MCU profile candidates; it does not rediscover a disk behind the caller's back.

## Verification

- Affected Python coverage: runtime switching, online flash API, offline algorithms,
  deployment receipts, remote identity, Pack invalidation and new download selection
  cases: 301 passing cases on the final Python code.
- GUI coverage includes online/offline views, peripheral selection, default/override
  persistence, identity headers, refused selection, status-poll timing before/after
  reservation, App navigation and memory-read panels: 185 distinct passing cases.
- `vue-tsc -b` and Vite production build pass. Tracked `gui/dist` is regenerated.
  Existing large-chunk warning remains.
- Real Chrome with the source backend, physical V3 and STM32F103RC: from an
  unselected, disconnected backend, offline disk discovery and four local algorithm
  candidates load. Online CMSIS-DAP discovery works without Configuration → Connect.
  A 64-byte Flash read at `0x08000000` completes and remains displayed after polling;
  backend reports HTTP 200, `connected=false`, and no active operation afterward.
- Initial read was correctly refused because an installed backend held the probe.
  Its status showed no running streams or operation. Using the user's existing
  disconnect-test authorization, it was disconnected; the source test then passed.
- Real browser confirms STM32F103RC defaults in both consumers, automatic unique SVD
  selection, absence of the refresh button, and an independent STM32F103RE override
  surviving navigation. A local synthetic Pack imported through the online file
  chooser appears in peripheral SVD choices and offline chip search without manual
  refresh. The synthetic Pack was removed through the API and its target absence
  confirmed; the actual peripheral default was restored.

## Failures found and scope limits

Real-surface testing found two defects missed by initial component fixtures:
legacy profile discovery still touched the unbound disk, and the App generation
key unmounted the submitting download form. Both are fixed with regression cases.
Earlier Python resource failures came from absent ignored built-in FLM files in the
worktree; reruns use the existing verified local resource root, without changing
the whitelist. GUI fixtures were updated to model the reservation request and
the actual reactive device-status contract. One browser upload attempt lost its
debugger attachment; a fresh test tab completed the import.

No erase, firmware flash, voltage change or offline trigger was issued in this
round. Offline deployment/trigger paths have fixture coverage; this run proves real
volume discovery and online target reads, not complete physical flashing. The
earlier unknown HEX failure remains open and was not replayed. Local evidence stays
under the build artifacts directory; hardware identities and screenshots are not
committed. No installer/global Skill update, merge or release is included.
