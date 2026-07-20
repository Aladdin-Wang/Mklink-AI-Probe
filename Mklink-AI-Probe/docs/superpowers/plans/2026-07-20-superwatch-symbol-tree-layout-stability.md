# SuperWatch Symbol Tree and Layout Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the SuperWatch waveform rectangle geometrically stable while live status text changes, and replace the thousands-row flat symbol catalog with a default-collapsed structure/array tree.

**Architecture:** Add a pure TypeScript tree model that converts the existing flat runtime-readable symbol catalog into stable branch and leaf nodes, then flatten only the currently visible rows for the Vue panel. Keep acquisition and symbol APIs unchanged. Stabilize the embedded waveform header and toolbars with SuperWatch-specific fixed-row CSS and bounded live badges.

**Tech Stack:** Vue 3, TypeScript 6, Vitest 4, happy-dom, existing Canvas waveform viewer, Tauri v2, Python FastAPI sidecar.

---

## File Map

- Create `gui/src/lib/symbolTree.ts`: pure symbol-path parsing, hierarchy construction, filtering, selection counts, and visible-row flattening.
- Create `gui/src/lib/symbolTree.test.ts`: unit tests for nested structures, arrays, search, selected-only filtering, and large collapsed catalogs.
- Modify `gui/src/components/dash/SymbolVariablePanel.vue`: expansion/search state and rendering of flattened branch/leaf rows.
- Modify `gui/src/components/dash/SymbolVariablePanel.test.ts`: component behavior and existing selection/write regressions.
- Modify `gui/src/components/dash/WaveformViewer.vue`: group title/live badges separately from command actions.
- Modify `gui/src/assets/rtt_viewer.css`: stable desktop SuperWatch header/toolbars and bounded live badges.
- Modify `gui/src/components/dash/WaveformViewer.test.ts`: layout-source guards and existing viewer regression coverage.
- Modify `docs/ai/project-memory.json`: factual completion, verification, package, and remaining limitations.
- Generate `docs/ai/CURRENT_HANDOFF.md`: rendered durable handoff.

### Task 1: Pure Symbol Tree Model

**Files:**
- Create: `gui/src/lib/symbolTree.ts`
- Create: `gui/src/lib/symbolTree.test.ts`

- [ ] **Step 1: Write failing hierarchy tests**

Create tests that define the desired public API:

```ts
import { describe, expect, it } from 'vitest'
import { buildSymbolTree, visibleSymbolRows } from './symbolTree'
import type { SymbolDescriptor } from '../types/mklink'

function symbol(path: string, parentPath: string | null = null): SymbolDescriptor {
  return {
    path,
    address: 0x20000000,
    type_name: 'float',
    scalar_kind: 'float',
    size: 4,
    writable: true,
    enum_values: {},
    parent_path: parentPath,
  }
}

describe('symbolTree', () => {
  it('builds nested structure and array branches while keeping scalars as leaves', () => {
    const roots = buildSymbolTree([
      symbol('gain'),
      symbol('controller.enabled', 'controller'),
      symbol('controller.channels[0].value', 'controller'),
      symbol('controller.channels[1].value', 'controller'),
    ])

    expect(roots.map(node => [node.key, node.kind])).toEqual([
      ['gain', 'leaf'],
      ['controller', 'branch'],
    ])
    const rows = visibleSymbolRows(roots, {
      expanded: new Set(['controller', 'controller.channels', 'controller.channels[0]']),
      selected: new Set<string>(),
      query: '',
      selectedOnly: false,
    })
    expect(rows.map(row => [row.node.key, row.depth])).toContainEqual([
      'controller.channels[0].value', 3,
    ])
  })

  it('keeps structured roots collapsed and does not expose their leaves by default', () => {
    const roots = buildSymbolTree([
      symbol('gain'),
      symbol('controller.target', 'controller'),
    ])
    const rows = visibleSymbolRows(roots, {
      expanded: new Set<string>(), selected: new Set<string>(), query: '', selectedOnly: false,
    })
    expect(rows.map(row => row.node.key)).toEqual(['gain', 'controller'])
  })
})
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```powershell
cd gui
npx vitest run src/lib/symbolTree.test.ts
```

Expected: FAIL because `src/lib/symbolTree.ts` does not exist.

- [ ] **Step 3: Implement path tokenization and tree construction**

Create these exact public types and functions:

```ts
import type { SymbolDescriptor } from '../types/mklink'

