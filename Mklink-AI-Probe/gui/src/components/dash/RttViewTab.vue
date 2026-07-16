<template>
  <div class="rtt-view-tab">
    <div v-if="!deviceConnected" class="alert alert-warn">请先连接设备。</div>
    <template v-else>
      <div class="rtt-view-toolbar">
        <ControlToolbar
          :state="toolbarState" :error="runtimeError || dash.error.value"
          :device-connected="deviceConnected"
          @start="onStart" @pause="onPauseRender" @resume="onResumeRender" @stop="onStop"
        />
        <span class="line-count">{{ retainedCount }} 行</span>
        <span class="stream-health">
          buffer {{ binary.telemetry.value?.bufferedSamples ?? 0 }} ·
          drops {{ binary.telemetry.value?.transportDroppedBatches ?? 0 }}/{{ binary.telemetry.value?.backendDroppedBatches ?? 0 }}
        </span>
        <button class="btn-clear" @click="clearLogs">清除</button>
      </div>
      <canvas v-show="numericChannelCount > 0" ref="chart" class="rtt-numeric-chart" />
      <VirtualLogPanel
        ref="logPanel" class="rtt-view-log" :class="{ 'is-empty': !hasTextLogs }"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useDashboard } from '../../composables/useDashboard'
import { useBinaryStream } from '../../composables/useBinaryStream'
import { useResourceStatus } from '../../composables/useResourceStatus'
import { RenderScheduler } from '../../lib/stream/renderScheduler'
import ControlToolbar from './ControlToolbar.vue'
import VirtualLogPanel, { type VirtualLogInput } from './VirtualLogPanel.vue'

const props = defineProps<{ deviceConnected: boolean }>()
const dash = useDashboard('rtt')
const binary = useBinaryStream('rtt', { capacity: 200_000, channelCount: 1 })
const { checkConflict } = useResourceStatus()
const logPanel = ref<InstanceType<typeof VirtualLogPanel> | null>(null)
const chart = ref<HTMLCanvasElement | null>(null)
const retainedCount = computed(() => logPanel.value?.retainedCount ?? 0)
const numericChannelCount = ref(0)
const hasTextLogs = ref(false)
const renderPaused = ref(false)
const runtimeError = ref<string | null>(null)
const toolbarState = computed(() => (
  runtimeError.value ? 'error' :
    dash.state.value === 'running' && renderPaused.value ? 'paused' : dash.state.value
))
let requestId = 0
let statusTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false

const scheduler = new RenderScheduler(() => {
  const canvas = chart.value
  if (!canvas || numericChannelCount.value <= 0) return
  const telemetry = binary.telemetry.value
  if (!telemetry?.bufferedSamples) return
  const batch = binary.waveformBatch.value
  const start = batch?.bufferStartMs
  const end = batch?.bufferEndMs
  if (start == null || end == null || !Number.isFinite(start) || !Number.isFinite(end)) return
  binary.requestVisibleRange(++requestId, start, end, Math.max(1, canvas.clientWidth || 640))
})

watch(() => binary.rttLines.value, batch => {
  if (!batch || renderPaused.value) return
  if (batch.lines.length) hasTextLogs.value = true
  logPanel.value?.append(batch.lines.map(line => ({
    time: line.timestampNs, level: line.level, text: line.text,
  } satisfies VirtualLogInput)))
})

watch(() => binary.waveformBatch.value, batch => {
  if (!batch) return
  numericChannelCount.value = batch.channelCount
  scheduler.recordCollection(batch.itemCount)
  scheduler.invalidate('data')
})

watch(() => binary.envelope.value, envelope => {
  if (!envelope || renderPaused.value || envelope.requestId !== requestId) return
  drawEnvelope(envelope)
})

