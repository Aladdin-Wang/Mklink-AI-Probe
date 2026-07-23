# Configuration Page and RTT Bidirectional Communication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the duplicated desktop configuration/connection tabs with one user-managed configuration workspace, move RTT address discovery into RTT View, and add binary-safe RTT DownBuffer transmission.

**Architecture:** Desktop-only paths live in a versioned frontend settings adapter and are selected through a Tauri dialog adapter with manual-input fallback. Existing project-init APIs remain untouched; RTT address discovery gains an optional source path, while RTT transmission is owned by the running `RttStreamManager` and exposed through a hex-payload REST endpoint. The RTT send bar is a focused Vue component integrated beneath the existing waveform/log display.

**Tech Stack:** Vue 3, TypeScript, Vitest, Tauri v2, Rust, FastAPI, pytest, Microsoft Edge/Playwright, NSIS.

---

## File Map

- Create `gui/src/lib/desktopSettings.ts`: versioned global desktop settings and RTT send-history persistence.
- Create `gui/src/lib/desktopSettings.test.ts`: storage parsing, migration, validation, and history bounds.
- Create `gui/src/lib/filePicker.ts`: Tauri dialog adapter with browser-safe cancellation/fallback behavior.
- Create `gui/src/lib/filePicker.test.ts`: adapter filters, cancellation, and unavailable-plugin behavior.
- Create `gui/src/views/ConfigView.test.ts`: user-facing configuration-page contract.
- Modify `gui/src/views/ConfigView.vue`: remove project-oriented UI and merge all connection sections.
- Create `gui/src/components/config/ConfigSectionNav.vue`: compact left-side section selection.
- Create `gui/src/components/config/FileSourcesPanel.vue`: AXF/ELF and MAP editing, browsing, persistence, and parse command.
- Modify `gui/src/composables/useMklinkApi.ts`: optional RTT source path and RTT write methods.
- Modify `gui/src/types/mklink.ts`: desktop path and RTT API response types.
- Modify `mklink/remote/api.py`: optional RTT source path and binary-safe RTT write endpoint.
- Modify `mklink/remote/dashboards.py`: manager-owned active device/start metadata and DownBuffer write lifecycle.
- Modify `_maintainer/testing/tests/test_remote_api.py`: RTT source-path API contracts.
- Modify `_maintainer/testing/tests/test_rtt_superwatch_streaming.py`: manager write lifecycle and exact-byte tests.
- Modify `_maintainer/testing/tests/test_online_flash_probes.py`: integrated RTT write endpoint/resource lifecycle tests.
- Create `gui/src/lib/rttTransmit.ts`: string/hex encoding, line endings, and validation.
- Create `gui/src/lib/rttTransmit.test.ts`: exact payload tests.
- Create `gui/src/components/dash/RttTransmitBar.vue`: compact reference-style transmit UI.
- Create `gui/src/components/dash/RttTransmitBar.test.ts`: interaction, history, errors, and gating tests.
- Modify `gui/src/components/dash/RttViewTab.vue`: address controls, auto-search, exact-address start, and transmit integration.
- Modify `gui/src/components/dash/RttViewTab.test.ts`: address and transmit integration coverage.
- Modify `gui/package.json` and `gui/package-lock.json`: add `@tauri-apps/plugin-dialog`.
- Modify `gui/src-tauri/Cargo.toml` and `gui/src-tauri/Cargo.lock`: add `tauri-plugin-dialog`.
- Modify `gui/src-tauri/src/lib.rs`: register the dialog plugin.
- Modify `gui/src-tauri/capabilities/default.json`: permit native file-open dialogs.
- Modify `docs/ai/project-memory.json` and regenerate `docs/ai/CURRENT_HANDOFF.md`: factual completion evidence.

### Task 1: Desktop Settings and File Picker Adapters

**Files:**
- Create: `gui/src/lib/desktopSettings.ts`
- Create: `gui/src/lib/desktopSettings.test.ts`
- Create: `gui/src/lib/filePicker.ts`
- Create: `gui/src/lib/filePicker.test.ts`
- Modify: `gui/src/types/mklink.ts`

- [ ] **Step 1: Write failing storage tests**

Cover defaults, malformed JSON recovery, save/load, valid RTT address retention, and a 20-entry successful-send history that collapses consecutive duplicates.

