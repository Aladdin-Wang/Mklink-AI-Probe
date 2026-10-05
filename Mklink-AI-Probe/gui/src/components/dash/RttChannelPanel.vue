<template>
  <section class="rtt-channel-panel" :data-channel="channel">
    <header><h3>RTT {{ channel }}</h3>
      <button type="button" data-testid="channel-pause" @click="renderPaused ? onResumeRender() : onPauseRender()">{{ renderPaused ? tr('继续显示', 'Resume display') : tr('暂停显示', 'Pause display') }}</button>
      <button type="button" data-testid="channel-collapse" @click="collapsed = !collapsed">{{ collapsed ? tr('展开', 'Expand') : tr('收起', 'Collapse') }}</button>
    </header>
    <div v-show="!collapsed" class="channel-content">
    <p v-if="runtimeError" role="alert">{{ runtimeError }}</p>
      <div class="rtt-view-toolbar">
        <div class="rtt-primary-tools">
          <label class="encoding-control" :for="`rtt-encoding-${channel}`">
            <span>{{ tr('编码', 'Encoding') }}</span>
            <select
              :id="`rtt-encoding-${channel}`" v-model="rttEncoding" data-testid="rtt-encoding"
              :disabled="!running" @change="onEncodingChange"
            >
              <option value="utf-8">UTF-8</option>
              <option value="gb2312">GB2312</option>
              <option value="gbk">GBK</option>
              <option value="gb18030">GB18030</option>
              <option value="big5">Big5</option>
            </select>
          </label>
          <div class="view-mode-switch" role="group" :aria-label="tr('显示模式', 'Display mode')">
            <button
              data-testid="rtt-log-mode" type="button" :class="{ active: viewMode === 'log' }"
              :aria-pressed="viewMode === 'log'" @click="setViewMode('log')"
            >
              <ScrollText :size="14" aria-hidden="true" />
              <span>{{ tr('日志', 'Log') }}</span>
            </button>
            <button
              data-testid="rtt-terminal-mode" type="button" :class="{ active: viewMode === 'terminal' }"
              :aria-pressed="viewMode === 'terminal'" @click="setViewMode('terminal')"
            >
              <SquareTerminal :size="14" aria-hidden="true" />
              <span>{{ tr('终端', 'Terminal') }}</span>
            </button>
            <button data-testid="rtt-hex-mode" type="button" :class="{ active: viewMode === 'hex' }" @click="setViewMode('hex')">HEX</button>
          </div>
          <div class="stream-metrics" aria-label="RTT stream status">
            <span>{{ retainedCount }} {{ tr('行', 'lines') }}</span>
            <span>buffer {{ activeTelemetry?.bufferedSamples ?? 0 }}</span>
            <span>drops {{ activeTelemetry?.transportDroppedBatches ?? 0 }}/{{ activeTelemetry?.backendDroppedBatches ?? 0 }}</span>
          </div>
        </div>
        <div class="rtt-secondary-tools">
          <LogDisplayControls
            v-if="viewMode === 'log'" :id-prefix="`rtt-${channel}`"
            v-model:mode="logDisplayMode" v-model:show-timestamp="showLogTimestamp"
          />
          <div v-if="viewMode === 'log'" class="format-help">
            <button
              data-testid="rtt-format-help" type="button" class="icon-action"
              :title="tr('数据格式说明', 'Data format help')"
              :aria-label="tr('数据格式说明', 'Data format help')"
              :aria-expanded="formatHelpOpen"
              @click="formatHelpOpen = !formatHelpOpen"
            >
              <Info :size="15" aria-hidden="true" />
            </button>
            <div v-if="formatHelpOpen" class="format-help-popover" role="note">
              <strong>{{ tr('数据格式', 'Data format') }}</strong>
              <span>{{ tr('每行输出同一组数值，例如', 'Output one value set per line, for example') }}</span>
              <code>temp=25.3,speed=1200</code>
              <span>{{ tr('或', 'or') }}</span>
              <code>25.3,1200</code>
            </div>
          </div>
          <button
            v-if="viewMode === 'log'" data-testid="rtt-chart-toggle" type="button" class="btn-chart-toggle"
            :aria-pressed="chartEnabled" @click="toggleChart"
          >
            <EyeOff v-if="chartEnabled" :size="14" aria-hidden="true" />
            <Eye v-else :size="14" aria-hidden="true" />
            <span>{{ chartEnabled ? tr('关闭曲线', 'Hide Chart') : tr('打开曲线', 'Show Chart') }}</span>
          </button>
          <button
            v-if="viewMode === 'log'" data-testid="rtt-save-log" type="button"
            class="icon-action" :disabled="retainedCount === 0"
            :title="tr('保存日志', 'Save log')" :aria-label="tr('保存日志', 'Save log')"
            @click="saveLog"
          >
            <Download :size="15" aria-hidden="true" />
          </button>
          <button
            data-testid="rtt-clear-logs" class="btn-clear icon-action" type="button"
            :title="viewMode === 'terminal' ? tr('清除终端', 'Clear terminal') : tr('清除日志', 'Clear log')"
            :aria-label="viewMode === 'terminal' ? tr('清除终端', 'Clear terminal') : tr('清除日志', 'Clear log')"
            @click="clearVisibleOutput"
          >
            <Trash2 :size="15" aria-hidden="true" />
          </button>
        </div>
      </div>
      <div v-if="viewMode === 'log' && chartEnabled && hasChartData" class="rtt-chart-shell">
        <canvas
          ref="chart" class="rtt-numeric-chart"
          @wheel.prevent="onChartWheel" @mousedown="onChartMouseDown" @dblclick="resetChartViewport"
        />
        <div class="rtt-chart-hint">{{ tr('滚轮缩放坐标 · 左键拖动曲线 · 双击复位', 'Wheel to zoom axes · Left-drag to pan · Double-click to reset') }}</div>
      </div>
      <VirtualLogPanel
        v-show="viewMode === 'log'" ref="logPanel" class="rtt-view-log"
        :display-mode="logDisplayMode" :show-timestamp="showLogTimestamp"
      />
      <div v-show="viewMode === 'terminal'" class="rtt-terminal-shell">
        <RttTerminalPanel
          ref="terminalPanel" :input-enabled="transmitEnabled"
          @input="queueTerminalInput"
        />
      </div>
      <RttRawView ref="rawView" v-show="viewMode === 'hex'" :channel="channel" :running="running" :paused="renderPaused" />
      <RttTransmitBar :id-prefix="`rtt-channel-${channel}`"
        :enabled="transmitEnabled" :settings="settings" :send="sendRtt"
        @settings-change="persistSettings"
      />
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Download, Eye, EyeOff, Info, ScrollText, SquareTerminal, Trash2 } from '@lucide/vue'
import { useBinaryStream } from '../../composables/useBinaryStream'
import { useMklinkApi } from '../../composables/useMklinkApi'
import { loadDesktopSettings, type DesktopSettings, type RttEncoding } from '../../lib/desktopSettings'
import { RenderScheduler } from '../../lib/stream/renderScheduler'
import { saveBlobFile, timestampedLogName } from '../../lib/downloadTextFile'
import LogDisplayControls, { type LogDisplayMode } from './LogDisplayControls.vue'
import RttRawView from './RttRawView.vue'
import RttTransmitBar from './RttTransmitBar.vue'
import RttTerminalPanel from './RttTerminalPanel.vue'
import VirtualLogPanel, { type VirtualLogInput } from './VirtualLogPanel.vue'
import { language, tr } from '../../composables/useLanguage'
import { API_BASE } from '../../lib/runtimeEndpoint'
const props = defineProps<{ channel: number, running: boolean, sendEnabled: boolean, session?: string, channelStatus?: { numeric_channels?: string[], encoding?: string } }>()
const logBinary = useBinaryStream(`rtt-${props.channel}`, { capacity: 25000, channelCount: 1 })
const terminalBinary = useBinaryStream(`rtt-terminal-${props.channel}`, { capacity: 64 * 1024, channelCount: 1 })
const { writeRtt } = useMklinkApi()
const settings = ref<DesktopSettings>(loadDesktopSettings(localStorage))
const rttEncoding = ref<RttEncoding>(settings.value.rttEncoding)
const logPanel = ref<InstanceType<typeof VirtualLogPanel> | null>(null)
const terminalPanel = ref<InstanceType<typeof RttTerminalPanel> | null>(null)
const chart = ref<HTMLCanvasElement | null>(null)
const retainedCount = computed(() => logPanel.value?.retainedCount ?? 0)
const activeTelemetry = computed(() => viewMode.value === 'log' ? logBinary.telemetry.value : terminalBinary.telemetry.value)
const numericChannelCount = ref(0)
const numericChannelNames = ref<string[]>([])
const chartEnabled = ref(true)
const viewMode = ref<'log' | 'terminal' | 'hex'>('terminal')
const logDisplayMode = ref<LogDisplayMode>('text')
const showLogTimestamp = ref(false)
const formatHelpOpen = ref(false)
const hasChartData = ref(false)
const renderPaused = ref(false)
const collapsed = ref(false)
const runtimeError = ref<string | null>(null)
let pausedLines: VirtualLogInput[] = []
let pausedTerminal = ''
const rawView = ref<InstanceType<typeof RttRawView> | null>(null)
const transmitEnabled = computed(() => props.running && props.sendEnabled)
let requestId = 0
let latestEnvelope: NonNullable<typeof logBinary.envelope.value> | null = null
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
const terminalEncoder = new TextEncoder()
const logEncoder = new TextEncoder()
let terminalInput = ''
let terminalInputTimer: ReturnType<typeof setTimeout> | null = null
let terminalSendChain = Promise.resolve()


