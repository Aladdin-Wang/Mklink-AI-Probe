<template>
  <div class="serial-assistant">
    <div class="serial-config-row">
      <label>
        <span>{{ tr('端口', 'Port') }}</span>
        <select v-model="portName" :disabled="running || starting || stopping">
          <option v-for="port in ports" :key="port.device" :value="port.device">
            {{ port.device }}{{ port.description ? ` · ${port.description}` : '' }}
          </option>
        </select>
      </label>
      <button
        type="button" class="icon-action" :title="tr('刷新串口', 'Refresh ports')"
        :aria-label="tr('刷新串口', 'Refresh ports')" :disabled="running || refreshingPorts"
        @click="refreshPorts"
      ><RefreshCw :size="15" :class="{ spinning: refreshingPorts }" /></button>
      <label>
        <span>{{ tr('波特率', 'Baud Rate') }}</span>
        <select v-model="baudrate" :disabled="running || starting || stopping">
          <option v-for="rate in baudrates" :key="rate" :value="rate">{{ rate }}</option>
        </select>
      </label>
      <label>
        <span>{{ tr('数据位', 'Data Bits') }}</span>
        <select v-model="databits" :disabled="running || starting || stopping">
          <option :value="8">8</option><option :value="7">7</option>
        </select>
      </label>
      <label>
        <span>{{ tr('停止位', 'Stop Bits') }}</span>
        <select v-model="stopbits" :disabled="running || starting || stopping">
          <option :value="1">1</option><option :value="2">2</option>
        </select>
      </label>
      <label>
        <span>{{ tr('校验', 'Parity') }}</span>
        <select v-model="parity" :disabled="running || starting || stopping">
          <option value="N">{{ tr('无', 'None') }}</option>
          <option value="E">{{ tr('偶', 'Even') }}</option>
          <option value="O">{{ tr('奇', 'Odd') }}</option>
        </select>
      </label>
      <button
        v-if="!running" type="button" class="btn btn-primary" :disabled="starting || !portName"
        @click="doStart"
      >{{ starting ? tr('启动中', 'Starting') : tr('打开串口', 'Open Port') }}</button>
      <button v-else type="button" class="btn btn-danger" :disabled="stopping" @click="doStop">
        {{ stopping ? tr('停止中', 'Stopping') : tr('关闭串口', 'Close Port') }}
      </button>
    </div>
    <SetupHint
      v-if="portsLoaded && !ports.length && !running"
      kind="info"
      :message="tr('未检测到可用串口。串口助手可独立于 MKLink 设备使用。', 'No serial ports detected. Serial Assistant works independently of the MKLink device.')"
      :primary-label="tr('刷新串口', 'Refresh Ports')"
      :busy="refreshingPorts"
      @primary="refreshPorts"
    />

    <div class="serial-toolbar">
      <div class="view-mode-switch" role="group" :aria-label="tr('显示模式', 'Display mode')">
        <button
          data-testid="serial-log-mode" type="button" :class="{ active: viewMode === 'log' }"
          :aria-pressed="viewMode === 'log'" @click="setViewMode('log')"
        ><ScrollText :size="14" /><span>{{ tr('日志', 'Log') }}</span></button>
        <button
          data-testid="serial-terminal-mode" type="button" :class="{ active: viewMode === 'terminal' }"
          :aria-pressed="viewMode === 'terminal'" @click="setViewMode('terminal')"
        ><SquareTerminal :size="14" /><span>{{ tr('终端', 'Terminal') }}</span></button>
      </div>
      <div class="serial-metrics">
        <span>RX {{ stats.rx_count }} / {{ stats.rx_bytes }} B</span>
        <span>TX {{ stats.tx_count }} / {{ stats.tx_bytes }} B</span>
        <span>{{ stats.bytes_per_sec }} B/s</span>
        <span :class="{ 'status-error': currentPortStatus.startsWith('error:') }">
          {{ tr('端口', 'Port') }} {{ portName || '--' }} · {{ localizedPortStatus }}
        </span>
      </div>
      <span v-if="runtimeError" class="runtime-error" role="alert">{{ runtimeError }}</span>
      <button
        type="button" class="icon-action clear-action"
        :title="viewMode === 'terminal' ? tr('清除终端', 'Clear terminal') : tr('清除日志', 'Clear log')"
        :aria-label="viewMode === 'terminal' ? tr('清除终端', 'Clear terminal') : tr('清除日志', 'Clear log')"
        @click="clearVisibleOutput"
      ><Trash2 :size="15" /></button>
    </div>

    <div v-show="viewMode === 'log'" ref="logEl" class="serial-log">
      <div v-if="!events.length" class="empty-output">{{ tr('暂无串口数据', 'No serial data') }}</div>
      <div
        v-for="(event, index) in events" :key="index"
        class="serial-line" :class="event.direction === 'TX' ? 'tx' : 'rx'"
      >
        <span class="timestamp">{{ event.timestamp }}</span>
        <span class="direction" :class="event.direction">{{ event.direction }}</span>
        <span class="hex">{{ event.raw_hex }}</span>
        <span v-if="event.ascii" class="ascii">{{ visibleAscii(event.ascii) }}</span>
      </div>
    </div>
    <div v-show="viewMode === 'terminal'" class="serial-terminal-shell">
      <RttTerminalPanel
        ref="terminalPanel" :input-enabled="transmitEnabled"
        :aria-label="tr('串口终端', 'Serial terminal')" @input="queueTerminalInput"
      />
    </div>

    <RttTransmitBar
      id-prefix="serial" :enabled="transmitEnabled" :settings="transmitSettings"
      :send="sendSerial" @settings-change="persistTransmitSettings"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { RefreshCw, ScrollText, SquareTerminal, Trash2 } from '@lucide/vue'
