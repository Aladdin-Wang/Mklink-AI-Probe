<template>
  <div class="rtt-view-tab">
    <SetupHint
      v-if="!deviceConnected"
      kind="device"
      :message="tr('RTT 实时采集需要连接 MKLink 设备。', 'Live RTT capture requires an MKLink device connection.')"
      :primary-label="tr('连接设备', 'Connect Device')"
      :secondary-label="!hasAddressFileSource ? tr('加载 AXF / ELF', 'Load AXF / ELF') : ''"
      :busy="connecting || loadingSymbols"
      @primary="quickConnect"
      @secondary="loadSymbolFile"
    />
      <div class="rtt-address-row">
        <label for="rtt-address">{{ tr('RTT 地址', 'RTT Address') }}</label>
        <input
          id="rtt-address" v-model="rttAddress" data-testid="rtt-address"
          type="text" spellcheck="false" placeholder="0x20000000" @input="onAddressInput"
        >
        <button data-testid="rtt-search" type="button" class="btn-search" @click="searchRttAddress">
          <Search :size="15" />
          <span>{{ searching ? tr('搜索中', 'Searching') : tr('自动搜索', 'Auto Search') }}</span>
        </button>
        <span v-if="addressError" class="address-error" role="alert">{{ addressError }}</span>
        <span v-else-if="addressSource" class="address-source" :title="addressSource">
          {{ tr('来源:', 'Source:') }} {{ addressSource }}
        </span>
      </div>
      <SetupHint
        v-if="deviceConnected && !hasAddressFileSource"
        kind="symbols"
        :message="tr('自动搜索 RTT 地址时，加载 AXF / ELF 可直接定位 _SEGGER_RTT。', 'Load AXF / ELF so Auto Search can locate _SEGGER_RTT directly.')"
        :primary-label="tr('加载 AXF / ELF', 'Load AXF / ELF')"
        :busy="loadingSymbols"
        @primary="loadSymbolFile"
      />
      <p v-if="sourceChangeNotice" data-testid="rtt-source-notice" role="status">{{ sourceChangeNotice }}</p>
      <div class="rtt-address-row">
        <label for="rtt-channels">{{ tr('采集通道', 'Capture channels') }}</label>
        <input id="rtt-channels" v-model="captureChannels" :disabled="effectiveRunning || starting" placeholder="0,1" size="12">
        <span>{{ tr('逗号分隔 0–7；每个通道均支持日志、终端和曲线，多通道需要新版固件。', 'Comma-separated 0–7; every channel supports logs, terminal and charts. Multiple channels require new firmware.') }}</span>
        <span v-if="multiplex">{{ tr('多路复用 · 可与 SuperWatch 并行', 'Multiplex · concurrent with SuperWatch') }}</span>
      </div>
      <ControlToolbar
        :state="toolbarState" :error="runtimeError || actionError || dash.error.value"
        :device-connected="deviceConnected && !searching"
        @start="onStart" @stop="onStop" :hide-pause="true"
      />
      <div class="rtt-channel-grid" :class="{ multiple: activeChannels.length > 1 }">
        <RttChannelPanel v-for="ch in activeChannels" :key="ch" :channel="ch"
          :running="statusRunning && !runtimeError" :session="captureSession" :channel-status="channelStatus[String(ch)]"
          :send-enabled="!stopping && !runtimeError && downBuffers.some(b => b.channel === ch && b.active)" />
      </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Search } from '@lucide/vue'
