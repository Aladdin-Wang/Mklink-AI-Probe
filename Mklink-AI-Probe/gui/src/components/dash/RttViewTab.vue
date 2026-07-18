<template>
  <div class="rtt-view-tab">
    <div v-if="!deviceConnected" class="alert alert-warn">请先连接设备。</div>
    <template v-else>
      <div class="rtt-address-row">
        <label for="rtt-address">RTT 地址</label>
        <input
          id="rtt-address" v-model="rttAddress" data-testid="rtt-address"
          type="text" spellcheck="false" placeholder="0x20000000" @input="onAddressInput"
        >
        <button data-testid="rtt-search" type="button" class="btn-search" @click="searchRttAddress">
          <Search :size="15" />
          <span>{{ searching ? '搜索中' : '自动搜索' }}</span>
        </button>
        <span v-if="addressError" class="address-error" role="alert">{{ addressError }}</span>
        <span v-else-if="addressSource" class="address-source">来源: {{ addressSource }}</span>
      </div>
      <div class="rtt-view-toolbar">
        <ControlToolbar
          :state="toolbarState" :error="runtimeError || dash.error.value"
          :device-connected="deviceConnected && !searching"
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
      <VirtualLogPanel ref="logPanel" class="rtt-view-log" />
      <RttTransmitBar
        :enabled="transmitEnabled" :settings="settings" :send="sendRtt"
        @settings-change="persistSettings"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Search } from '@lucide/vue'
import { useDashboard } from '../../composables/useDashboard'
import { useBinaryStream } from '../../composables/useBinaryStream'
import { useMklinkApi } from '../../composables/useMklinkApi'
import { useResourceStatus } from '../../composables/useResourceStatus'
import {
  loadDesktopSettings,
  saveDesktopSettings,
  type DesktopSettings,
} from '../../lib/desktopSettings'
import { RenderScheduler } from '../../lib/stream/renderScheduler'
import ControlToolbar from './ControlToolbar.vue'
import RttTransmitBar from './RttTransmitBar.vue'
import VirtualLogPanel, { type VirtualLogInput } from './VirtualLogPanel.vue'

const props = defineProps<{ deviceConnected: boolean }>()
const dash = useDashboard('rtt')
const binary = useBinaryStream('rtt', { capacity: 200_000, channelCount: 1 })
const { findRtt, writeRtt } = useMklinkApi()
const { checkConflict } = useResourceStatus()
const desktopStorage = localStorage
const settings = ref<DesktopSettings>(loadDesktopSettings(desktopStorage))
const rttAddress = ref(settings.value.rttAddress)
const addressError = ref('')
const addressSource = ref('')
const searching = ref(false)
const starting = ref(false)
const stopping = ref(false)
const statusRunning = ref(false)
const downBuffers = ref<Array<{ channel?: number, active?: boolean }>>([])
const logPanel = ref<InstanceType<typeof VirtualLogPanel> | null>(null)
const chart = ref<HTMLCanvasElement | null>(null)
const retainedCount = computed(() => logPanel.value?.retainedCount ?? 0)
const numericChannelCount = ref(0)
const renderPaused = ref(false)
const runtimeError = ref<string | null>(null)
const RTT_CHANNEL = 0
const RTT_SEARCH_SIZE = 1024
const effectiveRunning = computed(() => (
  statusRunning.value || dash.state.value === 'running'
))
const transmitEnabled = computed(() => (
  statusRunning.value
  && !stopping.value
  && !runtimeError.value
  && props.deviceConnected
  && downBuffers.value.some(buffer => (
    buffer.channel === RTT_CHANNEL && buffer.active === true
  ))
))
const toolbarState = computed(() => (
  runtimeError.value ? 'error' :
    starting.value ? 'starting' :
      effectiveRunning.value && renderPaused.value ? 'paused' :
        effectiveRunning.value ? 'running' : dash.state.value
))
let requestId = 0
let statusTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false
let searchGeneration = 0
let binaryAttached = false

function persistSettings(next: DesktopSettings): void {
  settings.value = saveDesktopSettings(desktopStorage, next)
}

function isRttAddress(value: string): boolean {
  return /^0x[0-9a-f]{1,8}$/i.test(value)
}

function onAddressInput(): void {
  searchGeneration++
  searching.value = false
  addressError.value = ''
  addressSource.value = ''
  const address = rttAddress.value.trim()
  if (isRttAddress(address)) {
    persistSettings({ ...settings.value, rttAddress: address })
  }
}

async function searchRttAddress(): Promise<void> {
  const generation = ++searchGeneration
  searching.value = true
  addressError.value = ''
  const symbolPath = settings.value.symbolPath.trim()
  const mapPath = settings.value.mapPath.trim()
  const source = symbolPath || mapPath || undefined
  try {
    const result = await findRtt(source)
    if (disposed || generation !== searchGeneration) return
    if (!result.addr || !isRttAddress(result.addr)) {
      throw new Error(result.details?.join('；') || result.warnings?.join('；') || '未找到 RTT 地址')
    }
    rttAddress.value = result.addr
    addressSource.value = result.source || (source ? '所选文件' : '工程自动检测')
    persistSettings({ ...settings.value, rttAddress: result.addr })
  } catch (caught) {
    if (!disposed && generation === searchGeneration) {
      addressError.value = caught instanceof Error ? caught.message : String(caught)
    }
  } finally {
    if (!disposed && generation === searchGeneration) searching.value = false
  }
}