```ts
expect(loadDesktopSettings(storage)).toEqual({
  version: 1,
  symbolPath: '',
  mapPath: '',
  rttAddress: '',
  transmitMode: 'text',
  lineEnding: '',
  sendHistory: [],
})

recordSuccessfulSend(storage, { text: 'status?', mode: 'text', lineEnding: '\r\n' })
recordSuccessfulSend(storage, { text: 'status?', mode: 'text', lineEnding: '\r\n' })
expect(loadDesktopSettings(storage).sendHistory).toHaveLength(1)
```

- [ ] **Step 2: Run the storage tests and verify RED**

Run: `npm test -- --run src/lib/desktopSettings.test.ts`

Expected: FAIL because `desktopSettings.ts` does not exist.

- [ ] **Step 3: Implement the versioned settings adapter**

Define exact shared types and a narrow storage interface:

```ts
export type RttTransmitMode = 'text' | 'hex'
export type RttLineEnding = '' | '\r' | '\n' | '\r\n'

export interface RttSendHistoryEntry {
  text: string
  mode: RttTransmitMode
  lineEnding: RttLineEnding
  timestamp: number
}

export interface DesktopSettings {
  version: 1
  symbolPath: string
  mapPath: string
  rttAddress: string
  transmitMode: RttTransmitMode
  lineEnding: RttLineEnding
  sendHistory: RttSendHistoryEntry[]
}
```

Use one key, `mklink.desktop.settings.v1`, defensive parsing, immutable returned objects, and a 20-entry history limit.

- [ ] **Step 4: Write failing file-picker tests**

Test AXF/ELF filters, MAP filters, cancellation returning `null`, and browser mode returning `null` instead of throwing.

```ts
expect(dialogOpen).toHaveBeenCalledWith(expect.objectContaining({
  multiple: false,
  filters: [{ name: 'AXF / ELF', extensions: ['axf', 'elf'] }],
}))
```

- [ ] **Step 5: Run picker tests and verify RED**

Run: `npm test -- --run src/lib/filePicker.test.ts`

Expected: FAIL because the adapter does not exist.

- [ ] **Step 6: Implement the browser-safe Tauri dialog adapter**

Use a dynamic import so browser/Edge development remains usable:

```ts
export async function pickSymbolFile(): Promise<string | null> {
  try {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const result = await open({ multiple: false, filters: [SYMBOL_FILTER] })
    return typeof result === 'string' ? result : null
  } catch {
    return null
  }
}
```

Provide a separate `pickMapFile()` with only the `map` extension.

- [ ] **Step 7: Run adapter tests and verify GREEN**

Run: `npm test -- --run src/lib/desktopSettings.test.ts src/lib/filePicker.test.ts`

Expected: all tests PASS.

- [ ] **Step 8: Commit the adapters**

```powershell
git add gui/src/lib/desktopSettings.ts gui/src/lib/desktopSettings.test.ts gui/src/lib/filePicker.ts gui/src/lib/filePicker.test.ts gui/src/types/mklink.ts
git commit -m "feat: add desktop path settings"
```

### Task 2: Merge the Configuration and Connection Workspace

**Files:**
- Create: `gui/src/views/ConfigView.test.ts`
- Create: `gui/src/components/config/ConfigSectionNav.vue`
- Create: `gui/src/components/config/FileSourcesPanel.vue`
- Modify: `gui/src/views/ConfigView.vue`

- [ ] **Step 1: Write failing configuration-page tests**

Mock `useMklinkApi`, `useMklinkWs`, the file picker, and desktop settings. Assert:

```ts
expect(wrapper.text()).not.toContain('项目概览')
expect(wrapper.text()).not.toContain('最近项目')
expect(wrapper.text()).not.toContain('MCU 类型')
expect(wrapper.text()).not.toContain('高级配置 (RTT)')
expect(wrapper.findAll('[data-testid="config-section"]')).toHaveLength(4)
```

Also verify Local Device is the default section, connection omits `mcu`, saved AXF/ELF is passed as `axf`, File Sources restores paths, Browse updates the correct field, and Remote/Service controls remain reachable.

- [ ] **Step 2: Run the view test and verify RED**

Run: `npm test -- --run src/views/ConfigView.test.ts`

