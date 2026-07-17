# SuperWatch Shared Symbol Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the duplicated desktop VOFA+ workflow with one AXF-aware SuperWatch workspace that shares a filtered symbol catalog, samples typed variables through `cmd.dump_memory`, writes typed RAM values through a stopped-stream `cmd.flush_memory` transaction, and survives AXF rebuilds by rebinding selections by name.

**Architecture:** Add a focused backend `SymbolCatalog` that converts the Device DWARF model into versioned runtime-safe descriptors. Expose catalog, reparse, selection, and typed-write operations through the existing FastAPI service; let `SuperWatchStreamManager` own serialized stop/write/readback/restart transitions. Add a singleton Vue catalog store consumed by an immediate-loading Symbols tab and a two-column SuperWatch workspace; retain the shared waveform engine while removing the GUI VOFA+ route and internal SuperWatch search controls.

**Tech Stack:** Python 3.14, FastAPI, existing DWARF parser and `DumpMemoryStreamSession`, Vue 3 Composition API, TypeScript, Vitest, Tauri v2, Computer Use, Keil MDK.

---

## File Structure

- Create `mklink/symbol_catalog.py`: normalized symbol descriptors, AXF fingerprint/generation, filtering, type encoding/decoding, name-based rebind.
- Modify `mklink/device.py`: own the active catalog and publish it atomically after AXF parsing.
- Modify `mklink/remote/api.py`: catalog list/status/reparse and SuperWatch typed-write routes.
- Modify `mklink/remote/dashboards.py`: serialized SuperWatch reparse and write transactions with dump-session restoration.
- Create `_maintainer/testing/tests/test_symbol_catalog.py`: catalog filtering and type conversion tests.
- Modify `_maintainer/testing/tests/test_remote_api.py`: catalog and typed-write API contracts.
- Modify `_maintainer/testing/tests/test_rtt_superwatch_streaming.py`: transaction ordering and acquisition restoration.
- Create `gui/src/composables/useSymbolCatalog.ts`: singleton dashboard catalog state and API calls.
- Create `gui/src/composables/useSymbolCatalog.test.ts`: store loading, stale detection, reparse, and error tests.
- Modify `gui/src/types/mklink.ts`: catalog, descriptor, rebind, and write result types; remove VOFA from desktop dashboard types.
- Rewrite `gui/src/components/dash/SymbolsTab.vue`: immediate virtualized catalog list and details.
- Create `gui/src/components/dash/SymbolVariablePanel.vue`: searchable tree, selection, current values, inline type-specific editor.
- Create `gui/src/components/dash/SymbolVariablePanel.test.ts`: directory, selection, and write UI behavior.
- Modify `gui/src/components/dash/SuperWatchTab.vue`: approved resizable two-column layout.
- Modify `gui/src/components/dash/WaveformViewer.vue`: remove embedded SuperWatch symbol controls and reserve full height for the plot.
- Modify `gui/src/assets/rtt_viewer.js`: external selection refresh and axis-specific wheel/pan/reset behavior.
- Modify `gui/src/assets/rtt_viewer.css`: stable X/Y axis hit regions and full-height chart layout.
- Modify `gui/src/components/dash/WaveformViewer.test.ts`: axis interaction and removed internal selector coverage.
- Modify `gui/src/views/DashboardView.vue`: remove VOFA+ tab and component.
- Modify `gui/src/views/DashboardView.test.ts`: reject/degrade legacy `tab=vofa` and verify clean navigation.
- Delete `gui/src/components/dash/VofaTab.vue`: desktop-only duplicate entry.

### Task 1: Build The Runtime-Safe Symbol Catalog

**Files:**
- Create: `mklink/symbol_catalog.py`
- Create: `_maintainer/testing/tests/test_symbol_catalog.py`

- [ ] **Step 1: Write failing catalog filtering tests**