function persistSettings(next: DesktopSettings) { settings.value = next }
async function sendRtt(payload: Uint8Array): Promise<void> { await writeRtt(payload, props.channel) }
async function onEncodingChange() {
  try {
    const response = await fetch(`${API_BASE}/api/dash/rtt/encoding`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({channel: props.channel, encoding: rttEncoding.value}) })
    if (!response.ok) throw new Error((await response.json()).detail || 'RTT encoding failed')
    settings.value = { ...settings.value, rttEncoding: rttEncoding.value }
    runtimeError.value = null
  } catch (error) { runtimeError.value = String(error) }
}
const scheduler = new RenderScheduler(() => {
  if (viewMode.value !== 'log') return
  const canvas = chart.value
  if (!canvas || !chartEnabled.value || !hasChartData.value || numericChannelCount.value <= 0) return
  const telemetry = logBinary.telemetry.value
  if (!telemetry?.bufferedSamples) return
  const range = visibleRange ?? dataRange
  if (!range || !Number.isFinite(range.start) || !Number.isFinite(range.end)) return
  logBinary.requestVisibleRange(
    ++requestId, range.start, range.end,
    Math.max(1, (canvas.clientWidth || 640) - CHART_MARGIN.left - CHART_MARGIN.right),
  )
})

watch(() => logBinary.rttLines.value, batch => {
  if (!batch) return
  const lines = batch.lines.map(line => ({
    time: line.timestampNs, level: line.level, text: line.text,
    raw: logEncoder.encode(`${line.text}\n`),
  } satisfies VirtualLogInput))
  if (renderPaused.value) pausedLines = [...pausedLines, ...lines].slice(-5000)
  else logPanel.value?.append(lines)
})