import { useDashboard } from '../../composables/useDashboard'
import { useMklinkApi } from '../../composables/useMklinkApi'
import { useDashboardSetup } from '../../composables/useDashboardSetup'
import { DESKTOP_SETTINGS_CHANGED_EVENT, isSameFileSourcePath, isSymbolFilePath, loadDesktopSettings, saveDesktopSettings, type DesktopSettings } from '../../lib/desktopSettings'
import { cancelRttAddressRefresh } from '../../lib/rttSymbolAddress'
import ControlToolbar from './ControlToolbar.vue'
import SetupHint from './SetupHint.vue'
import RttChannelPanel from './RttChannelPanel.vue'
import { tr } from '../../composables/useLanguage'
import { API_BASE } from '../../lib/runtimeEndpoint'
const props = defineProps<{ deviceConnected: boolean }>()
const dash = useDashboard('rtt')
const { findRtt } = useMklinkApi()
const {
  connecting,
  loadingSymbols,
  quickConnect,
  loadSymbolFile,
} = useDashboardSetup()
const desktopStorage = localStorage
const settings = ref<DesktopSettings>(loadDesktopSettings(desktopStorage))
const hasAddressFileSource = computed(() => isSymbolFilePath(settings.value.symbolPath))
const rttAddress = ref(settings.value.rttAddress)
const addressError = ref('')
const addressSource = ref('')
const searching = ref(false)
const starting = ref(false)
const stopping = ref(false)
const statusRunning = ref(false)
const statusKnown = ref(false)
const downBuffers = ref<Array<{ channel?: number, active?: boolean }>>([])
const runtimeError = ref<string | null>(null)
const sourceChangeNotice = ref<string | null>(null)
const actionError = ref<string | null>(null)
const captureChannels = ref('0')
const activeChannels = ref<number[]>([0])
const captureSession = ref<string>()
const channelStatus = ref<Record<string, { numeric_channels?: string[], encoding?: string }>>({})
const multiplex = ref(false)
// Zero lets the host bound the default scan to the actual RAM map.
const RTT_SEARCH_SIZE = 0
const effectiveRunning = computed(() => (
  statusKnown.value ? statusRunning.value : dash.state.value === 'running'
))
const toolbarState = computed(() => (
  runtimeError.value ? 'error' :
    starting.value ? 'starting' :
        effectiveRunning.value ? 'running' :
          statusKnown.value ? 'idle' : dash.state.value
))
let statusTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false
let searchGeneration = 0
function persistSettings(next: DesktopSettings): void {
  settings.value = saveDesktopSettings(desktopStorage, next)
}

function syncRttAddressFromSettings(): void {
  const latest = loadDesktopSettings(desktopStorage)
  const sourceChanged = !sameRttSearchSource(settings.value.symbolPath, latest.symbolPath)
  const addressChanged = latest.rttAddress !== rttAddress.value
  if (sourceChanged || addressChanged) {
    searchGeneration++
    searching.value = false
  }
  settings.value = latest
  if (addressChanged) {
    rttAddress.value = latest.rttAddress
    addressError.value = ''
    addressSource.value = ''
  }
}

function sameRttSearchSource(left: string | undefined, right: string | undefined): boolean {
  const leftPath = left?.trim() || ''
  const rightPath = right?.trim() || ''
  if (!leftPath || !rightPath) return leftPath === rightPath
  return isSameFileSourcePath(leftPath, rightPath)
}

function isRttAddress(value: string): boolean {
  return /^0x[0-9a-f]{1,8}$/i.test(value)
}

function onAddressInput(): void {
  cancelRttAddressRefresh(desktopStorage)
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
  cancelRttAddressRefresh(desktopStorage)
  const generation = ++searchGeneration
  searching.value = true
  addressError.value = ''
  const initialSettings = loadDesktopSettings(desktopStorage)
  settings.value = initialSettings
  const initialAddress = initialSettings.rttAddress
  const symbolPath = initialSettings.symbolPath.trim()
  const source = symbolPath || undefined
  try {
    const result = await findRtt(source)
    if (disposed || generation !== searchGeneration) return
    const latest = loadDesktopSettings(desktopStorage)
    if (
      !sameRttSearchSource(symbolPath, latest.symbolPath)
      || latest.rttAddress !== initialAddress
    ) return
    if (!result.addr || !isRttAddress(result.addr)) {
      throw new Error(result.details?.join(tr('；', '; ')) || result.warnings?.join(tr('；', '; ')) || tr('未找到 RTT 地址', 'RTT address not found'))
    }
    rttAddress.value = result.addr
    addressSource.value = result.source || (source ? tr('所选文件', 'Selected file') : tr('工程自动检测', 'Project auto-detection'))
    persistSettings({ ...latest, rttAddress: result.addr })
  } catch (caught) {
    if (!disposed && generation === searchGeneration) {
      addressError.value = caught instanceof Error ? caught.message : String(caught)
    }
  } finally {
    if (!disposed && generation === searchGeneration) searching.value = false
  }
}