```python
def test_catalog_keeps_ram_scalars_and_expands_struct_members(fake_dwarf):
    catalog = SymbolCatalog.from_dwarf(fake_dwarf, axf_path="app.axf", ram_ranges=[(0x20000000, 0x20010000)])
    assert [item.path for item in catalog.items] == ["gain", "controller.target"]
    assert catalog.by_path("gain").writable is True
    assert catalog.by_path("controller.target").address == 0x20000024


def test_catalog_rejects_locals_flash_constants_arrays_and_pointers(fake_dwarf):
    catalog = SymbolCatalog.from_dwarf(fake_dwarf, axf_path="app.axf", ram_ranges=[(0x20000000, 0x20010000)])
    assert catalog.by_path("local_temp") is None
    assert catalog.by_path("flash_table") is None
    assert catalog.by_path("buffer") is None
    assert catalog.by_path("next") is None
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest _maintainer/testing/tests/test_symbol_catalog.py -q`

Expected: FAIL because `mklink.symbol_catalog` does not exist.

- [ ] **Step 3: Implement immutable descriptors and catalog construction**

```python
@dataclass(frozen=True)
class SymbolDescriptor:
    path: str
    address: int
    type_name: str
    scalar_kind: str
    size: int
    writable: bool
    enum_values: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SymbolCatalog:
    generation: int
    axf_path: str
    fingerprint: AxfFingerprint
    items: tuple[SymbolDescriptor, ...]

    @cached_property
    def index(self) -> dict[str, SymbolDescriptor]:
        return {item.path: item for item in self.items}

    def by_path(self, path: str) -> SymbolDescriptor | None:
        return self.index.get(path)
```

Normalize typedef aliases, recursively expand supported structure members, require a nonzero address inside configured RAM ranges, and return descriptors sorted case-insensitively by path.

- [ ] **Step 4: Add type encode/decode validation tests**

```python
@pytest.mark.parametrize(
    ("type_name", "value", "expected"),
    [("int16_t", -2, b"\xfe\xff"), ("uint32_t", 0x12345678, b"\x78\x56\x34\x12"), ("float", 1.5, struct.pack("<f", 1.5)), ("bool", True, b"\x01")],
)
def test_encode_scalar_is_little_endian(type_name, value, expected):
    assert encode_scalar(type_name, value) == expected
```

Also cover integer overflow, NaN/Inf, invalid enums, unsupported types, and exact readback comparison.

- [ ] **Step 5: Implement scalar codecs and rebind summaries**

```python
def rebind_paths(old: SymbolCatalog, new: SymbolCatalog, paths: Sequence[str]) -> RebindSummary:
    preserved, updated, removed = [], [], []
    for path in paths:
        before, after = old.by_path(path), new.by_path(path)
        if after is None:
            removed.append(path)
        elif before and (before.address, before.type_name, before.size) != (after.address, after.type_name, after.size):
            updated.append(path)
        else:
            preserved.append(path)
    return RebindSummary(tuple(preserved), tuple(updated), tuple(removed))
```

- [ ] **Step 6: Run catalog tests and commit**

Run: `python -m pytest _maintainer/testing/tests/test_symbol_catalog.py -q`

Expected: all tests PASS.

Run:

```powershell
git add mklink/symbol_catalog.py _maintainer/testing/tests/test_symbol_catalog.py
git commit -m "feat: add runtime-safe symbol catalog"
```

### Task 2: Attach Catalog Lifecycle To Device And FastAPI

**Files:**
- Modify: `mklink/device.py`
- Modify: `mklink/remote/api.py`
- Modify: `_maintainer/testing/tests/test_remote_api.py`

- [ ] **Step 1: Write failing API contract tests**

```python
def test_symbol_catalog_lists_immediately_with_generation(client, connected_device):
    response = client.get("/api/symbols/catalog?limit=100")
    assert response.status_code == 200
    assert response.json()["generation"] == 1
    assert response.json()["items"][0]["path"] == "gain"


def test_symbol_status_marks_changed_axf_stale(client, touch_axf):
    assert client.get("/api/symbols/status").json()["stale"] is True
```

