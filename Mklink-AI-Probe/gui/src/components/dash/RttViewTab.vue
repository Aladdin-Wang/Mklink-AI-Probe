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
        <label class="encoding-control" for="rtt-encoding">
          <span>编码</span>
          <select
            id="rtt-encoding" v-model="rttEncoding" data-testid="rtt-encoding"
            :disabled="starting || stopping" @change="onEncodingChange"
          >
            <option value="utf-8">UTF-8</option>
            <option value="gb2312">GB2312</option>
            <option value="gbk">GBK</option>
            <option value="gb18030">GB18030</option>
            <option value="big5">Big5</option>
          </select>
        </label>
        <span class="line-count">{{ retainedCount }} 行</span>
        <span class="stream-health">
          buffer {{ binary.telemetry.value?.bufferedSamples ?? 0 }} ·
          drops {{ binary.telemetry.value?.transportDroppedBatches ?? 0 }}/{{ binary.telemetry.value?.backendDroppedBatches ?? 0 }}
        </span>
        <button
          data-testid="rtt-chart-toggle" type="button" class="btn-chart-toggle"
          :aria-pressed="chartEnabled" @click="toggleChart"
        >
          <EyeOff v-if="chartEnabled" :size="14" />
          <Eye v-else :size="14" />
          <span>{{ chartEnabled ? '关闭曲线' : '打开曲线' }}</span>
        </button>
        <button class="btn-clear" @click="clearLogs">清除</button>
      </div>
      <div class="rtt-format-note">
        <Info :size="14" />
        <span>数据格式：每行输出同一组数值，例如 <code>temp=25.3,speed=1200</code> 或 <code>25.3,1200</code>。</span>
      </div>
      <div v-if="chartEnabled && hasChartData" class="rtt-chart-shell">
        <canvas
          ref="chart" class="rtt-numeric-chart"
          @wheel.prevent="onChartWheel" @mousedown="onChartMouseDown" @dblclick="resetChartViewport"
        />
        <div class="rtt-chart-hint">滚轮缩放坐标 · 左键拖动曲线 · 双击复位</div>
      </div>
      <VirtualLogPanel ref="logPanel" class="rtt-view-log" />
      <RttTransmitBar
        :enabled="transmitEnabled" :settings="settings" :send="sendRtt"
        @settings-change="persistSettings"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Eye, EyeOff, Info, Search } from '@lucide/vue'
import { useDashboard } from '../../composables/useDashboard'
import { useBinaryStream } from '../../composables/useBinaryStream'
import { useMklinkApi } from '../../composables/useMklinkApi'
import {
  loadDesktopSettings,
  saveDesktopSettings,
  type DesktopSettings,
  type RttEncoding,
} from '../../lib/desktopSettings'
import { RenderScheduler } from '../../lib/stream/renderScheduler'
import ControlToolbar from './ControlToolbar.vue'
import RttTransmitBar from './RttTransmitBar.vue'
import VirtualLogPanel, { type VirtualLogInput } from './VirtualLogPanel.vue'