export interface SymbolTreeNode {
  key: string
  label: string
  kind: 'branch' | 'leaf'
  descriptor: SymbolDescriptor | null
  children: SymbolTreeNode[]
  leafCount: number
}

export interface VisibleSymbolRow {
  node: SymbolTreeNode
  depth: number
  expanded: boolean
  selectedLeafCount: number
}

export interface VisibleSymbolOptions {
  expanded: ReadonlySet<string>
  selected: ReadonlySet<string>
  query: string
  selectedOnly: boolean
}

export function buildSymbolTree(items: readonly SymbolDescriptor[]): SymbolTreeNode[]
export function visibleSymbolRows(
  roots: readonly SymbolTreeNode[], options: VisibleSymbolOptions,
): VisibleSymbolRow[]
export function collectBranchKeys(roots: readonly SymbolTreeNode[]): Set<string>
```

Tokenize `controller.channels[0].value` as `controller`, `channels`, `[0]`, `value`. Build canonical prefixes without a dot before array tokens. Treat the final token as the readable leaf and every preceding token as a branch. Preserve catalog order, compute `leafCount` bottom-up, and never mutate the input descriptors.

- [ ] **Step 4: Add failing filter tests**

Add tests for the complete filter contract:

```ts
it('auto-expands search matches and composes search with selected-only', () => {
  const roots = buildSymbolTree([
    symbol('controller.channels[0].value', 'controller'),
    symbol('controller.channels[1].status', 'controller'),
    symbol('gain'),
  ])
  const rows = visibleSymbolRows(roots, {
    expanded: new Set<string>(),
    selected: new Set(['controller.channels[0].value']),
    query: 'value',
    selectedOnly: true,
  })
  expect(rows.map(row => row.node.key)).toEqual([
    'controller',
    'controller.channels',
    'controller.channels[0]',
    'controller.channels[0].value',
  ])
  expect(rows.filter(row => row.node.kind === 'branch').every(row => row.expanded)).toBe(true)
})

it('keeps a 4660-leaf catalog bounded while roots are collapsed', () => {
  const items = Array.from({ length: 4660 }, (_, index) =>
    symbol(`root${Math.floor(index / 256)}.values[${index % 256}]`, `root${Math.floor(index / 256)}`),
  )
  const rows = visibleSymbolRows(buildSymbolTree(items), {
    expanded: new Set<string>(), selected: new Set<string>(), query: '', selectedOnly: false,
  })
  expect(rows.length).toBeLessThan(32)
  expect(rows.every(row => row.node.kind === 'branch')).toBe(true)
})
```

- [ ] **Step 5: Run the tests and implement minimal filtering**

Run the focused tests, confirm the new tests fail for missing filtering, then implement a recursive match/prune pass. A leaf survives when it matches both active filters. A branch survives when any descendant survives. Search or selected-only filtering forces surviving branches open; otherwise use `options.expanded`.

Run:

```powershell
cd gui
npx vitest run src/lib/symbolTree.test.ts
```

Expected: all symbol-tree tests PASS.

- [ ] **Step 6: Commit the pure model**

```powershell
git add -- gui/src/lib/symbolTree.ts gui/src/lib/symbolTree.test.ts
git commit -m "feat: build collapsed SuperWatch symbol tree"
```

### Task 2: Integrate the Collapsed Tree into the Variable Panel

**Files:**
- Modify: `gui/src/components/dash/SymbolVariablePanel.vue`
- Modify: `gui/src/components/dash/SymbolVariablePanel.test.ts`

- [ ] **Step 1: Replace the flat-list expectation with failing tree behavior tests**

Add component assertions using stable test ids:

```ts
it('collapses structured variables by default and expands them on demand', async () => {
  const wrapper = mount(SymbolVariablePanel, {
    props: { deviceConnected: true, latestValues: { gain: 1.25 } },
  })
  await flushPromises()

  expect(wrapper.find('[data-testid="leaf-controller.target"]').exists()).toBe(false)
  expect(wrapper.get('[data-testid="branch-controller"]').text()).toContain('0 / 2')

  await wrapper.get('[data-testid="expand-controller"]').trigger('click')
  expect(wrapper.get('[data-testid="leaf-controller.target"]').exists()).toBe(true)
})