- [ ] **Step 2: Run API tests and verify RED**

Run: `python -m pytest _maintainer/testing/tests/test_remote_api.py -k "symbol_catalog or symbol_status" -q`

Expected: 404 responses for the new routes.

- [ ] **Step 3: Publish catalog atomically after AXF parsing**

```python
def _load_dwarf_info(self) -> None:
    info = load_dwarf_info(self._axf)
    next_generation = (self._symbol_catalog.generation if self._symbol_catalog else 0) + 1
    catalog = SymbolCatalog.from_dwarf(
        info,
        axf_path=self._axf,
        generation=next_generation,
        ram_ranges=self._target_ram_ranges(),
    )
    self._dwarf_info = info
    self._symbol_catalog = catalog
```

Do not replace `_dwarf_info` or `_symbol_catalog` when parsing fails.

Expose `reparse_axf_atomically()` on Device. It parses into local `info` and `catalog` variables, compares the fingerprint again, then publishes both objects under the Device symbol lock only after every step succeeds.

- [ ] **Step 4: Add bounded catalog and status routes**

```python
@app.get("/api/symbols/catalog")
async def symbols_catalog(q: str = "", selected: bool = False, writable: bool = False, offset: int = 0, limit: int = 200):
    catalog = _require_symbol_catalog()
    return catalog.to_page(q=q, writable=writable, offset=offset, limit=min(limit, 500))
```

`/api/symbols/status` returns generation, counts, parsed timestamp, fingerprint, and stale state without exposing unrelated paths.

- [ ] **Step 5: Add explicit reparse rollback test and implementation**

```python
def test_reparse_keeps_previous_catalog_when_new_axf_is_invalid(client, device):
    old_generation = device.symbol_catalog.generation
    device.parse_loader.side_effect = RuntimeError("bad DWARF")
    response = client.post("/api/symbols/reparse")
    assert response.status_code == 422
    assert device.symbol_catalog.generation == old_generation
```

- [ ] **Step 6: Run focused backend tests and commit**

Run: `python -m pytest _maintainer/testing/tests/test_symbol_catalog.py _maintainer/testing/tests/test_remote_api.py -k "symbol" -q`

Run:

```powershell
git add mklink/device.py mklink/remote/api.py _maintainer/testing/tests/test_remote_api.py
git commit -m "feat: expose shared symbol catalog API"
```

### Task 3: Add Serialized SuperWatch Reparse And Typed Write Transactions

**Files:**
- Modify: `mklink/remote/dashboards.py`
- Modify: `mklink/remote/api.py`
- Modify: `_maintainer/testing/tests/test_rtt_superwatch_streaming.py`
- Modify: `_maintainer/testing/tests/test_remote_api.py`

- [ ] **Step 1: Write transaction ordering tests**

```python
def test_write_stops_dump_flushes_reads_back_and_restores_running(manager, bridge):
    manager.start(device_with_gain)
    result = manager.write_symbol("gain", generation=1, value=1.5)
    assert bridge.operations == ["dump:start", "dump:stop", "flush", "dump:oneshot", "dump:start"]
    assert result["verified"] is True
    assert manager.get_status()["state"] == "running"


def test_write_failure_still_restores_paused_state(manager, bridge):
    manager.pause()
    bridge.flush_error = RuntimeError("flush failed")
    with pytest.raises(RuntimeError):
        manager.write_symbol("gain", generation=1, value=2.0)
    assert manager.get_status()["state"] == "paused"
```

- [ ] **Step 2: Run transaction tests and verify RED**

Run: `python -m pytest _maintainer/testing/tests/test_rtt_superwatch_streaming.py -k "write_symbol or reparse" -q`

Expected: FAIL because transaction methods do not exist.

- [ ] **Step 3: Add one operation lock and dump-session restart barrier**