const props = defineProps<{ deviceConnected: boolean }>()
const dash = useDashboard('rtt')
const binary = useBinaryStream('rtt', { capacity: 200_000, channelCount: 1 })
const { findRtt, writeRtt, setRttEncoding } = useMklinkApi()
const desktopStorage = localStorage
const settings = ref<DesktopSettings>(loadDesktopSettings(desktopStorage))
const rttAddress = ref(settings.value.rttAddress)
const rttEncoding = ref<RttEncoding>(settings.value.rttEncoding)
const addressError = ref('')
const addressSource = ref('')
const searching = ref(false)
const starting = ref(false)
const stopping = ref(false)
const statusRunning = ref(false)
const statusKnown = ref(false)
const downBuffers = ref<Array<{ channel?: number, active?: boolean }>>([])
const logPanel = ref<InstanceType<typeof VirtualLogPanel> | null>(null)
const chart = ref<HTMLCanvasElement | null>(null)
const retainedCount = computed(() => logPanel.value?.retainedCount ?? 0)
const numericChannelCount = ref(0)
const numericChannelNames = ref<string[]>([])
const chartEnabled = ref(true)
const hasChartData = ref(false)
const renderPaused = ref(false)
const runtimeError = ref<string | null>(null)
const RTT_CHANNEL = 0
const RTT_SEARCH_SIZE = 1024
const effectiveRunning = computed(() => (
  statusKnown.value ? statusRunning.value : dash.state.value === 'running'
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
        effectiveRunning.value ? 'running' :
          statusKnown.value ? 'idle' : dash.state.value
))
let requestId = 0
let statusTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false
let searchGeneration = 0
let binaryAttached = false
let latestEnvelope: NonNullable<typeof binary.envelope.value> | null = null
let dataRange: { start: number, end: number } | null = null
let visibleRange: { start: number, end: number } | null = null
let manualTimeline = false
let manualYRange: { min: number, max: number } | null = null
let lastDrawYRange: { min: number, max: number } | null = null
let resizeObserver: ResizeObserver | null = null
let chartDrag: {
  startX: number
  startY: number
  timeStart: number
  timeEnd: number
  yMin: number
  yMax: number
  width: number
  height: number
} | null = null
const CHART_MARGIN = { left: 58, right: 18, top: 14, bottom: 38 }
const CHART_COLORS = ['#4f8ff7', '#34c47c', '#f2ad3d', '#ed5d68', '#9b7af5', '#28b8c7']

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

async function onEncodingChange(): Promise<void> {
  persistSettings({ ...settings.value, rttEncoding: rttEncoding.value })
  if (!effectiveRunning.value) return
  try {
    const result = await setRttEncoding(rttEncoding.value)
    rttEncoding.value = result.encoding
    runtimeError.value = null
  } catch (caught) {
    runtimeError.value = caught instanceof Error ? caught.message : String(caught)
  }
}

const scheduler = new RenderScheduler(() => {
  const canvas = chart.value
  if (!canvas || !chartEnabled.value || !hasChartData.value || numericChannelCount.value <= 0) return
  const telemetry = binary.telemetry.value
  if (!telemetry?.bufferedSamples) return
  const range = visibleRange ?? dataRange
  if (!range || !Number.isFinite(range.start) || !Number.isFinite(range.end)) return
  binary.requestVisibleRange(
    ++requestId, range.start, range.end,
    Math.max(1, (canvas.clientWidth || 640) - CHART_MARGIN.left - CHART_MARGIN.right),
  )
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
  if (numericChannelNames.value.length !== batch.channelCount) {
    numericChannelNames.value = Array.from(
      { length: batch.channelCount }, (_, index) => `v${index}`,
    )
  }
  if (
    batch.itemCount > 0
    && batch.bufferStartMs != null && Number.isFinite(batch.bufferStartMs)
    && batch.bufferEndMs != null && Number.isFinite(batch.bufferEndMs)
  ) {
    hasChartData.value = true
    dataRange = { start: batch.bufferStartMs, end: batch.bufferEndMs }
    if (!manualTimeline && !renderPaused.value) visibleRange = { ...dataRange }
  }
  scheduler.recordCollection(batch.itemCount)
  if (!renderPaused.value && chartEnabled.value) scheduler.invalidate('data')
})

watch(() => binary.envelope.value, envelope => {
  if (!envelope || renderPaused.value || envelope.requestId !== requestId) return
  latestEnvelope = envelope
  drawEnvelope(envelope)
})