function drawEnvelope(envelope: NonNullable<typeof binary.envelope.value>): void {
  const canvas = chart.value
  if (!canvas) return
  const width = Math.max(1, canvas.clientWidth || 640)
  const height = Math.max(1, canvas.clientHeight || 160)
  const dpr = window.devicePixelRatio || 1
  canvas.width = Math.round(width * dpr)
  canvas.height = Math.round(height * dpr)
  const context = canvas.getContext('2d')
  if (!context) return
  context.setTransform(dpr, 0, 0, dpr, 0, 0)
  context.clearRect(0, 0, width, height)
  const values = new Float32Array(envelope.values)
  const offsets = new Uint32Array(envelope.channelOffsets)
  let minimum = Infinity
  let maximum = -Infinity
  for (const value of values) { minimum = Math.min(minimum, value); maximum = Math.max(maximum, value) }
  const span = maximum > minimum ? maximum - minimum : 1
  const colors = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
  for (let channel = 0; channel < envelope.channelCount; channel++) {
    const first = offsets[channel]
    const count = offsets[channel + 1] - first
    if (!count) continue
    context.beginPath()
    context.strokeStyle = colors[channel % colors.length]
    for (let point = 0; point < count; point++) {
      const x = count <= 1 ? 0 : point / (count - 1) * width
      const y = height - (values[first + point] - minimum) / span * height
      if (point === 0) context.moveTo(x, y); else context.lineTo(x, y)
    }
    context.stroke()
  }
}

async function pollStatus(): Promise<void> {
  try {
    const response = await fetch('/api/dash/rtt/status')
    if (response.ok) {
      const status = await response.json()
      numericChannelCount.value = Array.isArray(status.numeric_channels) ? status.numeric_channels.length : 0
      if (typeof status.error === 'string' && status.error) {
        runtimeError.value = status.error
        binary.stop()
      }
    }
  } catch { /* low-rate status retries below */ }
  if (!disposed) statusTimer = setTimeout(pollStatus, 1_000)
}

async function onStart(): Promise<void> {
  const conflicts = await checkConflict('rtt')
  if (conflicts.length && !confirm(`启动 RTT 将停止 ${conflicts.join('、')}，确认？`)) return
  clearLogs()
  renderPaused.value = false
  runtimeError.value = null
  scheduler.start()
  binary.reset()
  const started = await dash.start()
  if (started && !disposed) binary.start()
}

function onPauseRender(): void {
  renderPaused.value = true
  requestId++
  scheduler.stop()
}

function onResumeRender(): void {
  renderPaused.value = false
  scheduler.start()
  scheduler.invalidate('data')
}

async function onStop(): Promise<void> {
  renderPaused.value = false
  runtimeError.value = null
  binary.stop()
  await dash.stop()
}

function clearLogs(): void {
  logPanel.value?.clear()
  hasTextLogs.value = false
}

onMounted(() => {
  scheduler.start()
  void pollStatus()
})

onUnmounted(() => {
  disposed = true
  if (statusTimer !== null) clearTimeout(statusTimer)
  binary.stop()
  scheduler.dispose()
})
</script>

<style scoped>
.rtt-view-tab { display: flex; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; }
.alert-warn { color: var(--warn); padding: 8px; border: 1px solid var(--warn); border-radius: 4px; }
.rtt-view-toolbar { display: flex; align-items: center; gap: 8px; padding: 6px 0; flex-wrap: wrap; }
.line-count, .stream-health { color: var(--muted); font-size: 12px; }
.btn-clear { background: none; border: 1px solid var(--border); border-radius: 4px; color: var(--muted); cursor: pointer; padding: 2px 8px; }
.rtt-numeric-chart { width: 100%; height: 160px; flex: 0 0 160px; border: 1px solid var(--border); border-radius: var(--radius); background: #10151d; }
.rtt-view-log { flex: 1 1 auto; min-height: 160px; margin-top: 8px; border: 1px solid var(--border); border-radius: var(--radius); }
.rtt-view-log.is-empty { display: none; }
</style>