```python
self._operation_lock = threading.RLock()
self._dump_idle = threading.Event()
self._dump_idle.set()

def _request_dump_restart_and_wait(self, timeout: float = 5.0) -> None:
    self._dump_restart.set()
    if not self._dump_idle.wait(timeout):
        raise TimeoutError("SuperWatch dump stream did not stop")
```

Set `_dump_idle.clear()` immediately before `DumpMemoryStreamSession.start()` and set it in the session `finally` block.

- [ ] **Step 4: Implement typed write with guaranteed restoration**

```python
def write_symbol(self, path: str, *, generation: int, value: object) -> dict:
    with self._operation_lock:
        restore = self._capture_acquisition_state()
        try:
            self._stop_dump_for_transaction()
            descriptor = self._device.symbol_catalog.require(path, generation)
            payload = encode_scalar_descriptor(descriptor, value)
            self._flush_memory(descriptor.address, payload)
            raw = self._dump_once(descriptor.address, descriptor.size)
            actual = decode_scalar_descriptor(descriptor, raw)
            verify_scalar_value(descriptor, value, actual)
            return {"path": path, "old_value": restore.last_values.get(path), "value": actual, "verified": True}
        finally:
            self._restore_acquisition_state(restore)
```

- [ ] **Step 5: Implement reparse and name-based runtime rebuild**

```python
def reparse_symbols(self) -> dict:
    with self._operation_lock:
        restore = self._capture_acquisition_state()
        old_catalog = self._device.symbol_catalog
        paths = tuple(item.name for item in self._runtime.items)
        try:
            self._stop_dump_for_transaction()
            new_catalog = self._device.reparse_axf_atomically()
            summary = rebind_paths(old_catalog, new_catalog, paths)
            self._replace_runtime_items([p for p in paths if p not in summary.removed])
            return summary.to_dict()
        finally:
            self._restore_acquisition_state(restore)
```

- [ ] **Step 6: Add routes and phase-specific error responses**

Add `POST /api/dash/superwatch/write` and route reparse through the manager when it owns an active or prepared runtime. Return structured `code`, `phase`, and `message` fields.

- [ ] **Step 7: Run focused tests and commit**

Run: `python -m pytest _maintainer/testing/tests/test_rtt_superwatch_streaming.py _maintainer/testing/tests/test_remote_api.py -k "superwatch or symbol" -q`

Run:

```powershell
git add mklink/remote/dashboards.py mklink/remote/api.py _maintainer/testing/tests/test_rtt_superwatch_streaming.py _maintainer/testing/tests/test_remote_api.py
git commit -m "feat: add typed SuperWatch write transactions"
```

### Task 4: Add The Shared Vue Symbol Store

**Files:**
- Create: `gui/src/composables/useSymbolCatalog.ts`
- Create: `gui/src/composables/useSymbolCatalog.test.ts`
- Modify: `gui/src/types/mklink.ts`

- [ ] **Step 1: Write failing singleton-store tests**

```typescript
it('loads the catalog once and shares it across consumers', async () => {
  const first = useSymbolCatalog()
  const second = useSymbolCatalog()
  await Promise.all([first.ensureLoaded(), second.ensureLoaded()])
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(second.items.value[0].path).toBe('gain')
})

it('keeps the previous catalog when reparse fails', async () => {
  await symbols.ensureLoaded()
  fetchMock.mockResolvedValueOnce(errorResponse('bad DWARF'))
  await expect(symbols.reparse()).rejects.toThrow('bad DWARF')
  expect(symbols.generation.value).toBe(1)
})
```

- [ ] **Step 2: Run store tests and verify RED**

Run: `npm test -- --run src/composables/useSymbolCatalog.test.ts`

- [ ] **Step 3: Define exact frontend types**

```typescript
export interface SymbolDescriptor {
  path: string
  address: number
  type_name: string
  scalar_kind: 'signed' | 'unsigned' | 'float' | 'bool' | 'enum'
  size: number
  writable: boolean
  enum_values: Record<string, number>
  parent_path?: string | null
}
```

- [ ] **Step 4: Implement module-level refs and deduplicated loading**