async function sendRtt(payload: Uint8Array): Promise<void> {
  await writeRtt(payload)
}

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

function attachBinary(): void {
  if (binaryAttached) return
  binaryAttached = true
  binary.start()
}

function detachBinary(): void {
  if (!binaryAttached) return
  binaryAttached = false
  binary.stop()
}

async function refreshStatus(): Promise<Record<string, any> | null> {
  try {
    const apiBase = import.meta.env.VITE_MKLINK_API || ''
    const response = await fetch(`${apiBase}/api/dash/rtt/status`)
    if (response.ok) {
      const status = await response.json()
      statusRunning.value = status.running === true
      downBuffers.value = Array.isArray(status.down_buffers) ? status.down_buffers : []
      numericChannelCount.value = Array.isArray(status.numeric_channels) ? status.numeric_channels.length : 0
      if (typeof status.error === 'string' && status.error) {
        runtimeError.value = status.error
        binaryAttached = false
        binary.stop()
      } else if (statusRunning.value && !runtimeError.value) {
        attachBinary()
      }
      return status
    }
  } catch { /* low-rate status retries below */ }
  return null
}

async function pollStatus(): Promise<void> {
  await refreshStatus()
  if (!disposed) statusTimer = setTimeout(pollStatus, 1_000)
}

async function waitForRttReady(timeoutMs = 11_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (!disposed && Date.now() < deadline) {
    const status = await refreshStatus()
    if (runtimeError.value) return false
    if (status?.running === true && typeof status.control_block_addr === 'string') {
      return true
    }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  if (!disposed) {
    runtimeError.value = 'RTT 启动超时，请检查地址后重试'
    detachBinary()
    const stopped = await stopTimedOutRtt()
    statusRunning.value = false
    downBuffers.value = []
    if (!stopped) {
      runtimeError.value = 'RTT 启动超时，后台仍在停止，请点击停止重试'
    }
  }
  return false
}

async function stopTimedOutRtt(maxAttempts = 3): Promise<boolean> {
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (await dash.stop()) return true
    if (attempt + 1 < maxAttempts) {
      await new Promise(resolve => setTimeout(resolve, 500))
    }
  }
  return false
}

async function onStart(): Promise<void> {
  if (searching.value || starting.value) return
  const address = rttAddress.value.trim()
  if (!isRttAddress(address)) {
    addressError.value = '请输入有效的 RTT 地址，例如 0x20001A40'
    return
  }
  persistSettings({ ...settings.value, rttAddress: address })
  starting.value = true
  try {
    stopping.value = false
    const conflicts = await checkConflict('rtt')
    if (conflicts.length && !confirm(`启动 RTT 将停止 ${conflicts.join('、')}，确认？`)) return
    clearLogs()
    renderPaused.value = false
    runtimeError.value = null
    scheduler.start()
    binary.reset()
    const started = await dash.start({
      addr: address,
      mode: 0,
      search_size: RTT_SEARCH_SIZE,
    })
    if (!started || disposed) return
    attachBinary()
    await waitForRttReady()
  } finally {
    starting.value = false
  }
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
  stopping.value = true
  renderPaused.value = false
  statusRunning.value = false
  downBuffers.value = []
  detachBinary()
  try {
    const stopped = await dash.stop()
    runtimeError.value = stopped ? null : (dash.error.value || 'RTT 停止未完成，请再次停止')
  } finally {
    stopping.value = false
  }
}

function clearLogs(): void {
  logPanel.value?.clear()
}

onMounted(() => {
  scheduler.start()
  void pollStatus()
})

onUnmounted(() => {
  disposed = true
  searchGeneration++
  if (statusTimer !== null) clearTimeout(statusTimer)
  detachBinary()
  scheduler.dispose()
})
</script>

<style scoped>
.rtt-view-tab { display: flex; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; }
.alert-warn { color: var(--warn); padding: 8px; border: 1px solid var(--warn); border-radius: 4px; }
.rtt-address-row { display: grid; grid-template-columns: auto minmax(180px, 320px) auto minmax(0, 1fr); align-items: center; gap: 8px; padding: 4px 0; }
.rtt-address-row label { font-size: 12px; color: var(--muted); }
.rtt-address-row input { min-width: 0; height: 30px; padding: 0 8px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: inherit; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.btn-search { height: 30px; display: inline-flex; align-items: center; gap: 5px; padding: 0 9px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: inherit; cursor: pointer; }
.address-error { min-width: 0; color: var(--danger, #dc2626); font-size: 12px; overflow-wrap: anywhere; }
.address-source { min-width: 0; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.rtt-view-toolbar { display: flex; align-items: center; gap: 8px; padding: 6px 0; flex-wrap: wrap; }
.line-count, .stream-health { color: var(--muted); font-size: 12px; }
.btn-clear { background: none; border: 1px solid var(--border); border-radius: 4px; color: var(--muted); cursor: pointer; padding: 2px 8px; }
.rtt-numeric-chart { width: 100%; height: 160px; flex: 0 0 160px; border: 1px solid var(--border); border-radius: var(--radius); background: #10151d; }
.rtt-view-log { flex: 1 1 auto; min-height: 160px; margin-top: 8px; border: 1px solid var(--border); border-radius: var(--radius); }
@media (max-width: 720px) {
  .rtt-address-row { grid-template-columns: auto minmax(0, 1fr) auto; }
  .address-error, .address-source { grid-column: 1 / -1; }
}
</style>
