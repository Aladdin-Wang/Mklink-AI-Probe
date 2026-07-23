# SuperWatch Stable Y Viewport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the SuperWatch chart rectangle stable and provide pointer-anchored Y zoom plus left-drag viewport panning while large selected channels remain acquired outside the viewport.

**Architecture:** Remove the auto-height statistics footer from the embedded waveform template. Replace the SuperWatch relative `zoom/offset` interaction with an absolute manual `yMin/yMax` viewport captured from the current auto range on first interaction; preserve legacy saved `zoom/offset` values for project compatibility. Reuse the existing Canvas and axis event layers so cursor and trigger dragging retain priority.

**Tech Stack:** Vue 3, TypeScript, plain browser JavaScript Canvas renderer, CSS Grid/Flexbox, Vitest, happy-dom, Playwright/WebView2.

---

### Task 1: Remove the Dynamic Statistics Footer

**Files:**
- Modify: `gui/src/components/dash/WaveformViewer.vue`
- Modify: `gui/src/assets/rtt_viewer.js`
- Modify: `gui/src/assets/rtt_viewer.css`
- Test: `gui/src/components/dash/WaveformViewer.test.ts`

- [ ] **Step 1: Write the failing footer-removal test**

Add a source-contract test next to the existing SuperWatch layout tests:

```ts
it('removes the dynamic statistics footer from the waveform layout', () => {
  expect(componentSource).not.toContain('id="stats-footer"')
  expect(viewerSource).not.toContain("document.getElementById('stats-footer')")
  expect(viewerCss).not.toMatch(/\nfooter\s*\{/)
})
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
cd gui
npx vitest run src/components/dash/WaveformViewer.test.ts -t "removes the dynamic statistics footer"
```

Expected: FAIL because the template, update loop, and CSS still contain the footer.

- [ ] **Step 3: Remove the footer without changing variable-directory values**

Delete this template node from `buildTemplate()`:

```html
<footer id="stats-footer"></footer>
```

Delete the `footer` lookup and `cur/min/max/avg` HTML generation from `updateUI()`. Keep the points badge, selector chips, and variable-directory current-value path unchanged.

Delete the waveform-specific CSS block:

```css
footer { ... }
.stat { ... }
.stat .label { ... }
.stat .value { ... }
```

- [ ] **Step 4: Run the focused file and verify GREEN**

Run:

```powershell
cd gui
npx vitest run src/components/dash/WaveformViewer.test.ts
```

Expected: all WaveformViewer tests pass.

- [ ] **Step 5: Commit the stable layout change**

```powershell
git add -- gui/src/components/dash/WaveformViewer.vue gui/src/assets/rtt_viewer.js gui/src/assets/rtt_viewer.css gui/src/components/dash/WaveformViewer.test.ts
git commit -m "fix: stabilize SuperWatch chart layout"
```

### Task 2: Add an Absolute Manual Y Viewport

**Files:**
- Modify: `gui/src/assets/rtt_viewer.js`
- Test: `gui/src/components/dash/WaveformViewer.test.ts`

- [ ] **Step 1: Write failing pointer-anchor and outlier-stability tests**

Expose `getSharedYRange()` through the existing `window.__rttTestProbe`:

```js
sharedYRange: function() { return getSharedYRange(); },
```

Add a SuperWatch test that configures `small` and `uwTick`, records the current range, wheels at 25% of the plot height, and verifies the value below the pointer remains fixed:

```ts
const before = runtime.probe.sharedYRange()
const ratio = 0.25
const anchorBefore = before.yMax - ratio * (before.yMax - before.yMin)
document.getElementById('chart')!.dispatchEvent(new WheelEvent('wheel', {
  deltaY: -100, clientX: 400, clientY: 98, bubbles: true,
}))
const after = runtime.probe.sharedYRange()
const anchorAfter = after.yMax - ratio * (after.yMax - after.yMin)
expect(anchorAfter).toBeCloseTo(anchorBefore, 6)
expect(after.yMax - after.yMin).toBeLessThan(before.yMax - before.yMin)
```

Append a later batch whose `uwTick` is much larger and assert the manual range is unchanged:

```ts
const locked = runtime.probe.sharedYRange()
runtime.viewer.acceptBinaryBatch({
  sequence: 2n, timestampNs: 4_000_000n, itemCount: 2, channelCount: 2,
  layout: 'sample-major-float32',
  values: Float32Array.of(2, 900_000, 3, 1_000_000).buffer,
  times: Float64Array.of(3, 4).buffer,
})
runtime.viewer.renderBinaryFrame()
expect(runtime.probe.sharedYRange()).toEqual(locked)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
cd gui
npx vitest run src/components/dash/WaveformViewer.test.ts -t "anchors|outlier"
```

