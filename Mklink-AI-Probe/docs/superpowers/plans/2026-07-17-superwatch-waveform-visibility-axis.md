# SuperWatch Waveform Visibility And Shared Axis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not dispatch subagents for this plan.

**Goal:** Remove the redundant right-side SuperWatch Watch panel, move per-curve visibility to the left variable directory, and render readable shared numeric Y-axis ticks.

**Architecture:** `SuperWatchTab` owns a session-scoped set of hidden selected names. `SymbolVariablePanel` emits acquisition and visibility intent separately, while `WaveformViewer` forwards the hidden-name snapshot into the existing canvas runtime. The runtime keeps hidden channels sampled but excludes them from shared-range calculation, drawing, cursors, trigger proximity, and the minimap.

**Tech Stack:** Vue 3, TypeScript, Vitest, Vue Test Utils, HTML5 Canvas, existing `rtt_viewer.js` runtime, Vite.

---

### Task 1: Put Waveform Visibility In The Variable Directory

**Files:**
- Modify: `gui/src/components/dash/SuperWatchTab.vue`
- Modify: `gui/src/components/dash/SuperWatchTab.test.ts`
- Modify: `gui/src/components/dash/SymbolVariablePanel.vue`
- Modify: `gui/src/components/dash/SymbolVariablePanel.test.ts`
- Modify: `gui/package.json`
- Modify: `gui/package-lock.json`

- [ ] **Step 1: Write failing component tests**

Add a `SuperWatchTab` assertion that a hidden-name `Set` is passed to both children, that `visibility-change` updates the set, and that `selection-removed` clears the name. Add `SymbolVariablePanel` tests that only selected rows show an icon-only visibility button, clicking it emits `visibility-change` without calling the add/remove API, and a successful deselection emits `selection-removed`.

```ts
expect(wrapper.get('[data-testid="visibility-gain"]').attributes('aria-pressed')).toBe('true')
await wrapper.get('[data-testid="visibility-gain"]').trigger('click')
expect(wrapper.emitted('visibility-change')).toEqual([['gain', false]])
expect(fetchMock).toHaveBeenCalledTimes(1)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
cd gui
npm test -- src/components/dash/SuperWatchTab.test.ts src/components/dash/SymbolVariablePanel.test.ts
```

Expected: FAIL because the visibility props, events, and eye buttons do not exist.

- [ ] **Step 3: Add the icon dependency and implement parent-owned state**

Install `@lucide/vue`, then add this state flow to `SuperWatchTab.vue`:

```ts
const hiddenChannels = shallowRef(new Set<string>())

function setChannelVisibility(path: string, visible: boolean): void {
  const next = new Set(hiddenChannels.value)
  if (visible) next.delete(path)
  else next.add(path)
  hiddenChannels.value = next
}

function clearChannelVisibility(path: string): void {
  if (!hiddenChannels.value.has(path)) return
  const next = new Set(hiddenChannels.value)
  next.delete(path)
  hiddenChannels.value = next
}
```

Pass `hiddenChannels` to both children. Handle `visibility-change` and `selection-removed` from the variable panel.

- [ ] **Step 4: Add the eye control without changing acquisition semantics**

In `SymbolVariablePanel.vue`, add `hiddenChannels: ReadonlySet<string>` and these emits:

```ts
const emit = defineEmits<{
  'visibility-change': [path: string, visible: boolean]
  'selection-removed': [path: string]
}>()
```

Render an icon-only `Eye`/`EyeOff` button only when `selected.has(symbol.path)`. Use `aria-pressed`, a Chinese tooltip, and `data-testid="visibility-${symbol.path}"`. On successful API removal and on a reparse summary removal, emit `selection-removed`; do not call the backend when the eye is clicked.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: both files pass with no Vue warnings.

- [ ] **Step 6: Commit the directory visibility flow**

```powershell
git add gui/package.json gui/package-lock.json gui/src/components/dash/SuperWatchTab.vue gui/src/components/dash/SuperWatchTab.test.ts gui/src/components/dash/SymbolVariablePanel.vue gui/src/components/dash/SymbolVariablePanel.test.ts
git commit -m "feat: move SuperWatch visibility into variable directory"
```

