<template>
  <div ref="workspace" class="superwatch-workspace" :class="{ focused: focusMode, compact: hideSettings, 'catalog-hidden': hideCatalog }" :style="{ gridTemplateColumns: `${panelWidth}px 5px minmax(0, 1fr)` }">
    <div class="watch-catalog-pane">
      <div class="watch-source-tabs">
        <button :class="{ active: source === 'variables' }" @click="source = 'variables'">{{ tr('程序变量', 'Variables') }}</button>
        <button :class="{ active: source === 'peripherals' }" @click="source = 'peripherals'">{{ tr('芯片外设', 'Peripherals') }}</button>
      </div>
    <SymbolVariablePanel v-show="source === 'variables'"
      :device-connected="deviceConnected"
      :symbol-loaded="symbolLoaded"
      :symbol-error="symbolError"
      :latest-values="latestValues"
      :hidden-channels="hiddenChannels"
      :snapshot-path="snapshotPath"
      @visibility-change="setChannelVisibility"
      @selection-removed="clearChannelVisibility"
      @snapshot-change="snapshotPath = $event"
    />
      <PeripheralWatchPanel v-show="source === 'peripherals'" :device-connected="deviceConnected" :latest-values="latestValues" />
    </div>
    <div class="workspace-resizer" role="separator" tabindex="0" aria-orientation="vertical"
      :aria-valuenow="panelWidth" :aria-valuemin="280" :aria-valuemax="maxPanelWidth()"
      :aria-label="tr('调整变量目录宽度', 'Resize variable catalog')"
      :title="tr('拖动或使用方向键调整目录宽度', 'Drag or use arrow keys to resize catalog')"
      @mousedown.prevent="startResize" @keydown="resizeByKey"></div>
    <div class="waveform-pane">
      <div class="workspace-actions">
        <button @click="focusMode = !focusMode">{{ focusMode ? tr('退出专注', 'Exit focus') : tr('展开工作区', 'Focus workspace') }}</button>
        <button @click="hideCatalog = !hideCatalog">{{ hideCatalog ? tr('显示目录','Show catalog') : tr('只看已选','Selected only') }}</button>
        <button @click="hideSettings = !hideSettings">{{ hideSettings ? tr('显示配置','Show settings') : tr('隐藏配置','Hide settings') }}</button>
      </div>
      <div class="speed-controls" v-show="!hideSettings">
        <label for="superwatch-speed">{{ tr('采样调试速率', 'Memory sampling clock') }}</label>
        <select id="superwatch-speed" v-model="speedProfile" @change="speedDirty = true" data-testid="superwatch-speed" class="form-select" :disabled="applyingSpeed">
          <option value="low">{{ tr('低速 · 4 MHz', 'Low · 4 MHz') }}</option>
          <option value="medium">{{ tr('中速 · 10 MHz（默认）', 'Medium · 10 MHz (default)') }}</option>
          <option value="high">{{ tr('高速 · 20 MHz', 'High · 20 MHz') }}</option>
          <option value="ultra">{{ tr('超高速 · 30 MHz', 'Ultra · 30 MHz') }}</option>
        </select>
        <button class="btn btn-sm" data-testid="apply-superwatch-speed" :disabled="!deviceConnected || applyingSpeed" @click="applySpeed">{{ tr('应用档位', 'Apply speed') }}</button>
        <span role="status">{{ speedMessage }}</span>
      </div>
      <WaveformViewer
        mode="SuperWatch"
        :device-connected="deviceConnected"
        :hidden-channels="hiddenChannels"
        :array-snapshot-path="snapshotPath"
        @latest-values="latestValues = $event"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import SymbolVariablePanel from './SymbolVariablePanel.vue'
import PeripheralWatchPanel from './PeripheralWatchPanel.vue'
import WaveformViewer from './WaveformViewer.vue'
import { tr } from '../../composables/useLanguage'
import { API_BASE } from '../../lib/runtimeEndpoint'

const props = withDefaults(defineProps<{
  deviceConnected: boolean
  symbolLoaded?: boolean
  symbolError?: string
}>(), {
  symbolLoaded: true,
  symbolError: '',
})

const focusMode = ref(false), hideSettings = ref(false), hideCatalog = ref(false)
function exitFocus(event: KeyboardEvent) { if (event.key === 'Escape') focusMode.value = false }
onMounted(() => window.addEventListener('keydown', exitFocus))
onUnmounted(() => window.removeEventListener('keydown', exitFocus))
const panelWidth = ref(340)
const workspace = ref<HTMLElement | null>(null)
let workspaceObserver: ResizeObserver | undefined
const source = ref('variables')
const latestValues = shallowRef<Record<string, number | boolean>>({})
const hiddenChannels = shallowRef(new Set<string>())
const snapshotPath = ref<string | null>(null)
const speedProfile = ref('medium')
const applyingSpeed = ref(false)
const speedMessage = ref('')
const speedDirty = ref(false)
let speedTimer: ReturnType<typeof setTimeout> | null = null
let speedDisposed = false
async function pollSpeed() {
  if (!speedDirty.value && !applyingSpeed.value) await loadSpeed()
  if (!speedDisposed) speedTimer = setTimeout(pollSpeed, 1000)
}
onUnmounted(() => { speedDisposed = true; if (speedTimer !== null) clearTimeout(speedTimer) })