Expected: FAIL because the old tabs and project sections still exist.

- [ ] **Step 3: Build the section navigation and file-source panel**

`ConfigSectionNav` emits one of:

```ts
type ConfigSection = 'local' | 'files' | 'remote' | 'serve'
```

`FileSourcesPanel` receives paths, connected/symbol status, and busy state; emits path updates, browse requests, save, and parse. Use inputs plus icon buttons with tooltips.

- [ ] **Step 4: Rewrite ConfigView around one workspace**

Remove imports and calls for project root, project history, project info, configuration status, MCU profiles, MICROKEEN overview, and RTT configuration. Preserve firmware upgrade warnings.

Connect with:

```ts
await connectDevice({
  port: localPort.value || config.value.com_port || undefined,
  axf: settings.value.symbolPath || undefined,
})
```

Do not include `mcu`. Keep port/SWD save behavior and all remote/service functionality.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run: `npm test -- --run src/views/ConfigView.test.ts src/lib/desktopSettings.test.ts src/lib/filePicker.test.ts`

Expected: all tests PASS.

- [ ] **Step 6: Commit the configuration workspace**

```powershell
git add gui/src/views/ConfigView.vue gui/src/views/ConfigView.test.ts gui/src/components/config/ConfigSectionNav.vue gui/src/components/config/FileSourcesPanel.vue
git commit -m "feat: merge desktop configuration workspace"
```

### Task 3: Accept Explicit RTT Address Sources

**Files:**
- Modify: `mklink/remote/api.py`
- Modify: `_maintainer/testing/tests/test_remote_api.py`
- Modify: `gui/src/composables/useMklinkApi.ts`
- Modify: `gui/src/types/mklink.ts`

- [ ] **Step 1: Write failing backend tests**

Test `POST /api/rtt-find` with `source_path` for AXF/ELF and MAP, missing files, parser failure details, and the existing empty-body fallback.

```python
response = client.post("/api/rtt-find", json={"source_path": str(source)})
assert response.status_code == 200
assert response.json()["addr"] == "0x20001A40"
assert response.json()["source_path"] == str(source)
```

- [ ] **Step 2: Run the API tests and verify RED**

Run: `python -m pytest _maintainer/testing/tests/test_remote_api.py -k rtt_find -q`

Expected: FAIL because `source_path` is ignored.

- [ ] **Step 3: Implement the additive source-path contract**

Change the route to accept:

```python
async def rtt_find(source_path: str | None = Body(default=None)):
```

When supplied, call `diagnose_rtt_addr(source_path)` directly. When omitted, retain the current project-derived MAP search unchanged. Return `source_path`, `addr`, `source`, `details`, and `warnings`; only persist to project `rtt_config` for the legacy no-argument path.

- [ ] **Step 4: Add the typed frontend call**

```ts
async function findRtt(sourcePath?: string): Promise<RttFindResponse> {
  return api('/api/rtt-find', {
    method: 'POST',
    body: JSON.stringify(sourcePath ? { source_path: sourcePath } : {}),
  })
}
```

- [ ] **Step 5: Run focused backend tests and verify GREEN**

Run: `python -m pytest _maintainer/testing/tests/test_remote_api.py -k rtt_find -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit RTT source detection**

```powershell
git add mklink/remote/api.py _maintainer/testing/tests/test_remote_api.py gui/src/composables/useMklinkApi.ts gui/src/types/mklink.ts
git commit -m "feat: detect RTT address from selected source"
```

### Task 4: Add Manager-Owned Binary RTT Writes

**Files:**
- Modify: `mklink/remote/dashboards.py`
- Modify: `mklink/remote/api.py`
- Modify: `_maintainer/testing/tests/test_rtt_superwatch_streaming.py`
- Modify: `_maintainer/testing/tests/test_online_flash_probes.py`

- [ ] **Step 1: Write failing manager lifecycle tests**

Use a fake device whose `rtt_start()` returns active `down_buffers` and whose `rtt_write()` records bytes. Assert exact byte preservation, status metadata, rejection before start/after stop, and stale-generation cleanup.

```python
manager.start(device, addr="0x20001A40", mode=1, search_size=0)
assert started.wait(timeout=1)
assert manager.write(b"\x00\xff\r\n") == 4
assert device.writes == [b"\x00\xff\r\n"]
```

- [ ] **Step 2: Run manager tests and verify RED**

Run: `python -m pytest _maintainer/testing/tests/test_rtt_superwatch_streaming.py -k 'rtt_manager_write or down_buffer' -q`

Expected: FAIL because the manager has no write operation or retained metadata.

- [ ] **Step 3: Implement manager-owned write state**

Add `_device`, `_start_info`, and `_write_lock`. Store the `device.rtt_start()` result only for the active generation. Expose `down_buffers` in `get_status()`. Implement:

```python
def write(self, data: bytes) -> int:
    if not self.running or self._device is None:
        raise RuntimeError("RTT is not running")
    if not any(item.get("active") for item in self._start_info.get("down_buffers", [])):
        raise RuntimeError("RTT DownBuffer is unavailable")
    with self._write_lock:
        if not self._device.rtt_write(data):
            raise RuntimeError("RTT write failed")
    return len(data)