Expected: FAIL because the current range is recomputed from rolling extrema and zooms around the shared center.

- [ ] **Step 3: Implement Auto and Manual shared Y states**

Extend the state while retaining legacy fields for saved projects:

```js
var globalYView = {
  zoom: 1,
  offset: 0,
  autoRange: true,
  manualMin: null,
  manualMax: null
};
```

Split the range calculation:

```js
function getAutoSharedYRange() {
  // Existing visible-channel extrema and 10% padding calculation.
}

function hasManualSharedYRange() {
  return globalYView.autoRange === false &&
    Number.isFinite(globalYView.manualMin) &&
    Number.isFinite(globalYView.manualMax) &&
    globalYView.manualMax > globalYView.manualMin;
}

function getSharedYRange() {
  if (hasManualSharedYRange()) {
    return { yMin: globalYView.manualMin, yMax: globalYView.manualMax };
  }
  var range = getAutoSharedYRange();
  if (!range) return null;
  if (globalYView.zoom === 1 && globalYView.offset === 0) return range;
  var span = range.yMax - range.yMin;
  var center = (range.yMin + range.yMax) / 2 + globalYView.offset;
  return {
    yMin: center - span / globalYView.zoom / 2,
    yMax: center + span / globalYView.zoom / 2
  };
}

function setManualSharedYRange(yMin, yMax) {
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax) || yMax <= yMin) return false;
  globalYView.autoRange = false;
  globalYView.manualMin = yMin;
  globalYView.manualMax = yMax;
  globalYView.zoom = 1;
  globalYView.offset = 0;
  return true;
}
```

Implement pointer-anchored zoom:

```js
function zoomSharedYAt(deltaY, anchorRatio) {
  var current = getSharedYRange();
  if (!current) return;
  var ratio = Math.max(0, Math.min(1, anchorRatio));
  var span = current.yMax - current.yMin;
  var nextSpan = span * (deltaY > 0 ? 1.25 : 0.8);
  var anchor = current.yMax - ratio * span;
  setManualSharedYRange(
    anchor - (1 - ratio) * nextSpan,
    anchor + ratio * nextSpan
  );
  drawChart();
}
```