it('expands search matches and restores the previous expansion state when cleared', async () => {
  const wrapper = mount(SymbolVariablePanel, {
    props: { deviceConnected: true, latestValues: {} },
  })
  await flushPromises()

  await wrapper.get('[data-testid="variable-search"]').setValue('target')
  expect(wrapper.get('[data-testid="leaf-controller.target"]').exists()).toBe(true)

  await wrapper.get('[data-testid="variable-search"]').setValue('')
  expect(wrapper.find('[data-testid="leaf-controller.target"]').exists()).toBe(false)
})

it('shows only selected leaves and their ancestors in selected-only mode', async () => {
  const wrapper = mount(SymbolVariablePanel, {
    props: { deviceConnected: true, latestValues: { gain: 1.25 } },
  })
  await flushPromises()

  await wrapper.get('[data-testid="selected-only"]').setValue(true)
  expect(wrapper.get('[data-testid="leaf-gain"]').exists()).toBe(true)
  expect(wrapper.find('[data-testid="branch-controller"]').exists()).toBe(false)
})
```

- [ ] **Step 2: Run the component test and confirm RED**

```powershell
cd gui
npx vitest run src/components/dash/SymbolVariablePanel.test.ts
```

Expected: FAIL because branches, tree test ids, and expansion behavior do not exist.

- [ ] **Step 3: Add tree state without changing API behavior**

Import the pure helpers and replace `groups` with stable tree state:

```ts
import { buildSymbolTree, collectBranchKeys, visibleSymbolRows } from '../../lib/symbolTree'

const expanded = shallowRef(new Set<string>())
let searchExpansionSnapshot: Set<string> | null = null
const tree = computed(() => buildSymbolTree(catalog.items.value))
const rows = computed(() => visibleSymbolRows(tree.value, {
  expanded: expanded.value,
  selected: selected.value,
  query: query.value,
  selectedOnly: selectedOnly.value,
}))

function toggleBranch(path: string): void {
  if (query.value.trim() || selectedOnly.value) return
  expanded.value = withSet(expanded.value, path, !expanded.value.has(path))
}

watch(query, (next, previous) => {
  if (next.trim() && !previous.trim()) searchExpansionSnapshot = new Set(expanded.value)
  if (!next.trim() && previous.trim() && searchExpansionSnapshot) {
    expanded.value = searchExpansionSnapshot
    searchExpansionSnapshot = null
  }
})
```

After reparse, intersect `expanded` with `collectBranchKeys(tree.value)`. Do not add `latestValues` to tree or row computations.

- [ ] **Step 4: Render branch rows and preserve the existing leaf controls**

Replace nested group/flat loops with one `rows` loop. Branch rows contain a Lucide `ChevronRight` or `ChevronDown`, label, and `selectedLeafCount / leafCount`. Leaf rows retain the existing checkbox, eye button, name, type, current value, edit button, write editor, and success message. Use indentation derived from `row.depth` and stable ids:

```vue
<div v-for="row in rows" :key="row.node.key">
  <button
    v-if="row.node.kind === 'branch'"
    class="branch-row"
    type="button"
    :data-testid="`expand-${row.node.key}`"
    :style="{ '--tree-depth': row.depth }"
    @click="toggleBranch(row.node.key)"
  >
    <ChevronDown v-if="row.expanded" :size="15" />
    <ChevronRight v-else :size="15" />
    <span>{{ row.node.label }}</span>
    <span>{{ row.selectedLeafCount }} / {{ row.node.leafCount }}</span>
  </button>
  <div
    v-else
    class="variable-row"
    :data-testid="`leaf-${row.node.key}`"
    :style="{ '--tree-depth': row.depth }"
  >
    <!-- retain the existing leaf controls using row.node.descriptor -->
  </div>