```

Clear retained state in every stop/failure/finally path.

- [ ] **Step 4: Write failing REST endpoint tests**

Cover exact `00ff0d0a`, malformed/odd hex, empty data, payload over 64 KiB, stopped RTT, and missing DownBuffer.

- [ ] **Step 5: Run endpoint tests and verify RED**

Run: `python -m pytest _maintainer/testing/tests/test_online_flash_probes.py -k rtt_write -q`

Expected: FAIL because `/api/dash/rtt/write` does not exist.

- [ ] **Step 6: Implement the endpoint**

Add `POST /api/dash/rtt/write` accepting embedded `data_hex`. Validate with `bytes.fromhex()`, enforce `1..65536` bytes, call `managers['rtt'].write(data)`, and return `{"sent_bytes": len(data)}`. Map validation to 422 and runtime-state errors to 409.

- [ ] **Step 7: Run manager and endpoint tests and verify GREEN**

Run: `python -m pytest _maintainer/testing/tests/test_rtt_superwatch_streaming.py _maintainer/testing/tests/test_online_flash_probes.py -k 'rtt and (write or down_buffer)' -q`

Expected: all selected tests PASS.

- [ ] **Step 8: Commit binary RTT writes**

```powershell
git add mklink/remote/dashboards.py mklink/remote/api.py _maintainer/testing/tests/test_rtt_superwatch_streaming.py _maintainer/testing/tests/test_online_flash_probes.py
git commit -m "feat: add RTT DownBuffer writes"
```

### Task 5: Encode RTT Transmit Payloads

**Files:**
- Create: `gui/src/lib/rttTransmit.ts`
- Create: `gui/src/lib/rttTransmit.test.ts`
- Modify: `gui/src/composables/useMklinkApi.ts`

- [ ] **Step 1: Write failing exact-byte tests**

```ts
expect(encodeRttTransmit('温度?', 'text', '\r\n')).toEqual(
  Uint8Array.from([...new TextEncoder().encode('温度?'), 0x0d, 0x0a]),
)
expect(encodeRttTransmit('AA 55 01', 'hex', '\n')).toEqual(
  Uint8Array.of(0xaa, 0x55, 0x01, 0x0a),
)
expect(() => encodeRttTransmit('A', 'hex', '')).toThrow('偶数')
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm test -- --run src/lib/rttTransmit.test.ts`

Expected: FAIL because the encoder does not exist.

- [ ] **Step 3: Implement the encoder and hex serializer**

Strip ASCII whitespace only in hex mode, validate `/^[0-9a-f]*$/i`, require an even digit count, append literal ending bytes, and return `Uint8Array`. Add `toHexPayload(bytes)` using two lowercase hex digits per byte.

- [ ] **Step 4: Add the frontend write call**

```ts
async function writeRtt(data: Uint8Array): Promise<{ sent_bytes: number }> {
  return api('/api/dash/rtt/write', {
    method: 'POST',
    body: JSON.stringify({ data_hex: toHexPayload(data) }),
  })
}
```

- [ ] **Step 5: Run tests and verify GREEN**

Run: `npm test -- --run src/lib/rttTransmit.test.ts`

Expected: all tests PASS.

- [ ] **Step 6: Commit transmit encoding**

```powershell
git add gui/src/lib/rttTransmit.ts gui/src/lib/rttTransmit.test.ts gui/src/composables/useMklinkApi.ts
git commit -m "feat: encode RTT transmit payloads"
```

### Task 6: Build the Compact RTT Transmit Bar

**Files:**
- Create: `gui/src/components/dash/RttTransmitBar.vue`
- Create: `gui/src/components/dash/RttTransmitBar.test.ts`

- [ ] **Step 1: Write failing component tests**

Cover `Abc`/`Hex` toggle, reference-order controls, literal ending choices, click and Enter send, IME composition guard, disabled state, clear, successful history, failed-send retention, and history restore without sending.

Use stable selectors:

```ts
expect(wrapper.get('[data-testid="rtt-format"]').text()).toBe('Abc')
await wrapper.get('[data-testid="rtt-format"]').trigger('click')
expect(wrapper.get('[data-testid="rtt-format"]').text()).toBe('Hex')
```

- [ ] **Step 2: Run the component test and verify RED**

Run: `npm test -- --run src/components/dash/RttTransmitBar.test.ts`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the reference-style single row**

Use Lucide icons for direction, erase, history, and chevrons. Props:

```ts
defineProps<{
  enabled: boolean
  settings: DesktopSettings
  send: (payload: Uint8Array) => Promise<void>
}>()
```

Emit `settings-change` after mode/ending/history changes. The input is single-line. `keydown.enter` sends only when `!event.isComposing`. History restores text, mode, and ending without sending.

- [ ] **Step 4: Run component tests and verify GREEN**

Run: `npm test -- --run src/components/dash/RttTransmitBar.test.ts src/lib/rttTransmit.test.ts src/lib/desktopSettings.test.ts`

Expected: all tests PASS.

- [ ] **Step 5: Commit the transmit bar**

```powershell
git add gui/src/components/dash/RttTransmitBar.vue gui/src/components/dash/RttTransmitBar.test.ts
git commit -m "feat: add compact RTT transmit bar"
```

### Task 7: Integrate RTT Address and Transmission Controls

**Files:**
- Modify: `gui/src/components/dash/RttViewTab.vue`
- Modify: `gui/src/components/dash/RttViewTab.test.ts`

- [ ] **Step 1: Add failing address-integration tests**

Test source priority, successful fill, failure preserving the previous value, stale-search isolation, manual edit validation, and start parameters.

```ts
expect(mocks.dash.start).toHaveBeenCalledWith({
  addr: '0x20001A40',
  mode: 1,
  search_size: 0,
})
```

- [ ] **Step 2: Add failing transmit-integration tests**

Mock status with active/inactive DownBuffers. Assert the transmit bar is enabled only for running RTT plus an active DownBuffer and that successful sends call `writeRtt` with exact bytes.

- [ ] **Step 3: Run RttViewTab tests and verify RED**

Run: `npm test -- --run src/components/dash/RttViewTab.test.ts`

Expected: FAIL because address and transmit controls are absent.

- [ ] **Step 4: Implement address search and exact-address start**

Load desktop settings on mount. Auto Search chooses `symbolPath || mapPath || undefined`, calls `findRtt`, and updates `rttAddress` only if its generation is current and the component remains mounted. Start rejects invalid addresses, then calls `dash.start({ addr, mode: 1, search_size: 0 })` before opening binary transport.

- [ ] **Step 5: Integrate status metadata and transmit bar**

Poll and retain `down_buffers`. Render `RttTransmitBar` after the waveform/log display. Its send callback calls `writeRtt`, records successful history, clears the input through the component contract, and surfaces failures inline without stopping acquisition.

- [ ] **Step 6: Run focused RTT GUI tests and verify GREEN**

Run: `npm test -- --run src/components/dash/RttViewTab.test.ts src/components/dash/RttTransmitBar.test.ts src/lib/rttTransmit.test.ts`

Expected: all tests PASS.

- [ ] **Step 7: Commit RTT View integration**

```powershell
git add gui/src/components/dash/RttViewTab.vue gui/src/components/dash/RttViewTab.test.ts
git commit -m "feat: add RTT address and transmit controls"
```

### Task 8: Wire the Tauri Dialog Plugin

**Files:**
- Modify: `gui/package.json`
- Modify: `gui/package-lock.json`
- Modify: `gui/src-tauri/Cargo.toml`
- Modify: `gui/src-tauri/Cargo.lock`
- Modify: `gui/src-tauri/src/lib.rs`
- Modify: `gui/src-tauri/capabilities/default.json`

- [ ] **Step 1: Add the JavaScript dependency**

Run from `gui`:

```powershell
npm install @tauri-apps/plugin-dialog@^2
```

Expected: package files update without audit changes outside dependency resolution.

- [ ] **Step 2: Add the Rust dependency and plugin registration**

Add `tauri-plugin-dialog = "2"`, register `.plugin(tauri_plugin_dialog::init())`, and add `dialog:allow-open` to the main-window capability.

- [ ] **Step 3: Verify Rust and frontend compilation**

Run:

```powershell
npm run build
cargo test --manifest-path src-tauri/Cargo.toml
cargo check --manifest-path src-tauri/Cargo.toml
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit the desktop dialog wiring**