watch(chart, canvas => {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (!canvas) return
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      if (latestEnvelope) drawEnvelope(latestEnvelope)
      if (!renderPaused.value) scheduler.invalidate('resize')
    })
    resizeObserver.observe(canvas)
  }
  void nextTick(() => {
    if (latestEnvelope) drawEnvelope(latestEnvelope)
    if (!renderPaused.value) scheduler.invalidate('resize')
  })
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
  const times = new Float64Array(envelope.times)
  const timeIndices = new Uint32Array(envelope.timeIndices)
  const offsets = new Uint32Array(envelope.channelOffsets)
  let minimum = Infinity
  let maximum = -Infinity
  for (const value of values) { minimum = Math.min(minimum, value); maximum = Math.max(maximum, value) }
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) return
  const automaticPad = (maximum - minimum) * 0.1 || 1
  const yRange = manualYRange ?? {
    min: minimum - automaticPad,
    max: maximum + automaticPad,
  }
  lastDrawYRange = { ...yRange }
  const timeRange = visibleRange ?? dataRange
  if (!timeRange) return
  const plotWidth = Math.max(1, width - CHART_MARGIN.left - CHART_MARGIN.right)
  const plotHeight = Math.max(1, height - CHART_MARGIN.top - CHART_MARGIN.bottom)
  const timeSpan = Math.max(1e-9, timeRange.end - timeRange.start)
  const valueSpan = Math.max(1e-12, yRange.max - yRange.min)

  context.strokeStyle = '#293344'
  context.fillStyle = '#8995a8'
  context.lineWidth = 0.5
  context.font = '11px ui-monospace, SFMono-Regular, Consolas, monospace'
  for (let tick = 0; tick <= 5; tick++) {
    const x = CHART_MARGIN.left + plotWidth * tick / 5
    const y = CHART_MARGIN.top + plotHeight * tick / 5
    context.beginPath()
    context.moveTo(x, CHART_MARGIN.top)
    context.lineTo(x, CHART_MARGIN.top + plotHeight)
    context.moveTo(CHART_MARGIN.left, y)
    context.lineTo(CHART_MARGIN.left + plotWidth, y)
    context.stroke()
    context.textAlign = 'center'
    context.fillText(
      formatTimeTick(
        timeRange.start + timeSpan * tick / 5,
        dataRange?.start ?? timeRange.start,
      ),
      x, height - 17,
    )
    context.textAlign = 'right'
    context.fillText(
      formatValueTick(yRange.max - valueSpan * tick / 5, valueSpan),
      CHART_MARGIN.left - 7, y + 4,
    )
  }
  context.textAlign = 'center'
  context.fillText('时间', CHART_MARGIN.left + plotWidth / 2, height - 3)
  context.save()
  context.translate(12, CHART_MARGIN.top + plotHeight / 2)
  context.rotate(-Math.PI / 2)
  context.fillText('数值', 0, 0)
  context.restore()
  context.save()
  context.beginPath()
  context.rect(CHART_MARGIN.left, CHART_MARGIN.top, plotWidth, plotHeight)
  context.clip()
  for (let channel = 0; channel < envelope.channelCount; channel++) {
    const first = offsets[channel]
    const count = offsets[channel + 1] - first
    if (!count) continue
    context.beginPath()
    context.strokeStyle = CHART_COLORS[channel % CHART_COLORS.length]
    context.lineWidth = 1.5
    for (let point = 0; point < count; point++) {
      const offset = first + point
      const time = times[timeIndices[offset]]
      const x = CHART_MARGIN.left + (time - timeRange.start) / timeSpan * plotWidth
      const y = CHART_MARGIN.top + plotHeight - (values[offset] - yRange.min) / valueSpan * plotHeight
      if (point === 0) context.moveTo(x, y); else context.lineTo(x, y)
    }
    context.stroke()
  }
  context.restore()
  for (let channel = 0; channel < envelope.channelCount; channel++) {
    const name = numericChannelNames.value[channel] ?? `v${channel}`
    const x = CHART_MARGIN.left + 8
    const y = CHART_MARGIN.top + 12 + channel * 15
    if (y > CHART_MARGIN.top + plotHeight - 4) break
    context.fillStyle = CHART_COLORS[channel % CHART_COLORS.length]
    context.textAlign = 'left'
    context.fillText(name, x, y)
  }
}

function formatTimeTick(milliseconds: number, origin: number): string {
  const relative = milliseconds - origin
  if (Math.abs(relative) >= 1_000) return `${(relative / 1_000).toFixed(2)} s`
  if (Math.abs(relative) >= 1) return `${relative.toFixed(1)} ms`
  return `${(relative * 1_000).toFixed(0)} us`
}

function formatValueTick(value: number, span: number): string {
  if (Math.abs(value) >= 1e6 || (value !== 0 && Math.abs(value) < 1e-3)) {
    return value.toExponential(2)
  }
  const decimals = span >= 100 ? 0 : span >= 10 ? 1 : span >= 1 ? 2 : 3
  return value.toFixed(decimals).replace(/\.?0+$/, '') || '0'
}