### Task 2: Remove The Desktop Watch Panel And Apply Hidden Channels

**Files:**
- Modify: `gui/src/components/dash/WaveformViewer.vue`
- Modify: `gui/src/components/dash/WaveformViewer.test.ts`
- Modify: `gui/src/assets/rtt_viewer.css`
- Modify: `gui/src/assets/rtt_viewer.js`

- [ ] **Step 1: Write failing runtime tests**

Add tests proving:

```ts
expect(document.getElementById('watch-panel')).not.toBeNull()
expect(getComputedStyle(document.getElementById('watch-panel')!).display).toBe('none')
runtime.viewer.setHiddenChannels(['B'])
expect(runtime.probe.fields().A.visible).toBe(true)
expect(runtime.probe.fields().B.visible).toBe(false)
expect(runtime.probe.fields().B.ringBuf.count).toBeGreaterThan(0)
```

Also verify that reconfiguring the same hidden channel keeps it hidden and that clearing the list restores it.

- [ ] **Step 2: Run the focused viewer tests and verify RED**

```powershell
cd gui
npm test -- src/components/dash/WaveformViewer.test.ts
```

Expected: FAIL because `hiddenChannels`, `setHiddenChannels`, and desktop panel suppression do not exist.

- [ ] **Step 3: Forward the Vue prop into the runtime**

Add `hiddenChannels: ReadonlySet<string>` to `WaveformViewer.vue`. Watch a stable sorted array snapshot and call:

```ts
function applyHiddenChannels(): void {
  const names = [...props.hiddenChannels].sort()
  ;(window as any).__waveformViewers?.[props.mode]?.setHiddenChannels?.(names)
}
```

Call it after script readiness, after metadata/channel configuration, and whenever the prop Set is replaced.

- [ ] **Step 4: Keep hidden state in the canvas runtime**

In `rtt_viewer.js`, maintain `hiddenChannelNames` independently from `FIELDS`:

```js
var hiddenChannelNames = {};

function setHiddenChannels(names) {
  hiddenChannelNames = {};
  for (var i = 0; i < names.length; i++) hiddenChannelNames[String(names[i])] = true;
  for (var name in FIELDS) FIELDS[name].visible = !hiddenChannelNames[name];
  updateWatchTable();
  drawChart();
  drawMinimap();
}
```

After `applyChannelMetadata` in `configureBinaryChannels`, reapply the map. Export `setHiddenChannels` on `window.__waveformViewers[CONFIG.mode]`. Do not remove hidden channels or stop pushing their binary samples.

- [ ] **Step 5: Suppress the redundant desktop panel and expand Canvas**

Add a SuperWatch desktop class to the injected root and CSS rules that hide `#watch-panel` and `#watch-resizer`, remove the chart's split border treatment, and retain the existing outer margins. Keep the hidden DOM for legacy shared-runtime compatibility; only the Vue desktop SuperWatch workspace suppresses it.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: viewer tests pass, including existing watch-table legacy tests.

- [ ] **Step 7: Commit the runtime visibility bridge**

```powershell
git add gui/src/components/dash/WaveformViewer.vue gui/src/components/dash/WaveformViewer.test.ts gui/src/assets/rtt_viewer.css gui/src/assets/rtt_viewer.js
git commit -m "feat: expand SuperWatch waveform workspace"
```

### Task 3: Render A Shared Numeric Y Axis

**Files:**
- Modify: `gui/src/assets/rtt_viewer.js`
- Modify: `gui/src/assets/rtt_viewer.css`
- Modify: `gui/src/components/dash/WaveformViewer.test.ts`

- [ ] **Step 1: Write failing shared-axis tests**

Instrument Canvas `fillText` calls in the existing test harness and add assertions that six shared numeric labels are drawn from the visible-channel range, hidden outliers no longer affect those labels, and Y-axis wheel/pan/reset update `globalYView` rather than independent channel scales.