```powershell
git add gui/package.json gui/package-lock.json gui/src-tauri/Cargo.toml gui/src-tauri/Cargo.lock gui/src-tauri/src/lib.rs gui/src-tauri/capabilities/default.json
git commit -m "feat: add desktop file dialogs"
```

### Task 9: Full Regression, Installed HIL, Standard NSIS, and Handoff

**Files:**
- Modify: `docs/ai/project-memory.json`
- Regenerate: `docs/ai/CURRENT_HANDOFF.md`
- External only: `E:\software\HPM5300\Mklink-AI-Probe\release\<build-time>\...`

- [ ] **Step 1: Run full automated regression sequentially**

Run Python and GUI separately to avoid the known host-memory interaction:

```powershell
python -m pytest -q
cd gui
npm test -- --run
npm run build
cargo test --manifest-path src-tauri/Cargo.toml
cargo check --manifest-path src-tauri/Cargo.toml
```

Expected: Python baseline at or above 660 tests, GUI baseline at or above 280 tests, Vite build succeeds, Rust tests and check succeed.

- [ ] **Step 2: Run real Edge/Playwright UI validation**

Use the production frontend against the installed bundled sidecar. Verify all four configuration sections, no removed project/MCU/RTT content, native/manual path behavior, RTT address detection, reference-order send controls, history, clear, and responsive desktop layout. Do not retain screenshots.