import { useMklinkApi } from '../../composables/useMklinkApi'
import { useToast } from '../../composables/useToast'
import { tr } from '../../composables/useLanguage'
import type { DesktopSettings } from '../../lib/desktopSettings'
import { toHexPayload } from '../../lib/rttTransmit'
import {
  loadSerialAssistantSettings,
  saveSerialAssistantSettings,
  type SerialAssistantSettings,
} from '../../lib/serialAssistantSettings'
import type { PortInfo, SerialEvent } from '../../types/mklink'
import RttTerminalPanel from './RttTerminalPanel.vue'
import RttTransmitBar from './RttTransmitBar.vue'
import SetupHint from './SetupHint.vue'
import { API_BASE } from '../../lib/runtimeEndpoint'

interface SerialStatus {
  running?: boolean
  ports?: Record<string, string>
  config?: Array<Record<string, unknown>>
  stats?: typeof stats.value
}

const baudrates = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
const toast = useToast()
const { listPorts: fetchPorts } = useMklinkApi()
const ports = ref<PortInfo[]>([])
const portName = ref('')
const baudrate = ref(115200)
const databits = ref(8)
const stopbits = ref(1)
const parity = ref('N')
const running = ref(false)
const starting = ref(false)
const stopping = ref(false)
const refreshingPorts = ref(false)
const portsLoaded = ref(false)
const events = ref<SerialEvent[]>([])
const stats = ref({ rx_count: 0, tx_count: 0, rx_bytes: 0, tx_bytes: 0, bytes_per_sec: 0 })
const portStatuses = ref<Record<string, string>>({})
const runtimeError = ref('')
const viewMode = ref<'log' | 'terminal'>('terminal')
const logEl = ref<HTMLElement | null>(null)
const terminalPanel = ref<InstanceType<typeof RttTerminalPanel> | null>(null)
const serialSettings = ref<SerialAssistantSettings>(loadSerialAssistantSettings(localStorage))
const maxEvents = 5000
const terminalEncoder = new TextEncoder()
let terminalDecoder = new TextDecoder()
let eventSource: EventSource | null = null
let statusTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false
let terminalInput = ''
let terminalInputTimer: ReturnType<typeof setTimeout> | null = null
let terminalSendChain = Promise.resolve()
let reportedPortError = ''

