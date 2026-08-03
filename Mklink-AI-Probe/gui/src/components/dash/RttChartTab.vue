<template>
  <div class="rtt-chart-tab">
    <ControlToolbar
      :state="dash.state.value"
      :error="dash.error.value"
      :device-connected="deviceConnected"
      :point-count="data.length"
      @start="onStart"
      @pause="dash.pause()"
      @resume="dash.resume()"
      @stop="onStop"
    />
    <VariableChips
      :channels="channelNames"
      :active-channels="activeChannels"
      @toggle="toggleChannel"
    />
    <CrossPickerCanvas ref="chart" height="300px" />
    <RawLogPanel :lines="rawLines" max-height="150px" @clear="rawLines = []" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useDashboard } from '../../composables/useDashboard'
import { useEventSource } from '../../composables/useEventSource'
import { useResourceStatus } from '../../composables/useResourceStatus'
import ControlToolbar from './ControlToolbar.vue'
import VariableChips from './VariableChips.vue'
import CrossPickerCanvas from './CrossPickerCanvas.vue'
import RawLogPanel from './RawLogPanel.vue'
import { takeNewStreamPoints } from '../../lib/streamCursor'
import { tr } from '../../composables/useLanguage'

const props = defineProps<{ deviceConnected: boolean }>()

const dash = useDashboard('rtt')
const { data, connect, disconnect } = useEventSource('/api/dash/rtt/stream')
const { checkConflict } = useResourceStatus()
const chart = ref<InstanceType<typeof CrossPickerCanvas> | null>(null)
const rawLines = ref<string[]>([])
const activeChannels = ref<Set<string>>(new Set())
const maxRawLines = 500
let lastStreamSeq = 0

const DASH_NAMES: Record<string, string> = {
  rtt: 'RTT', superwatch: 'SuperWatch', vofa: 'VOFA+',
}

const channelNames = computed(() => {
  const names = new Set<string>()
  for (const dp of data.value) {
    for (const k of Object.keys(dp)) {
      if (!k.startsWith('_') && typeof dp[k] === 'number') names.add(k)
    }
  }
  return Array.from(names).sort()
})

function toggleChannel(name: string) {
  if (activeChannels.value.has(name)) activeChannels.value.delete(name)
  else activeChannels.value.add(name)
  // Trigger reactivity
  activeChannels.value = new Set(activeChannels.value)
}

// Push SSE data to chart
watch(data, (newData) => {
  if (!chart.value) return
  const fresh = takeNewStreamPoints(newData as any[], lastStreamSeq)
  for (const dp of fresh.points as any[]) {
    const evt = dp.event || dp._event
    if (evt === 'data' || !evt) {
      chart.value.pushDataPoint(dp as Record<string, unknown>)
    } else if (evt === 'raw') {
      rawLines.value.push(dp.line as string)
      if (rawLines.value.length > maxRawLines) {
        rawLines.value = rawLines.value.slice(-maxRawLines)
      }
    }
  }
  lastStreamSeq = fresh.nextSeq
})

async function onStart() {
  const conflicts = await checkConflict('rtt')
  if (conflicts.length > 0) {
    const names = conflicts.map(c => DASH_NAMES[c] || c).join('、')
    if (!confirm(tr(`启动 RTT 将停止当前运行的 ${names} 会话。确认？`, `Starting RTT will stop the active ${names} session. Continue?`))) return
  }
  await dash.start()
  setTimeout(() => {
    connect()
  }, 500)
}

async function onStop() {
  disconnect()
  await dash.stop()
  rawLines.value = []
  lastStreamSeq = 0
}
</script>

<style scoped>
.rtt-chart-tab {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