- [ ] **Step 3: Run physical RTT HIL**

With the existing physical V4 target fixture:

- Detect RTT from AXF/ELF and confirm the address field is filled.
- Clear AXF/ELF, detect through MAP fallback, and compare the address.
- Override the address manually and start/stop successfully.
- Send UTF-8 text and exact HEX bytes with `无`, `\r`, `\n`, and `\r\n`.
- Confirm target-observed bytes match exactly.
- Confirm Enter and button sends, history restore, clear behavior, invalid HEX retention, DownBuffer gating, normal stop, zero clients, process exit, and port release.

- [ ] **Step 4: Build only the standard NSIS package**

Use the active Tauri builder workflow to rebuild the bundled sidecar and standard NSIS installer. Do not build MSI or WebView2-offline packages. Copy the installer and SHA-256 file to a build-time folder under the external release directory with the source commit in the filename.

- [ ] **Step 5: Install and smoke-test the standard NSIS candidate**

Perform silent overwrite install, restricted-PATH health, physical probe discovery, configuration-page workflow, RTT bidirectional workflow, normal shutdown, and process/port cleanup. Do not commit installers, logs, screenshots, Pack files, probe IDs, COM ports, usernames, credentials, or local hardware paths.

- [ ] **Step 6: Update durable AI memory**

Record factual commits, test counts, Edge/HIL results, installer filename/checksum without local paths, remaining limitations, and next actions. Remove completed plan references.

Run:

```powershell
python scripts/ai_memory.py render
python scripts/ai_memory.py validate
git diff --check
```

- [ ] **Step 7: Commit and push the final handoff**

```powershell
git add docs/ai/project-memory.json docs/ai/CURRENT_HANDOFF.md
git commit -m "docs: record configuration and RTT HIL"
git push origin feature/online-flash-streaming
git status --short --branch
git rev-list --left-right --count HEAD...origin/feature/online-flash-streaming
```

Expected: clean worktree and `0 0` local/remote divergence.