```ts
expect(runtime.probe.globalYView().zoom).toBeGreaterThan(1)
expect((window as any).__canvasLabels).toEqual(expect.arrayContaining(['0', '20', '40']))
runtime.viewer.setHiddenChannels(['outlier'])
runtime.viewer.renderBinaryFrame()
expect((window as any).__canvasLabels.some((label: string) => label.includes('1000'))).toBe(false)
```

- [ ] **Step 2: Run the shared-axis tests and verify RED**

Run the focused viewer command from Task 2. Expected: FAIL because drawing still normalizes each channel separately and the grid has no Y tick labels.

- [ ] **Step 3: Centralize shared range calculation**

Add a helper that scans only visible channels with data, adds 10% padding, and applies `globalYView.zoom` and `globalYView.offset`. Use it for drawing, trigger positioning, axis panning, and tick labels. Curve drawing must call the global transform for every visible channel.

- [ ] **Step 4: Draw readable numeric ticks**

Reserve a stable left margin of approximately 64 px. For the same six horizontal grid positions, draw right-aligned labels. Use fixed decimals for ordinary ranges and compact exponential notation when `abs(value) >= 1e6`, `0 < abs(value) < 1e-4`, or the visible span requires it. Increase the Y hit region to cover the label gutter without overlapping the variable directory.

- [ ] **Step 5: Move Y interactions to the shared view**

Wheel changes `globalYView.zoom`; drag changes `globalYView.offset` using the current shared span; double-click restores `{ zoom: 1, offset: 0 }`. Preserve X-axis behavior and the existing trigger/cursor interactions.

- [ ] **Step 6: Run focused and full frontend verification**

```powershell
cd gui
npm test -- src/components/dash/SuperWatchTab.test.ts src/components/dash/SymbolVariablePanel.test.ts src/components/dash/WaveformViewer.test.ts
npm test
npm run build
```

Expected: all Vitest files pass and Vite production build exits 0.

- [ ] **Step 7: Commit the shared axis**

```powershell
git add gui/src/assets/rtt_viewer.js gui/src/assets/rtt_viewer.css gui/src/components/dash/WaveformViewer.test.ts
git commit -m "feat: add shared SuperWatch Y axis"
```

### Task 4: Visual, Installed-App, And Repository Closure

**Files:**
- Modify: `docs/ai/project-memory.json`
- Regenerate: `docs/ai/CURRENT_HANDOFF.md`

- [ ] **Step 1: Start the local GUI and inspect with real Edge/Playwright**

Verify at desktop and narrow widths: no right Watch panel, larger Canvas, eye buttons do not shift rows, hidden curves disappear while values continue updating, and Y labels fit without overlap.

- [ ] **Step 2: Run installed-app hardware regression when the probe fixture is available**

Use only the App firmware region. Select at least two real variables, hide one, confirm the hidden variable value continues changing, restore it, exercise shared Y zoom/pan/reset, pause/resume/stop, and confirm resource release. Do not perform whole-chip erase and do not commit screenshots, logs, IDs, COM names, firmware, AXF, HEX, or BIN artifacts.

- [ ] **Step 3: Run final repository verification**

```powershell
python scripts/ai_memory.py validate
git diff --check
git status --short --branch
```

Run any additional Rust/Python tests only if implementation changes cross those boundaries.

- [ ] **Step 4: Update durable memory and regenerate handoff**

Record factual test/build/visual/HIL results, known limits, new commits, and clean-tree target. Run:

```powershell
python scripts/ai_memory.py render
python scripts/ai_memory.py validate
```

- [ ] **Step 5: Commit memory, push, and confirm synchronization**

```powershell
git add docs/ai/project-memory.json docs/ai/CURRENT_HANDOFF.md
git commit -m "docs: update SuperWatch waveform handoff"
git push origin feature/online-flash-streaming
git status --short --branch
git rev-list --left-right --count HEAD...origin/feature/online-flash-streaming
```

Expected: clean worktree and `0 0` synchronization.