const currentPortStatus = computed(() => portStatuses.value[portName.value] || (running.value ? 'opening' : 'closed'))
const localizedPortStatus = computed(() => {
  const status = currentPortStatus.value
  if (status === 'open') return tr('已打开', 'Open')
  if (status === 'opening' || status === 'closed' && running.value) return tr('打开中', 'Opening')
  if (status === 'closed') return tr('已关闭', 'Closed')
  if (status === 'error: port is busy or unavailable') return tr('端口被占用或不可用', 'Port is busy or unavailable')
  return status
})
const transmitEnabled = computed(() => running.value && currentPortStatus.value === 'open')
const transmitSettings = computed<DesktopSettings>(() => ({
  version: 1,
  symbolPath: '',
  mapPath: '',
  rttAddress: '',
  rttEncoding: 'utf-8',
  transmitMode: serialSettings.value.transmitMode,
  lineEnding: serialSettings.value.lineEnding,
  sendHistory: serialSettings.value.sendHistory.map(entry => ({ ...entry })),
}))

function errorMessage(payload: unknown, fallback: string): string {
  if (typeof payload === 'string' && payload) return payload
  if (typeof payload === 'object' && payload !== null) {
    const detail = (payload as Record<string, unknown>).detail
    if (typeof detail === 'string') return detail
    if (typeof detail === 'object' && detail !== null) {
      const conflict = (detail as Record<string, unknown>).conflict
      if (typeof conflict === 'string') return `${fallback}: ${conflict}`
    }
  }
  return fallback
}

async function requestJson(path: string, init?: RequestInit): Promise<any> {
  const response = await fetch(`${API_BASE}${path}`, init)
  let payload: unknown = null
  try { payload = await response.json() } catch { /* empty response */ }
  if (!response.ok) throw new Error(errorMessage(payload, `${response.status} ${response.statusText}`))
  return payload
}

async function refreshPorts(): Promise<void> {
  if (refreshingPorts.value) return
  refreshingPorts.value = true
  try {
    ports.value = await fetchPorts()
    if (!portName.value || !ports.value.some(port => port.device === portName.value)) {
      portName.value = ports.value[0]?.device || ''
    }
  } catch (caught) {
    toast.error(caught instanceof Error ? caught.message : String(caught))
  } finally {
    refreshingPorts.value = false
    portsLoaded.value = true
  }
}

function applyStatus(status: SerialStatus): void {
  running.value = status.running === true
  if (status.stats) stats.value = status.stats
  portStatuses.value = status.ports || {}
  const config = status.config?.[0]
  if (running.value && config) {
    if (typeof config.port === 'string') portName.value = config.port
    if (typeof config.baudrate === 'number') baudrate.value = config.baudrate
    if (typeof config.databits === 'number') databits.value = config.databits
    if (typeof config.stopbits === 'number') stopbits.value = config.stopbits
    if (typeof config.parity === 'string') parity.value = config.parity
  }
  const portError = Object.values(portStatuses.value).find(value => value.startsWith('error:')) || ''
  if (portError && portError !== reportedPortError) {
    reportedPortError = portError
    toast.error(tr('串口打开失败：', 'Failed to open serial port: ') + (
      portError === 'error: port is busy or unavailable'
        ? tr('端口被占用或不可用', 'port is busy or unavailable')
        : portError.replace(/^error:\s*/, '')
    ))
  } else if (!portError) {
    reportedPortError = ''
  }
  if (running.value) connectSSE()
  else closeSSE()
}

async function refreshStatus(): Promise<void> {
  try {
    applyStatus(await requestJson('/api/dash/serial/status'))
  } catch { /* retry on the next low-rate poll */ }
}

async function pollStatus(): Promise<void> {
  await refreshStatus()
  if (!disposed) statusTimer = setTimeout(pollStatus, 1000)
}

