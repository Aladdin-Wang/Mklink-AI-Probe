<template>
  <div class="superwatch-workspace" :style="{ gridTemplateColumns: `${panelWidth}px 5px minmax(0, 1fr)` }">
    <SymbolVariablePanel
      :device-connected="deviceConnected"
      :latest-values="latestValues"
      :hidden-channels="hiddenChannels"
      @visibility-change="setChannelVisibility"
      @selection-removed="clearChannelVisibility"
    />
    <div class="workspace-resizer" title="调整变量目录宽度" @mousedown="startResize"></div>
    <div class="waveform-pane">
      <WaveformViewer
        mode="SuperWatch"
        :device-connected="deviceConnected"
        :hidden-channels="hiddenChannels"
        @latest-values="latestValues = $event"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onUnmounted, ref, shallowRef } from 'vue'
import SymbolVariablePanel from './SymbolVariablePanel.vue'
import WaveformViewer from './WaveformViewer.vue'

defineProps<{ deviceConnected: boolean }>()

const panelWidth = ref(340)
const latestValues = shallowRef<Record<string, number | boolean>>({})
const hiddenChannels = shallowRef(new Set<string>())
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
</script>

<style scoped>
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
.waveform-pane { min-width: 0; min-height: 0; overflow: hidden; }

@media (max-width: 760px) {
  .superwatch-workspace {
    grid-template-columns: 1fr !important;
    grid-template-rows: minmax(220px, 38vh) minmax(360px, 1fr);
    overflow: auto;
  }
  .workspace-resizer { display: none; }
}
</style>