function toggleChart(): void {
  chartEnabled.value = !chartEnabled.value
  if (!chartEnabled.value) {
    scheduler.stop()
    return
  }
  if (!renderPaused.value) scheduler.start()
  void nextTick(() => scheduler.invalidate('resize'))
}

function resetChartViewport(): void {
  manualTimeline = false
  manualYRange = null
  if (dataRange) visibleRange = { ...dataRange }
  if (latestEnvelope) drawEnvelope(latestEnvelope)
  if (!renderPaused.value) scheduler.invalidate('zoom')
}

function constrainTimeRange(start: number, end: number): { start: number, end: number } {
  if (!dataRange) return { start, end }
  const fullSpan = dataRange.end - dataRange.start
  const span = end - start
  if (!(fullSpan > 0) || span >= fullSpan) return { ...dataRange }
  if (start < dataRange.start) {
    return { start: dataRange.start, end: dataRange.start + span }
  }
  if (end > dataRange.end) {
    return { start: dataRange.end - span, end: dataRange.end }
  }
  return { start, end }
}

function onChartWheel(event: WheelEvent): void {
  const canvas = chart.value
  const range = visibleRange ?? dataRange
  const yRange = lastDrawYRange
  if (!canvas || !range) return
  const rect = canvas.getBoundingClientRect()
  const x = event.clientX - rect.left
  const y = event.clientY - rect.top
  const width = Math.max(1, rect.width - CHART_MARGIN.left - CHART_MARGIN.right)
  const height = Math.max(1, rect.height - CHART_MARGIN.top - CHART_MARGIN.bottom)
  const factor = event.deltaY > 0 ? 1.25 : 0.8
  const onXAxis = y >= rect.height - CHART_MARGIN.bottom
  const onYAxis = x <= CHART_MARGIN.left
  if (onXAxis || (!onXAxis && !onYAxis)) {
    const ratio = Math.max(0, Math.min(1, (x - CHART_MARGIN.left) / width))
    const span = range.end - range.start
    const anchor = range.start + span * ratio
    const nextSpan = Math.max(1e-6, span * factor)
    visibleRange = constrainTimeRange(
      anchor - nextSpan * ratio,
      anchor + nextSpan * (1 - ratio),
    )
    manualTimeline = true
  }
  if (yRange && (onYAxis || (!onXAxis && !onYAxis))) {
    const ratio = Math.max(0, Math.min(1, (y - CHART_MARGIN.top) / height))
    const span = yRange.max - yRange.min
    const anchor = yRange.max - span * ratio
    const nextSpan = Math.max(1e-12, span * factor)
    manualYRange = {
      min: anchor - nextSpan * (1 - ratio),
      max: anchor + nextSpan * ratio,
    }
  }
  if (latestEnvelope) drawEnvelope(latestEnvelope)
  if (!renderPaused.value) scheduler.invalidate('zoom')
}

function onChartMouseDown(event: MouseEvent): void {
  if (event.button !== 0) return
  const canvas = chart.value
  const timeRange = visibleRange ?? dataRange
  if (!canvas || !timeRange) return
  const yRange = lastDrawYRange ?? { min: 0, max: 1 }
  const rect = canvas.getBoundingClientRect()
  chartDrag = {
    startX: event.clientX,
    startY: event.clientY,
    timeStart: timeRange.start,
    timeEnd: timeRange.end,
    yMin: yRange.min,
    yMax: yRange.max,
    width: Math.max(1, rect.width - CHART_MARGIN.left - CHART_MARGIN.right),
    height: Math.max(1, rect.height - CHART_MARGIN.top - CHART_MARGIN.bottom),
  }
  event.preventDefault()
}

function onChartMouseMove(event: MouseEvent): void {
  if (!chartDrag) return
  const timeSpan = chartDrag.timeEnd - chartDrag.timeStart
  const ySpan = chartDrag.yMax - chartDrag.yMin
  const timeShift = -(event.clientX - chartDrag.startX) / chartDrag.width * timeSpan
  const yShift = (event.clientY - chartDrag.startY) / chartDrag.height * ySpan
  visibleRange = constrainTimeRange(
    chartDrag.timeStart + timeShift,
    chartDrag.timeEnd + timeShift,
  )
  manualTimeline = true
  manualYRange = {
    min: chartDrag.yMin + yShift,
    max: chartDrag.yMax + yShift,
  }
  if (latestEnvelope) drawEnvelope(latestEnvelope)
  if (!renderPaused.value) scheduler.invalidate('zoom')
}