async function doStart(): Promise<void> {
  if (!portName.value || starting.value) return
  starting.value = true
  runtimeError.value = ''
  try {
    const result = await requestJson('/api/dash/serial/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ports: [{
          port: portName.value,
          baudrate: baudrate.value,
          databits: databits.value,
          stopbits: stopbits.value,
          parity: parity.value,
        }],
      }),
    })
    if (result?.status !== 'already_running') {
      events.value = []
      terminalDecoder = new TextDecoder()
      terminalPanel.value?.clear()
      stats.value = { rx_count: 0, tx_count: 0, rx_bytes: 0, tx_bytes: 0, bytes_per_sec: 0 }
    }
    running.value = true
    portStatuses.value = { [portName.value]: 'opening' }
    connectSSE()
    await refreshStatus()
    toast.success(tr('串口助手已启动', 'Serial Assistant started'))
  } catch (caught) {
    runtimeError.value = caught instanceof Error ? caught.message : String(caught)
    toast.error(tr('启动失败：', 'Start failed: ') + runtimeError.value)
  } finally {
    starting.value = false
  }
}

async function doStop(): Promise<void> {
  if (!running.value || stopping.value) return
  stopping.value = true
  runtimeError.value = ''
  try {
    await requestJson('/api/dash/serial/stop', { method: 'POST' })
    running.value = false
    portStatuses.value = {}
    closeSSE()
    toast.info(tr('串口助手已停止', 'Serial Assistant stopped'))
  } catch (caught) {
    runtimeError.value = caught instanceof Error ? caught.message : String(caught)
    toast.error(tr('停止失败：', 'Stop failed: ') + runtimeError.value)
  } finally {
    stopping.value = false
  }
}

function connectSSE(): void {
  if (!running.value || eventSource) return
  const source = new EventSource(`${API_BASE}/api/dash/serial/stream`)
  eventSource = source
  source.onmessage = event => {
    try {
      const data = JSON.parse(event.data)
      if (data.event === 'terminal') {
        if (data.direction === 'RX' && typeof data.data_base64 === 'string') {
          const binary = atob(data.data_base64)
          const bytes = Uint8Array.from(binary, character => character.charCodeAt(0))
          const text = terminalDecoder.decode(bytes, { stream: true })
          if (text) terminalPanel.value?.write(text)
        }
      } else if (data.event === 'data') {
        const shouldFollow = !logEl.value
          || logEl.value.scrollHeight - logEl.value.scrollTop - logEl.value.clientHeight < 32
        events.value.push(data)
        if (events.value.length > maxEvents) events.value = events.value.slice(-maxEvents)
        if (shouldFollow) void nextTick(() => {
          if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
        })
      } else if (data.event === 'status') {
        applyStatus(data)
      } else if (data.event === 'stopped') {
        running.value = false
        portStatuses.value = {}
        closeSSE()
      }
    } catch { /* ignore malformed stream events */ }
  }
  source.onerror = () => {
    if (eventSource === source) {
      source.close()
      eventSource = null
    }
  }
}

function closeSSE(): void {
  eventSource?.close()
  eventSource = null
}

async function sendSerial(payload: Uint8Array): Promise<void> {
  if (!transmitEnabled.value) throw new Error(tr('串口尚未打开', 'Serial port is not open'))
  await requestJson('/api/dash/serial/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ port: portName.value, data: toHexPayload(payload), hex: true }),
  })
}

function persistTransmitSettings(next: DesktopSettings): void {
  serialSettings.value = saveSerialAssistantSettings(localStorage, {
    transmitMode: next.transmitMode,
    lineEnding: next.lineEnding,
    sendHistory: next.sendHistory,
  })
}

function setViewMode(mode: 'log' | 'terminal'): void {
  viewMode.value = mode
  if (mode === 'terminal') void nextTick(() => terminalPanel.value?.activate())
}

function queueTerminalInput(data: string): void {
  if (!transmitEnabled.value || !data) return
  terminalInput += data
  if (terminalInputTimer === null) terminalInputTimer = setTimeout(flushTerminalInput, 8)
}

function flushTerminalInput(): void {
  terminalInputTimer = null
  if (!terminalInput) return
  const payload = terminalEncoder.encode(terminalInput)
  terminalInput = ''
  terminalSendChain = terminalSendChain
    .then(() => sendSerial(payload))
    .then(() => { runtimeError.value = '' })
    .catch(caught => { runtimeError.value = caught instanceof Error ? caught.message : String(caught) })
}