</div>
```

Give the selected-only checkbox `data-testid="selected-only"`. Use Lucide icons already present in the project; do not introduce manual SVG.

- [ ] **Step 5: Verify panel RED-to-GREEN and regressions**

```powershell
cd gui
npx vitest run src/components/dash/SymbolVariablePanel.test.ts src/lib/symbolTree.test.ts
```

Expected: all focused tests PASS, including add/remove, visibility, verified write, stale catalog, collapsed tree, search restore, and selected-only behavior.

- [ ] **Step 6: Commit the panel integration**

```powershell
git add -- gui/src/components/dash/SymbolVariablePanel.vue gui/src/components/dash/SymbolVariablePanel.test.ts
git commit -m "feat: fold structured SuperWatch variables"
```

### Task 3: Stabilize the SuperWatch Waveform Geometry

**Files:**
- Modify: `gui/src/components/dash/WaveformViewer.vue`
- Modify: `gui/src/assets/rtt_viewer.css`
- Modify: `gui/src/components/dash/WaveformViewer.test.ts`

- [ ] **Step 1: Add failing layout guards**

Add a source-level regression test next to the existing responsive/layout guards:

```ts
it('keeps desktop SuperWatch live status and controls in stable rows', () => {
  expect(componentSource).toContain('<div class="header-status">')
  expect(viewerCss).toContain('.waveform-viewer.superwatch-desktop header')
  expect(viewerCss).toContain('grid-template-columns: minmax(0, 1fr) auto')
  expect(viewerCss).toContain('.waveform-viewer.superwatch-desktop #control-toolbar')
  expect(viewerCss).toContain('.waveform-viewer.superwatch-desktop #trigger-toolbar')
  expect(viewerCss).toContain('flex-wrap: nowrap')
  expect(viewerCss).toContain('#transport-health-badge')
})
```

- [ ] **Step 2: Run the viewer test and confirm RED**

```powershell
cd gui
npx vitest run src/components/dash/WaveformViewer.test.ts
```

Expected: FAIL because the header status wrapper and stable SuperWatch rules do not exist.

- [ ] **Step 3: Group header status separately from actions**

Change only the generated header markup:

```html
<header>
  <div class="header-status">
    <h1>MKLink ${mode}</h1>
    <span id="mode-badge" class="badge badge-mode">${mode}</span>
    <span id="conn-status" class="badge badge-ok" data-i18n="live">live</span>
    <span id="pts-count" class="badge badge-info">0 pts</span>
    <span id="sample-rate-badge" class="badge badge-info">rate -- Hz</span>
    <span id="transport-state-badge" class="badge badge-info">transport stopped</span>
    <span id="transport-health-badge" class="badge badge-info">transport 0 / backend 0/0 / buffer 0</span>
  </div>
  <div class="header-actions">...</div>
</header>
```

Do not rename ids consumed by `rtt_viewer.js`.

- [ ] **Step 4: Add bounded desktop SuperWatch CSS**

Add SuperWatch-specific rules after the shared header and toolbar rules:

```css
.header-status {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.waveform-viewer.superwatch-desktop header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  min-height: 49px;
  max-height: 49px;
  overflow: hidden;
}
.waveform-viewer.superwatch-desktop .header-status {
  flex-wrap: nowrap;
  overflow: hidden;
  white-space: nowrap;
}
.waveform-viewer.superwatch-desktop .header-actions {
  flex-wrap: nowrap;
}
.waveform-viewer.superwatch-desktop #sample-rate-badge { width: 86px; }
.waveform-viewer.superwatch-desktop #transport-state-badge { width: 126px; }
.waveform-viewer.superwatch-desktop #transport-health-badge {
  width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.waveform-viewer.superwatch-desktop #control-toolbar,
.waveform-viewer.superwatch-desktop #trigger-toolbar {
  min-height: 39px;
  max-height: 39px;
  flex-wrap: nowrap;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}