```typescript
const items = shallowRef<SymbolDescriptor[]>([])
const generation = ref(0)
let loadingPromise: Promise<void> | null = null

async function ensureLoaded(force = false): Promise<void> {
  if (!force && generation.value > 0) return
  if (loadingPromise) return loadingPromise
  loadingPromise = loadCatalog().finally(() => { loadingPromise = null })
  return loadingPromise
}
```

- [ ] **Step 5: Run store tests and commit**

Run: `npm test -- --run src/composables/useSymbolCatalog.test.ts`

Run:

```powershell
git add gui/src/composables/useSymbolCatalog.ts gui/src/composables/useSymbolCatalog.test.ts gui/src/types/mklink.ts
git commit -m "feat: share symbol catalog in dashboard"
```

### Task 5: Make The Symbols Tab Load Immediately

**Files:**
- Modify: `gui/src/components/dash/SymbolsTab.vue`
- Create: `gui/src/components/dash/SymbolsTab.test.ts`

- [ ] **Step 1: Write immediate-loading and filtering tests**

```typescript
it('shows valid catalog variables immediately when opened', async () => {
  const wrapper = mount(SymbolsTab, { props: { deviceConnected: true } })
  await flushPromises()
  expect(wrapper.text()).toContain('gain')
  expect(wrapper.text()).toContain('controller.target')
})
```

- [ ] **Step 2: Run the test and verify RED**

Run: `npm test -- --run src/components/dash/SymbolsTab.test.ts`

- [ ] **Step 3: Replace query-triggered API calls with shared catalog state**

Use `ensureLoaded()` on mount, computed client-side filters, a bounded rendered window, and the existing type detail request only when a row is selected.

- [ ] **Step 4: Run focused tests and commit**

Run: `npm test -- --run src/components/dash/SymbolsTab.test.ts src/composables/useSymbolCatalog.test.ts`

Run:

```powershell
git add gui/src/components/dash/SymbolsTab.vue gui/src/components/dash/SymbolsTab.test.ts
git commit -m "feat: load symbols immediately in dashboard"
```

### Task 6: Build The Approved SuperWatch Variable Directory

**Files:**
- Create: `gui/src/components/dash/SymbolVariablePanel.vue`
- Create: `gui/src/components/dash/SymbolVariablePanel.test.ts`
- Modify: `gui/src/components/dash/SuperWatchTab.vue`
- Modify: `gui/src/components/dash/WaveformViewer.vue`
- Modify: `gui/src/assets/rtt_viewer.js`
- Modify: `gui/src/assets/rtt_viewer.css`

- [ ] **Step 1: Write variable panel behavior tests**

Cover immediate items, structure grouping, selected/writable filters, add/remove API calls, inline numeric/bool/enum editors, stale-generation refusal, write progress, and reparse summary.

```typescript
it('writes a float from the variable row and refreshes the verified value', async () => {
  await wrapper.get('[data-testid="edit-gain"]').trigger('click')
  await wrapper.get('[data-testid="write-input-gain"]').setValue('1.3')
  await wrapper.get('[data-testid="write-gain"]').trigger('click')
  await flushPromises()
  expect(writeSymbol).toHaveBeenCalledWith('gain', 1, 1.3)
  expect(wrapper.text()).toContain('验证成功')
})
```

- [ ] **Step 2: Run panel tests and verify RED**

Run: `npm test -- --run src/components/dash/SymbolVariablePanel.test.ts`

- [ ] **Step 3: Implement the resizable/collapsible two-column shell**

```vue
<div class="superwatch-workspace" :class="{ collapsed }">
  <SymbolVariablePanel class="symbol-panel" />
  <button class="panel-collapse" @click="collapsed = !collapsed"><PanelLeftClose /></button>
  <WaveformViewer class="waveform-panel" mode="SuperWatch" :device-connected="deviceConnected" :embedded-symbol-controls="false" />
</div>
```

Use Lucide icons already available to the project, stable grid tracks, and a drag handle bounded between 280 and 520 pixels.