Use the Y-axis hit-region ratio and Canvas plot ratio when calling this helper. Update `resetVisibleY()` to set Auto and clear manual bounds. Save/load `autoRange`, `manualMin`, and `manualMax`, while accepting old projects that only contain `zoom` and `offset`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
cd gui
npx vitest run src/components/dash/WaveformViewer.test.ts
```

Expected: pointer anchoring, outlier stability, shared ticks, hide/show, and existing axis tests pass.

- [ ] **Step 5: Commit the manual Y viewport**

```powershell
git add -- gui/src/assets/rtt_viewer.js gui/src/components/dash/WaveformViewer.test.ts
git commit -m "feat: add stable SuperWatch Y viewport"
```

### Task 3: Pan the Plot with the Left Mouse Button

**Files:**
- Modify: `gui/src/assets/rtt_viewer.js`
- Test: `gui/src/components/dash/WaveformViewer.test.ts`

- [ ] **Step 1: Write failing vertical and two-axis drag tests**

After entering Manual mode with one wheel event, dispatch a plain left drag inside the plot:

```ts
const before = runtime.probe.sharedYRange()
const canvas = document.getElementById('chart')!
canvas.dispatchEvent(new MouseEvent('mousedown', {
  button: 0, clientX: 400, clientY: 160, bubbles: true,
}))
window.dispatchEvent(new MouseEvent('mousemove', {
  clientX: 400, clientY: 220, bubbles: true,
}))
window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
const after = runtime.probe.sharedYRange()
expect(after.yMax - after.yMin).toBeCloseTo(before.yMax - before.yMin, 6)
expect(after.yMin).not.toBeCloseTo(before.yMin, 6)
```

Zoom X with Shift+wheel, repeat a diagonal drag, and assert both `timeline().offset` and the shared Y range change. Add a cursor/trigger precedence assertion showing their existing drag paths do not create a viewport drag.

- [ ] **Step 2: Run the drag tests and verify RED**

Run:

```powershell
cd gui
npx vitest run src/components/dash/WaveformViewer.test.ts -t "left drag|two-axis"
```

Expected: FAIL because plain Canvas left drag currently pans only an already-zoomed X timeline.

- [ ] **Step 3: Implement one plot viewport drag state**

After cursor and trigger hit testing, start a plot drag for plain left clicks inside the plot:

```js
axisDrag = {
  mode: 'plot-shared',
  startX: e.clientX,
  startY: e.clientY,
  startTimelineOffset: timelineView.offset,
  panTimeline: timelineView.zoom > 1,
  yMin: sharedRange.yMin,
  yMax: sharedRange.yMax
};
```

Handle it in the existing global mousemove listener:

```js
} else if (axisDrag.mode === 'plot-shared') {
  var plotHeight = Math.max(1, rect.height - 40);
  var span = axisDrag.yMax - axisDrag.yMin;
  var shift = (e.clientY - axisDrag.startY) / plotHeight * span;
  setManualSharedYRange(axisDrag.yMin + shift, axisDrag.yMax + shift);
  if (axisDrag.panTimeline) {
    var dx = (e.clientX - axisDrag.startX) / Math.max(1, rect.width - 80);
    timelineView.offset = clampAxisOffset(axisDrag.startTimelineOffset - dx);
    drawMinimap();
  }
  drawChart();
```

Keep middle-button, Alt+left, and Space+left as horizontal hand tools. Ensure Canvas hover/click logic ignores movement while `plot-shared` drag is active. Double-click must call `resetVisibleY()` and restore Auto.

- [ ] **Step 4: Run the WaveformViewer tests and verify GREEN**

Run:

```powershell
cd gui
npx vitest run src/components/dash/WaveformViewer.test.ts
```

Expected: all tests pass, including X axis, shared Y axis, cursor, trigger, and disposal coverage.

- [ ] **Step 5: Commit plot panning**

```powershell
git add -- gui/src/assets/rtt_viewer.js gui/src/components/dash/WaveformViewer.test.ts
git commit -m "feat: pan SuperWatch plot viewport"
```

### Task 4: Full Regression and Real Browser Qualification

**Files:**
- Modify: `docs/ai/project-memory.json`
- Generate: `docs/ai/CURRENT_HANDOFF.md`

- [ ] **Step 1: Run the complete GUI suite**

```powershell
cd gui
npm test
npm run build
```

Expected: all GUI tests pass and Vite completes without TypeScript errors.

- [ ] **Step 2: Run proportional backend and desktop checks**

```powershell
python -m pytest -q
cd gui/src-tauri
cargo test
cargo check
```

Expected: all Python and Rust tests pass. The only tolerated Rust message is the existing MSVC linker import-library warning.

- [ ] **Step 3: Verify chart geometry and interactions in real Edge/WebView2**

Use the existing physical SuperWatch fixture with one large monotonic integer and two smaller changing values. Through Playwright/CDP:

1. Record `#chart-wrap.getBoundingClientRect()` over at least five seconds while values gain digits.
2. Require identical width, height, top, and left values across samples.
3. Wheel over a small-signal Y position and require the same value-to-pixel anchor before and after zoom.
4. Drag vertically and require an unchanged span with a shifted absolute range.
5. Continue acquisition until the large channel grows and require the Manual range to remain unchanged.
6. Double-click and require Auto range to include the large channel again.
7. Confirm smooth visible Canvas rendering, pause/resume, stop, and resource cleanup.

- [ ] **Step 4: Build and qualify only the standard NSIS installer**

```powershell
python skills/tauri-gui-builder/scripts/build.py --check
python skills/tauri-gui-builder/scripts/build.py --bundle
```

Require only `bundle/nsis/` output. Copy it to the external release directory under a build-time folder with the source commit in the filename, compute SHA-256, install silently, verify the footer commit, bundled-sidecar restricted-PATH launch, zero Python processes, and normal-close process/port release. Do not generate MSI or WebView2-offline packages.

- [ ] **Step 5: Update AI memory, commit, and push**

Record only factual, privacy-safe results. Then run:

```powershell
python scripts/ai_memory.py render
python scripts/ai_memory.py validate
git diff --check
git add -- docs/ai/project-memory.json docs/ai/CURRENT_HANDOFF.md
git commit -m "docs: hand off stable SuperWatch viewport"
git push origin feature/online-flash-streaming
git status --short --branch
```

Expected: memory validates, remote and local HEAD match, and the worktree is clean.