.waveform-viewer.superwatch-desktop #control-toolbar::-webkit-scrollbar,
.waveform-viewer.superwatch-desktop #trigger-toolbar::-webkit-scrollbar {
  display: none;
}
```

Adjust exact bounded widths only if the real rendered Chinese/English labels require it. Keep command actions visible before allowing status text to consume more space.

- [ ] **Step 5: Run focused layout and viewer tests**

```powershell
cd gui
npx vitest run src/components/dash/WaveformViewer.test.ts src/components/dash/SuperWatchTab.test.ts
```

Expected: all focused tests PASS.

- [ ] **Step 6: Commit the layout fix**

```powershell
git add -- gui/src/components/dash/WaveformViewer.vue gui/src/assets/rtt_viewer.css gui/src/components/dash/WaveformViewer.test.ts
git commit -m "fix: stabilize SuperWatch waveform geometry"
```

### Task 4: Automated and Real-Target Qualification

**Files:**
- No committed test artifacts.

- [ ] **Step 1: Run the full GUI test and build baseline**

```powershell
cd gui
npm test
npm run build
```

Expected: all GUI tests PASS and Vue TypeScript plus Vite production build complete successfully.

- [ ] **Step 2: Run proportional backend and desktop checks**

```powershell
python -m pytest -q
cd gui/src-tauri
cargo test
cargo check
```

Expected: Python and Rust suites PASS. Do not treat unrelated pre-existing warnings as new failures; record exact warnings factually.

- [ ] **Step 3: Start the source application without altering the target project**

Use the supplied STM32F103 project only as a local runtime input. Do not copy its firmware, AXF, MAP, Pack, FLM, absolute path, probe id, or COM port into Git. Start the source FastAPI/Tauri application on unused ports, connect through the normal GUI, and load the existing AXF catalog.

- [ ] **Step 4: Measure waveform geometry for at least five seconds**

Using real Edge/WebView2 with Playwright/CDP when available, sample `#chart-wrap.getBoundingClientRect()` while sample rate, point count, buffer count, and health badges change. Require identical `top`, `left`, `width`, and `height` across samples. If browser automation is unavailable, use computer use for the interactive workflow and a supported WebView2 inspection surface for the numeric geometry check; report any unavailable surface explicitly.

- [ ] **Step 5: Exercise the tree and performance behavior on the real catalog**

Require all of the following:

1. Initial full-catalog view shows collapsed structured roots rather than thousands of mounted leaves.
2. Expanding nested structures and arrays reveals the expected readable leaves.
3. Search expands the matching path, and clearing search restores the prior collapsed state.
4. `仅已选` exposes the selected variables and their ancestors.
5. With `仅已选` disabled, waveform rendering remains visually smooth while the catalog contains thousands of leaves.
6. Existing selection, eye visibility, write verification, pause/resume, stop, and reconnect behavior remains correct.
7. Normal close leaves zero product/Python child processes and releases product ports.

- [ ] **Step 6: Run repository hygiene checks**

```powershell
git diff --check
git status --short --branch
```

Expected: only intentional source, test, plan, and later memory changes are present; no local artifacts or sensitive identifiers appear.

### Task 5: Standard NSIS, AI Memory, Commit, and Push

**Files:**
- Modify: `docs/ai/project-memory.json`
- Generate: `docs/ai/CURRENT_HANDOFF.md`
- Create outside Git: standard NSIS installer and SHA-256 under the main repository `release\<build-time>\` directory.

- [ ] **Step 1: Read the Tauri builder skill before packaging**

Read the active `mklink-flash:tauri-gui-builder` skill completely and use its current commands. Do not build MSI or a WebView2-offline package.

- [ ] **Step 2: Build only the standard NSIS**

Use the builder's standard checks and bundle command:

```powershell
python skills/tauri-gui-builder/scripts/build.py --check
python skills/tauri-gui-builder/scripts/build.py --bundle
```

Require only the standard NSIS candidate. Place it in `release\<yyyyMMdd-HHmmss>\` under the main repository, include the implementation commit in the filename, and generate SHA-256. Keep the installer and checksum outside Git.

- [ ] **Step 3: Install and smoke-test the standard candidate**

Verify restricted-PATH startup, bundled sidecar use, build identity, SuperWatch collapsed tree, stable geometry, normal close, zero Python child processes, and released ports. Do not run destructive target programming; this qualification is read-only unless a later user instruction explicitly authorizes flashing.

- [ ] **Step 4: Update durable AI memory with factual results**

Record the final source commits, exact automated counts, real-target results, package filename/size/hash, limitations, and next actions without local hardware paths or identifiers. Then run:

```powershell
python scripts/ai_memory.py render
python scripts/ai_memory.py validate
git diff --check
```

- [ ] **Step 5: Commit the handoff**

```powershell
git add -- docs/ai/project-memory.json docs/ai/CURRENT_HANDOFF.md
git commit -m "docs: hand off stable SuperWatch symbol tree"
```

- [ ] **Step 6: Final verification and push**

Run fresh final evidence:

```powershell
cd gui
npm test
npm run build
cd ..
python scripts/ai_memory.py validate
git diff --check
git push origin feature/online-flash-streaming
git status --short --branch
git rev-list --left-right --count HEAD...origin/feature/online-flash-streaming
```

Expected: tests and build PASS, AI memory validates, local/remote counts are `0 0`, and the worktree is clean.