watch(() => terminalBinary.rttTerminal.value, chunk => {
  if (!chunk) return
  if (renderPaused.value) pausedTerminal = (pausedTerminal + chunk.text).slice(-65536)
  else terminalPanel.value?.write(chunk.text)
})

watch(() => logBinary.waveformBatch.value, batch => {
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
  if (!renderPaused.value && chartEnabled.value && viewMode.value === 'log') {
    scheduler.invalidate('data')
  }
})

watch(() => logBinary.envelope.value, envelope => {
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
watch(language, () => scheduler.invalidate('resize'))

function drawEnvelope(envelope: NonNullable<typeof logBinary.envelope.value>): void {
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
  context.fillText(tr('时间', 'Time'), CHART_MARGIN.left + plotWidth / 2, height - 3)
  context.save()
  context.translate(12, CHART_MARGIN.top + plotHeight / 2)
  context.rotate(-Math.PI / 2)
  context.fillText(tr('数值', 'Value'), 0, 0)
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

function setViewMode(mode: 'log' | 'terminal' | 'hex'): void {
  if (viewMode.value === mode) return
  viewMode.value = mode
  formatHelpOpen.value = false
  if (mode === 'terminal') {
    scheduler.stop()
    void nextTick(() => terminalPanel.value?.activate())
  } else if (!renderPaused.value && chartEnabled.value) {
    scheduler.start()
    void nextTick(() => scheduler.invalidate('resize'))
  }
}

function queueTerminalInput(data: string): void {
  if (!transmitEnabled.value || !data) return
  terminalInput += data
  if (terminalInputTimer === null) {
    terminalInputTimer = setTimeout(flushTerminalInput, 8)
  }
}

function flushTerminalInput(): void {
  terminalInputTimer = null
  if (!terminalInput) return
  const payload = terminalEncoder.encode(terminalInput)
  terminalInput = ''
  terminalSendChain = terminalSendChain
    .then(() => sendRtt(payload))
    .then(() => { runtimeError.value = null })
    .catch(caught => {
      runtimeError.value = caught instanceof Error ? caught.message : String(caught)
    })
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

function attachBinary() { logBinary.start(); terminalBinary.start() }
function detachBinary() { logBinary.stop(); terminalBinary.stop() }
watch(() => props.running, running => { if (running) attachBinary(); else detachBinary() }, { immediate: true })
watch(() => props.channelStatus, status => {
  if (status?.numeric_channels?.length) { numericChannelNames.value = status.numeric_channels; numericChannelCount.value = status.numeric_channels.length }
  if (status?.encoding) rttEncoding.value = status.encoding as RttEncoding
}, { immediate: true })
watch(() => props.session, () => { clearAllOutputs(); resetChartData(); logBinary.reset(); terminalBinary.reset() })
function onPauseRender(): void {
  renderPaused.value = true
  requestId++
  scheduler.stop()
}

function onResumeRender(): void {
  logPanel.value?.append(pausedLines); pausedLines = []
  terminalPanel.value?.write(pausedTerminal); pausedTerminal = ''
  renderPaused.value = false
  if (!manualTimeline && dataRange) visibleRange = { ...dataRange }
  if (viewMode.value === 'log') {
    scheduler.start()
    scheduler.invalidate('data')
  }
}

function clearAllOutputs(): void {
  pausedLines = []; pausedTerminal = ''
  logPanel.value?.clear()
  terminalPanel.value?.clear()
}

function clearVisibleOutput(): void {
  if (viewMode.value === 'hex') rawView.value?.clear()
  else if (viewMode.value === 'terminal') { terminalPanel.value?.clear(); pausedTerminal = '' }
  else { logPanel.value?.clear(); pausedLines = [] }
}

function saveLog(): void {
  const raw = logPanel.value?.exportRaw() ?? new Uint8Array()
  if (raw.byteLength) {
    void saveBlobFile(
      timestampedLogName(`rtt-${props.channel}`),
      new Blob([new Uint8Array(raw)], { type: 'application/octet-stream' }),
    )
  }
}


onMounted(() => {
  window.addEventListener('mousemove', onChartMouseMove)
  window.addEventListener('mouseup', onChartMouseUp)
  scheduler.start()
})
onUnmounted(() => {
  if (terminalInputTimer !== null) clearTimeout(terminalInputTimer)
  terminalInput = ''
  window.removeEventListener('mousemove', onChartMouseMove)
  window.removeEventListener('mouseup', onChartMouseUp)
  resizeObserver?.disconnect()
  detachBinary()
  scheduler.dispose()
})
</script>
<style scoped>
.rtt-channel-panel { display: flex; flex-direction: column; height: 600px; min-width: 0; border: 1px solid var(--border); border-radius: var(--radius); padding: 10px; }
header { display: flex; align-items: center; gap: 8px; }
header h3 { flex: 1; margin: 0; font-size: 14px; }
header button { color: inherit; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; cursor: pointer; }
.channel-content { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.rtt-view-toolbar { flex-wrap: wrap; position: relative; display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 42px; padding: 7px 0; }
.rtt-primary-tools, .rtt-secondary-tools { display: flex; align-items: center; gap: 10px; min-width: 0; }
.rtt-primary-tools { flex: 1 1 auto; flex-wrap: wrap; }
.rtt-secondary-tools { flex: 0 0 auto; }
.rtt-view-toolbar :deep(.control-toolbar) { flex: 0 0 auto; gap: 6px; padding: 0; }
.encoding-control { display: inline-flex; align-items: center; gap: 5px; color: var(--muted); font-size: 12px; }
.encoding-control select { height: 26px; padding: 0 24px 0 7px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text); }
.view-mode-switch { display: inline-flex; height: 26px; overflow: hidden; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); }
.view-mode-switch button { display: inline-flex; align-items: center; gap: 4px; padding: 0 7px; border: 0; border-right: 1px solid var(--border); background: transparent; color: var(--muted); cursor: pointer; font: inherit; font-size: 11px; }
.view-mode-switch button:last-child { border-right: 0; }
.view-mode-switch button.active { background: var(--accent); color: #fff; }
.stream-metrics { display: inline-flex; align-items: center; min-width: 0; color: var(--muted); font-family: var(--font-mono); font-size: 11px; white-space: nowrap; }
.stream-metrics span + span::before { margin: 0 6px; color: var(--dim); content: '\00b7'; }
.format-help { position: relative; }
.icon-action { display: inline-grid; width: 26px; height: 26px; place-items: center; padding: 0; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--muted); cursor: pointer; }
.icon-action:hover { border-color: var(--accent); color: var(--accent); }
.format-help-popover { position: absolute; z-index: 20; top: calc(100% + 6px); right: 0; display: grid; grid-template-columns: auto auto; gap: 5px 8px; width: max-content; max-width: min(360px, calc(100vw - 48px)); padding: 10px 12px; border: 1px solid var(--border); border-radius: 5px; background: var(--surface); box-shadow: 0 8px 24px rgb(0 0 0 / 14%); color: var(--muted); font-size: 12px; }
.format-help-popover strong { grid-column: 1 / -1; color: var(--fg); }
.format-help-popover code { color: var(--fg); font-family: var(--font-mono); }
.btn-clear { flex: 0 0 auto; }
.btn-chart-toggle { display: inline-flex; align-items: center; gap: 5px; height: 26px; padding: 0 8px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: inherit; cursor: pointer; }
.rtt-chart-shell { position: relative; flex: 0 0 226px; min-height: 226px; }
.rtt-numeric-chart { display: block; width: 100%; height: 220px; border: 1px solid var(--border); border-radius: var(--radius); background: #10151d; cursor: grab; }
.rtt-numeric-chart:active { cursor: grabbing; }
.rtt-chart-hint { position: absolute; top: 7px; right: 10px; pointer-events: none; color: #78869a; font-size: 11px; }
.rtt-view-log { flex: 1 1 auto; min-height: 160px; margin-top: 8px; border: 1px solid var(--border); border-radius: var(--radius); }
.rtt-terminal-shell { display: flex; flex: 1 1 auto; min-height: 220px; overflow: hidden; }
.rtt-terminal-shell :deep(.rtt-terminal-panel) { width: 100%; }
@media (max-width: 720px) {
  .rtt-address-row { grid-template-columns: auto minmax(0, 1fr) auto; }
  .address-error, .address-source { grid-column: 1 / -1; }
  .rtt-view-toolbar { align-items: flex-start; flex-direction: column; gap: 6px; }
  .rtt-secondary-tools { align-self: flex-end; }
  .format-help-popover { right: -70px; }
}
</style>
