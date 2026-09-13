<template>
  <div class="superwatch-workspace" :style="{ gridTemplateColumns: `${panelWidth}px 5px minmax(0, 1fr)` }">
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
    <div class="workspace-resizer" :title="tr('调整变量目录宽度', 'Resize variable catalog')" @mousedown="startResize"></div>
    <div class="waveform-pane">
      <div class="speed-controls">
        <label for="superwatch-speed">{{ tr('采样调试速率', 'Memory sampling clock') }}</label>
        <select id="superwatch-speed" v-model="speedProfile" data-testid="superwatch-speed" class="form-select" :disabled="applyingSpeed">
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

const panelWidth = ref(340)
const source = ref('variables')
const latestValues = shallowRef<Record<string, number | boolean>>({})
const hiddenChannels = shallowRef(new Set<string>())
const snapshotPath = ref<string | null>(null)
const speedProfile = ref('medium')
const applyingSpeed = ref(false)
const speedMessage = ref('')

async function loadSpeed(): Promise<void> {
  try {
    const response = await fetch(`${API_BASE}/api/device/debug-speed`)
    if (!response.ok) return
    const payload = await response.json()
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
  panelWidth.value = Math.min(520, Math.max(280, resizeStartWidth + event.clientX - resizeStartX))
}

function stopResize(): void {
  document.removeEventListener('mousemove', resizePanel)
}

onUnmounted(() => {
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
onMounted(loadSpeed)
watch(() => props.deviceConnected, loadSpeed)
</script>

<style scoped>
.watch-catalog-pane { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
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