let lastSourceChange = 0
async function refreshStatus(): Promise<Record<string, any> | null> {
  try {
    const response = await fetch(`${API_BASE}/api/dash/rtt/status`)
    if (response.ok) {
      const status = await response.json()
      const changed = status.file_source_change
      if (changed && changed.sequence !== lastSourceChange) {
        lastSourceChange = changed.sequence
        const message = changed.error || changed.message || tr('符号文件已变化，请重新检测地址', 'Symbol file changed. Detect the address again.')
        sourceChangeNotice.value = message
        if (!changed.pending) {
          rttAddress.value = changed.rtt_addr && isRttAddress(changed.rtt_addr) ? changed.rtt_addr : ''
          persistSettings({ ...settings.value, rttAddress: rttAddress.value })
        }
      }
      statusKnown.value = true
      statusRunning.value = status.running === true
      captureSession.value = status.session
      channelStatus.value = status.channel_status || {}
      multiplex.value = status.transport === 'cdc-mux'
      activeChannels.value = Array.isArray(status.channels) && status.channels.length ? status.channels : [0]
      if (statusRunning.value && status.control_block_addr) captureChannels.value = activeChannels.value.join(',')
      downBuffers.value = Array.isArray(status.down_buffers) ? status.down_buffers : []
      if (typeof status.error === 'string' && status.error) runtimeError.value = status.error
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
    runtimeError.value = tr('RTT 启动超时，请检查地址后重试', 'RTT startup timed out. Check the address and retry.')
    const stopped = await stopTimedOutRtt()
    statusRunning.value = false
    downBuffers.value = []
    if (!stopped) {
      runtimeError.value = tr('RTT 启动超时，后台仍在停止，请点击停止重试', 'RTT startup timed out while the backend is still stopping. Click Stop and retry.')
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
  if (!props.deviceConnected) {
    runtimeError.value = tr('请先连接 MKLink 设备', 'Connect the MKLink device first')
    return
  }
  const address = rttAddress.value.trim()
  if (!isRttAddress(address)) {
    addressError.value = tr('请输入有效的 RTT 地址，例如 0x20001A40', 'Enter a valid RTT address, for example 0x20001A40')
    return
  }
  persistSettings({ ...settings.value, rttAddress: address })
  starting.value = true
  try {
    stopping.value = false
    runtimeError.value = null
    actionError.value = null
    sourceChangeNotice.value = null
    const channels = captureChannels.value.split(',').map(value => /^[0-7]$/.test(value.trim()) ? Number(value.trim()) : NaN)
    if (channels.length > 8 || new Set(channels).size !== channels.length
        || channels.some(ch => !Number.isInteger(ch) || ch < 0 || ch > 7)) {
      actionError.value = tr('通道必须为不重复的 0–7', 'Channels must be unique 0–7')
      return
    }
    const started = await dash.start({
      ...(channels.length > 1 ? { channels } : {}),
      ...(channels[0] !== 0 ? { channel: channels[0] } : {}),
      addr: address,
      mode: 0,
      search_size: RTT_SEARCH_SIZE,
      encoding: settings.value.rttEncoding,
    })
    if (!started || disposed) return
    await waitForRttReady()
  } finally {
    starting.value = false
  }
}

async function onStop(): Promise<void> {
  if (stopping.value) return
  stopping.value = true
  actionError.value = null
  try {
    const stopped = await dash.stop()
    if (stopped) {
        statusRunning.value = false
      downBuffers.value = []
        runtimeError.value = null
    } else {
      // A shared subscriber can refuse stop while the producer remains healthy.
      // Preserve this window's stream and render state until stop is accepted.
      actionError.value = dash.error.value || tr('RTT 停止未完成，请再次停止', 'RTT did not stop completely. Stop it again.')
    }
  } finally {
    stopping.value = false
  }
}

onMounted(() => {
  window.addEventListener(DESKTOP_SETTINGS_CHANGED_EVENT, syncRttAddressFromSettings)
  void pollStatus()
})
onUnmounted(() => {
  disposed = true
  searchGeneration++
  if (statusTimer !== null) clearTimeout(statusTimer)
  window.removeEventListener(DESKTOP_SETTINGS_CHANGED_EVENT, syncRttAddressFromSettings)
})
</script>

<style scoped>
.rtt-channel-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; flex: 1; min-height: 0; overflow: auto; padding-top: 8px; }
.rtt-channel-grid.multiple { grid-template-columns: repeat(auto-fit, minmax(min(480px, 100%), 1fr)); align-content: start; }
.rtt-view-tab { display: flex; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; }
.alert-warn { color: var(--warn); padding: 8px; border: 1px solid var(--warn); border-radius: 4px; }
.rtt-address-row { display: grid; grid-template-columns: auto minmax(180px, 320px) auto minmax(0, 1fr); align-items: center; gap: 10px; min-height: 38px; padding: 2px 0 7px; border-bottom: 1px solid var(--border-subtle); }
.rtt-address-row label { font-size: 12px; color: var(--muted); }
.rtt-address-row input { min-width: 0; height: 30px; padding: 0 8px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: inherit; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.btn-search { height: 30px; display: inline-flex; align-items: center; gap: 5px; padding: 0 9px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: inherit; cursor: pointer; }
.address-error { min-width: 0; color: var(--danger, #dc2626); font-size: 12px; overflow-wrap: anywhere; }
.address-source { min-width: 0; overflow: hidden; color: var(--muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }

@media (max-width: 720px) { .rtt-address-row { grid-template-columns: auto minmax(0, 1fr) auto; } .address-error, .address-source { grid-column: 1 / -1; } }
</style>
