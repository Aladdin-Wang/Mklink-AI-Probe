<template>
  <section class="vofa-page">
    <p class="vofa-help">{{ tr('共享 VOFA 波形：在 CLI 或 AI 中选择采样通道；此页显示同一后台的数据。暂停仅暂停绘图。', 'Shared VOFA waveforms: choose channels in CLI or AI; this page displays the same backend data. Pause freezes the chart only.') }}</p>
    <WaveformViewer mode="VOFA" :device-connected="deviceStatus.connected" />
  </section>
</template>

<script setup lang="ts">
import WaveformViewer from '../components/dash/WaveformViewer.vue'
import { useMklinkApi } from '../composables/useMklinkApi'
import { tr } from '../composables/useLanguage'
const { deviceStatus } = useMklinkApi()
</script>

<style scoped>
.vofa-page { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.vofa-help { color: var(--muted); margin: 0 0 8px; font-size: 12px; }
.vofa-page :deep(.waveform-viewer) { flex: 1; min-height: 0; }
</style>