function onChartMouseUp(): void {
  chartDrag = null
}

function resetChartData(): void {
  requestId++
  latestEnvelope = null
  dataRange = null
  visibleRange = null
  manualTimeline = false
  manualYRange = null
  lastDrawYRange = null
  hasChartData.value = false
  numericChannelCount.value = 0
  numericChannelNames.value = []
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
      statusKnown.value = true
      statusRunning.value = status.running === true
      if (statusRunning.value && typeof status.encoding === 'string') {
        const encoding = status.encoding as RttEncoding
        if (
          ['utf-8', 'gb2312', 'gbk', 'gb18030', 'big5'].includes(encoding)
          && rttEncoding.value !== encoding
        ) {
          rttEncoding.value = encoding
          persistSettings({ ...settings.value, rttEncoding: encoding })
        }
      }
      downBuffers.value = Array.isArray(status.down_buffers) ? status.down_buffers : []
      const channels = Array.isArray(status.numeric_channels)
        ? status.numeric_channels.map((name: unknown) => String(name))
        : []
      if (channels.length || !hasChartData.value) {
        numericChannelNames.value = channels
        numericChannelCount.value = channels.length
      }
      if (typeof status.error === 'string' && status.error) {
        runtimeError.value = status.error
        binaryAttached = false
        binary.stop()
      } else if (statusRunning.value && !runtimeError.value) {
        attachBinary()
      } else {
        detachBinary()
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
    clearLogs()
    resetChartData()
    renderPaused.value = false
    runtimeError.value = null
    scheduler.start()
    binary.reset()
    const started = await dash.start({
      addr: address,
      mode: 0,
      search_size: RTT_SEARCH_SIZE,
      encoding: rttEncoding.value,
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
  if (!manualTimeline && dataRange) visibleRange = { ...dataRange }
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
  window.addEventListener('mousemove', onChartMouseMove)
  window.addEventListener('mouseup', onChartMouseUp)
  scheduler.start()
  void pollStatus()
})

onUnmounted(() => {
  disposed = true
  searchGeneration++
  if (statusTimer !== null) clearTimeout(statusTimer)
  window.removeEventListener('mousemove', onChartMouseMove)
  window.removeEventListener('mouseup', onChartMouseUp)
  resizeObserver?.disconnect()
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
.encoding-control { display: inline-flex; align-items: center; gap: 5px; color: var(--muted); font-size: 12px; }
.encoding-control select { height: 26px; padding: 0 24px 0 7px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text); }
.line-count, .stream-health { color: var(--muted); font-size: 12px; }
.btn-clear { background: none; border: 1px solid var(--border); border-radius: 4px; color: var(--muted); cursor: pointer; padding: 2px 8px; }
.btn-chart-toggle { display: inline-flex; align-items: center; gap: 5px; height: 26px; padding: 0 8px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: inherit; cursor: pointer; }
.rtt-format-note { display: flex; align-items: center; gap: 6px; min-height: 24px; color: var(--muted); font-size: 12px; }
.rtt-format-note code { color: var(--text); font-family: var(--font-mono); }
.rtt-chart-shell { position: relative; flex: 0 0 226px; min-height: 226px; }
.rtt-numeric-chart { display: block; width: 100%; height: 220px; border: 1px solid var(--border); border-radius: var(--radius); background: #10151d; cursor: grab; }
.rtt-numeric-chart:active { cursor: grabbing; }
.rtt-chart-hint { position: absolute; top: 7px; right: 10px; pointer-events: none; color: #78869a; font-size: 11px; }
.rtt-view-log { flex: 1 1 auto; min-height: 160px; margin-top: 8px; border: 1px solid var(--border); border-radius: var(--radius); }
@media (max-width: 720px) {
  .rtt-address-row { grid-template-columns: auto minmax(0, 1fr) auto; }
  .address-error, .address-source { grid-column: 1 / -1; }
}
</style>