function clearVisibleOutput(): void {
  if (viewMode.value === 'terminal') terminalPanel.value?.clear()
  else events.value = []
}

function visibleAscii(value: string): string {
  return value.replace(/\r/g, '\\r').replace(/\n/g, '\\n')
}

onMounted(async () => {
  await refreshPorts()
  await refreshStatus()
  void pollStatus()
})

onUnmounted(() => {
  disposed = true
  closeSSE()
  if (statusTimer !== null) clearTimeout(statusTimer)
  if (terminalInputTimer !== null) clearTimeout(terminalInputTimer)
  terminalInput = ''
})
</script>

<style scoped>
.serial-assistant { display: flex; flex: 1 1 auto; min-width: 0; min-height: 0; flex-direction: column; }
.serial-config-row { display: flex; flex-wrap: wrap; align-items: end; gap: 7px; }
.serial-config-row label { display: grid; gap: 3px; color: var(--muted); font-size: 11px; }
.serial-config-row select { height: 30px; min-width: 64px; max-width: 220px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: inherit; }
.serial-config-row label:first-child select { width: 180px; }
.serial-toolbar { display: flex; min-width: 0; align-items: center; gap: 10px; margin-top: 8px; }
.view-mode-switch { display: inline-flex; flex: 0 0 auto; overflow: hidden; border: 1px solid var(--border); border-radius: 4px; }
.view-mode-switch button { display: inline-flex; height: 26px; align-items: center; gap: 5px; padding: 0 8px; border: 0; background: var(--surface); color: var(--muted); cursor: pointer; }
.view-mode-switch button + button { border-left: 1px solid var(--border); }
.view-mode-switch button.active { background: var(--accent); color: #fff; }
.serial-metrics { display: flex; min-width: 0; flex: 1 1 auto; flex-wrap: wrap; gap: 0; color: var(--muted); font-family: var(--font-mono); font-size: 11px; }
.serial-metrics span + span::before { margin: 0 6px; color: var(--dim); content: '\00b7'; }
.runtime-error, .status-error { color: var(--danger); }
.runtime-error { min-width: 0; overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.icon-action { display: inline-grid; width: 30px; height: 30px; place-items: center; padding: 0; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--muted); cursor: pointer; }
.clear-action { width: 26px; height: 26px; margin-left: auto; }
.icon-action:hover { border-color: var(--accent); color: var(--accent); }
.spinning { animation: spin 0.8s linear infinite; }
.serial-log { flex: 1 1 auto; min-height: 260px; margin-top: 8px; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius); background: #10151d; padding: 8px; font-family: var(--font-mono); font-size: 12px; line-height: 1.55; }
.serial-line { display: grid; grid-template-columns: 92px 26px minmax(160px, auto) minmax(120px, 1fr); gap: 8px; align-items: baseline; }
.serial-line.rx { color: var(--success); }
.serial-line.tx { color: var(--warn); }
.timestamp { color: var(--dim); }
.direction { font-weight: 700; }
.direction.RX { color: var(--success); }
.direction.TX { color: var(--warn); }
.hex { color: var(--info); overflow-wrap: anywhere; }
.ascii { color: var(--muted); overflow-wrap: anywhere; white-space: pre-wrap; }
.empty-output { display: grid; min-height: 100%; place-items: center; color: #697586; }
.serial-terminal-shell { display: flex; flex: 1 1 auto; min-height: 260px; overflow: hidden; }
.serial-terminal-shell :deep(.rtt-terminal-panel) { width: 100%; }
.serial-assistant :deep(.rtt-transmit-wrapper) { margin-top: 8px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 768px) {
  .serial-config-row label:first-child { flex: 1 1 180px; }
  .serial-config-row label:first-child select { width: 100%; max-width: none; }
  .serial-toolbar { align-items: flex-start; flex-wrap: wrap; }
  .serial-metrics { order: 3; flex-basis: 100%; }
  .serial-line { grid-template-columns: 78px 24px minmax(100px, 1fr); }
  .serial-line .ascii { grid-column: 3; }
}
</style>