async function loadSpeed(): Promise<void> {
  try {
    const response = await fetch(`${API_BASE}/api/device/debug-speed`)
    if (!response.ok) return
    const payload = await response.json()
    if (speedDisposed || speedDirty.value || applyingSpeed.value) return
    if (['low', 'medium', 'high', 'ultra'].includes(payload.profile)) speedProfile.value = payload.profile
  } catch { /* The backend can still be starting. */ }
}

async function applySpeed(): Promise<void> {
  applyingSpeed.value = true
  speedMessage.value = ''
  try {
    const response = await fetch(`${API_BASE}/api/device/debug-speed`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile: speedProfile.value }),
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : response.statusText)
    speedDirty.value = false
    speedMessage.value = tr('已应用；可开始采样', 'Applied; ready to sample')
  } catch (error: any) {
    speedMessage.value = error.message
  } finally {
    applyingSpeed.value = false
  }
}
let resizeStartX = 0
let resizeStartWidth = 0

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

function startResize(event: MouseEvent): void {
  resizeStartX = event.clientX
  resizeStartWidth = panelWidth.value
  document.addEventListener('mousemove', resizePanel)
  document.addEventListener('mouseup', stopResize, { once: true })
}

function resizePanel(event: MouseEvent): void {
  panelWidth.value = clampPanelWidth(resizeStartWidth + event.clientX - resizeStartX)
}

function maxPanelWidth(): number {
  // Leave a small usable waveform pane; large screens can use their full width.
  return Math.max(280, (workspace.value?.clientWidth || window.innerWidth) - 165)
}

function clampPanelWidth(width: number): number {
  return Math.min(maxPanelWidth(), Math.max(280, width))
}

function resizeByKey(event: KeyboardEvent): void {
  if (event.key === 'ArrowLeft') panelWidth.value = clampPanelWidth(panelWidth.value - 40)
  else if (event.key === 'ArrowRight') panelWidth.value = clampPanelWidth(panelWidth.value + 40)
  else if (event.key === 'Home') panelWidth.value = 280
  else if (event.key === 'End') panelWidth.value = maxPanelWidth()
  else return
  event.preventDefault()
}

onMounted(() => {
  workspaceObserver = new ResizeObserver(() => { panelWidth.value = clampPanelWidth(panelWidth.value) })
  if (workspace.value) workspaceObserver.observe(workspace.value)
})

function stopResize(): void {
  document.removeEventListener('mousemove', resizePanel)
}

onUnmounted(() => {
  workspaceObserver?.disconnect()
  document.removeEventListener('mousemove', resizePanel)
  document.removeEventListener('mouseup', stopResize)
})

async function loadSnapshotSelection(): Promise<void> {
  if (!props.deviceConnected) {
    snapshotPath.value = null
    return
  }
  try {
    const response = await fetch(`${API_BASE}/api/dash/superwatch/array-snapshot`)
    if (!response.ok) return
    const payload = await response.json()
    snapshotPath.value = payload?.snapshot?.name ?? null
  } catch {
    // The dashboard can mount before the API is ready; retry on reconnect.
  }
}

onMounted(loadSnapshotSelection)
watch(() => props.deviceConnected, loadSnapshotSelection)
onMounted(pollSpeed)
watch(() => props.deviceConnected, loadSpeed)
</script>

<style scoped>
.focused { position:fixed; inset:0; z-index:900; background:var(--bg); height:100dvh !important; padding:8px; box-sizing:border-box; }
.workspace-actions { display:flex; gap:6px; padding:4px; flex-shrink:0; }
.workspace-actions button { background:var(--surface);color:var(--text);border:1px solid var(--border);padding:5px 8px;border-radius:4px; }
.catalog-hidden :deep(.symbol-panel > :not(.selected-workspace)) { display:none !important; }
.catalog-hidden :deep(.selected-workspace) { max-height:100%; flex:1; }
.catalog-hidden .watch-source-tabs { display:none; }
.compact :deep(#control-toolbar > label), .compact :deep(.buffer-unit), .compact :deep(#interval-group), .compact :deep(#control-toolbar .ctrl-sep), .compact :deep(#trigger-toolbar), .compact :deep(#buffer-input), .compact :deep(#btn-apply-buffer), .compact :deep(#buffer-memory-estimate), .compact :deep(#interval-input), .compact :deep(#btn-apply-interval) { display:none; }

.watch-catalog-pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; }
.watch-catalog-pane :deep(.symbol-panel) { flex: 1; min-height: 0; }
.watch-source-tabs { display: flex; border-bottom: 1px solid var(--border); flex: 0 0 auto; }
.watch-source-tabs button { flex: 1; padding: 10px; border: 0; background: var(--surface); color: var(--muted); cursor: pointer; }
.watch-source-tabs button.active { color: var(--accent); box-shadow: inset 0 -2px var(--accent); }
.superwatch-workspace {
  display: grid;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.workspace-resizer {
  width: 5px;
  background: var(--border);
  cursor: col-resize;
}
.workspace-resizer:hover { background: var(--accent); }
.waveform-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.waveform-pane > :last-child { flex: 1; min-height: 0; }
.speed-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 6px 12px; flex: 0 0 auto; font-size: 12px; }
.speed-controls select { width: auto; }
.speed-controls [role="status"] { color: var(--muted); }

@media (max-width: 760px) {
  .superwatch-workspace {
    grid-template-columns: 1fr !important;
    grid-template-rows: minmax(220px, 38vh) minmax(360px, 1fr);
    overflow: auto;
  }
  .workspace-resizer { display: none; }
}
</style>