- [ ] **Step 4: Remove the embedded SuperWatch search/add panel**

Add an `embeddedSymbolControls` prop to `WaveformViewer`. Omit `#superwatch-panel` from the generated template when false, and make the legacy runtime listeners null-safe. Selection changes are performed by Vue through the existing add/remove endpoints.

- [ ] **Step 5: Run panel and waveform tests and commit**

Run: `npm test -- --run src/components/dash/SymbolVariablePanel.test.ts src/components/dash/WaveformViewer.test.ts`

Run:

```powershell
git add gui/src/components/dash/SymbolVariablePanel.vue gui/src/components/dash/SymbolVariablePanel.test.ts gui/src/components/dash/SuperWatchTab.vue gui/src/components/dash/WaveformViewer.vue gui/src/assets/rtt_viewer.js gui/src/assets/rtt_viewer.css
git commit -m "feat: add SuperWatch symbol workspace"
```

### Task 7: Add Axis-Specific Mouse Zoom, Pan, And Reset

**Files:**
- Modify: `gui/src/assets/rtt_viewer.js`
- Modify: `gui/src/assets/rtt_viewer.css`
- Modify: `gui/src/components/dash/WaveformViewer.test.ts`

- [ ] **Step 1: Write deterministic interaction tests**

```typescript
it('zooms only time when the wheel is over the x-axis', async () => {
  runtime.dispatchWheel({ x: 400, y: runtime.axis.xY, deltaY: -100 })
  expect(runtime.timelineView.zoom).toBeGreaterThan(1)
  expect(runtime.yView).toEqual({ min: null, max: null })
})

it('double-clicking the y-axis restores automatic amplitude range', async () => {
  runtime.setYView(-10, 10)
  runtime.dispatchDoubleClick({ x: runtime.axis.yX, y: 200 })
  expect(runtime.yView).toEqual({ min: null, max: null })
})
```

- [ ] **Step 2: Run interaction tests and verify RED**

Run: `npm test -- --run src/components/dash/WaveformViewer.test.ts -t "axis"`

- [ ] **Step 3: Implement stable axis hit regions**

Track `yView = { min, max }` separately from auto bounds. Wheel events over the bottom axis change `timelineView.zoom/offset`; wheel events over the left axis change `yView` around the cursor-derived value. Axis drags update only their matching view. Double-click resets only the matching axis.

- [ ] **Step 4: Run waveform tests and commit**

Run: `npm test -- --run src/components/dash/WaveformViewer.test.ts`

Run:

```powershell
git add gui/src/assets/rtt_viewer.js gui/src/assets/rtt_viewer.css gui/src/components/dash/WaveformViewer.test.ts
git commit -m "feat: add waveform axis mouse controls"
```

### Task 8: Remove The Desktop VOFA+ Entry

**Files:**
- Modify: `gui/src/views/DashboardView.vue`
- Modify: `gui/src/views/DashboardView.test.ts`
- Modify: `gui/src/types/mklink.ts`
- Delete: `gui/src/components/dash/VofaTab.vue`

- [ ] **Step 1: Write navigation tests**

```typescript
it('does not render a VOFA+ dashboard tab', () => {
  const wrapper = mountDashboard()
  expect(wrapper.text()).not.toContain('VOFA+')
})

it('falls back to RTT for a legacy tab=vofa route', () => {
  const wrapper = mountDashboard({ query: { tab: 'vofa' } })
  expect(wrapper.find('.rtt-route-probe').exists()).toBe(true)
})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm test -- --run src/views/DashboardView.test.ts`

- [ ] **Step 3: Remove imports, route membership, tab button, component, and desktop dashboard type**

Keep backend VOFA routes and CLI untouched.

- [ ] **Step 4: Run tests and commit**

Run: `npm test -- --run src/views/DashboardView.test.ts`

Run:

```powershell
git add gui/src/views/DashboardView.vue gui/src/views/DashboardView.test.ts gui/src/types/mklink.ts
git add -u gui/src/components/dash/VofaTab.vue
git commit -m "refactor: remove desktop VOFA dashboard"
```

### Task 9: Full Automated Regression And Production Build

**Files:**
- Modify only files required by failures directly caused by Tasks 1-8.

- [ ] **Step 1: Run focused Python regression**

Run: `python -m pytest _maintainer/testing/tests/test_symbol_catalog.py _maintainer/testing/tests/test_remote_api.py _maintainer/testing/tests/test_rtt_superwatch_streaming.py -q`

- [ ] **Step 2: Run full GUI regression**

Run: `npm test -- --run`

Expected: all GUI tests PASS, including existing 60-second waveform gates.

- [ ] **Step 3: Run production builds and Rust tests**

Run: `npm run build`

Run: `cargo test -q`

- [ ] **Step 4: Run full Python regression**

Run: `python -m pytest -q`

- [ ] **Step 5: Validate diffs and commit regression fixes**

Run: `git diff --check`

If a regression fails, return to the task that owns the behavior, add a focused failing test there, fix it, rerun that task's verification command, and commit using that task's exact file list. Do not create a catch-all regression commit.

### Task 10: Build Both Fixtures And Complete Hardware Closure

**Files:**
- External local Bootloader and App Keil projects only; do not stage their outputs.
- Update after verification: `docs/ai/project-memory.json`
- Regenerate: `docs/ai/CURRENT_HANDOFF.md`

- [ ] **Step 1: Record Bootloader and App Flash ranges before any write**

Parse both HEX files with a structured Intel HEX parser. Assert Bootloader and App ranges do not overlap and record privacy-safe range/hash fingerprints outside Git.

- [ ] **Step 2: Rebuild both Keil projects**

Use the installed Keil command-line builder. Require zero build errors. Parse both AXF files through Mklink and verify nonzero valid catalog counts.

- [ ] **Step 3: Add or adjust App-only test variables when needed**

Use clearly named volatile aligned scalar variables covering float, signed integer, boolean, and enum behavior. Rebuild the App. Never add generated AXF/HEX/BIN files to Git.

- [ ] **Step 4: Program only the App HEX when firmware changed**

Use the online flash workflow with file-embedded HEX addresses, covered-sector erase only, verify enabled, and no whole-chip erase. Read back the App region and independently confirm the Bootloader fingerprint is unchanged.

- [ ] **Step 5: Exercise installed SuperWatch with Computer Use**

Select real variables from the directory, start sampling, verify typed values and changing curves, pause/resume/stop, collapse/resize the directory, zoom/pan/reset X and Y axes, and verify resource release.

- [ ] **Step 6: Perform a reversible typed write**

Record the original App variable value, write a safe alternative, verify the UI reports dump stop/flush/readback/restart, observe the new value, restore the original value, and verify it again.

- [ ] **Step 7: Rebuild the App and test stale AXF recovery**

Rebuild without deleting selected names. Confirm `AXF updated`, invoke reparse, and verify selection preservation, updated metadata, and automatic acquisition restoration.

- [ ] **Step 8: Build and overwrite-install the unsigned NSIS package**

Ensure the sidecar includes pyOCD and `cmsis_pack_manager` runtime data. Install silently, cold-start the application, and repeat the ordinary-user symbol/SuperWatch flow.

- [ ] **Step 9: Clean all generated outputs from the repository worktree**

Remove dependencies, Tauri target, sidecar, installers, caches, logs, screenshots, and visual-companion session files. Restore tracked `gui/dist` and temporary Tauri config changes.

- [ ] **Step 10: Update memory, validate, commit, and push**

Run:

```powershell
python scripts/ai_memory.py render
python scripts/ai_memory.py validate
git diff --check
git status --short --branch
git rev-list --left-right --count HEAD...origin/feature/online-flash-streaming
```

Commit implementation and memory separately, push `feature/online-flash-streaming`, and require a clean worktree with remote divergence `0 0`.
