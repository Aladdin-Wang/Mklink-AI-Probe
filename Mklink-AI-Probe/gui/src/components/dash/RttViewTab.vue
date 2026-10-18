<template>
  <div class="rtt-view-tab" @dblclick="fitPanels">
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
      <div class="rtt-config-row">
        <label for="rtt-address">{{ tr('RTT 地址', 'RTT Address') }}</label>
        <input
          id="rtt-address" v-model="rttAddress" data-testid="rtt-address"
          type="text" spellcheck="false" placeholder="0x20000000" @input="onAddressInput"
        >
        <button data-testid="rtt-search" type="button" class="btn-search" :title="addressSource" @click="searchRttAddress">
          <Search :size="15" />
          <span>{{ searching ? tr('搜索中', 'Searching') : tr('自动搜索', 'Auto Search') }}</span>
        </button>
        <button v-if="sourcePending" data-testid="reload-sources" type="button" class="btn-search"
          :disabled="reloadingSources" :title="tr('板上固件就绪后重新加载', 'Reload when the target firmware is ready')"
          @click="reloadSources">{{ tr('重新加载', 'Reload') }}</button>
        <span v-if="addressError" class="address-error" role="alert">{{ addressError }}</span>
        <div class="rtt-channel-options" :aria-label="tr('显示通道', 'Visible channels')">
          <label v-for="ch in availableChannels" :key="ch.channel" :title="ch.name || `RTT ${ch.channel}`">
            <input type="checkbox" :data-testid="`rtt-channel-${ch.channel}`"
              :checked="!hiddenChannels.has(ch.channel)" @change="toggleChannel(ch.channel)">
            CH {{ ch.channel }}
          </label>
        </div>
        <ControlToolbar
          :state="toolbarState" :error="runtimeError || actionError || dash.error.value"
          :device-connected="deviceConnected && !searching"
          @start="onStart" @stop="onStop" :hide-pause="true"
        />
      </div>
      <div ref="channelGrid" class="rtt-channel-grid" :class="{ 'auto-fit': autoFit, multiple: activeChannels.filter(ch => !hiddenChannels.has(ch)).length > 1 }">
        <RttChannelPanel v-for="ch in activeChannels" :key="ch" :channel="ch"
          v-show="!hiddenChannels.has(ch)"
          :running="statusRunning && !runtimeError" :session="captureSession" :channel-status="channelStatus[String(ch)]"
          :send-enabled="!stopping && !runtimeError && downBuffers.some(b => b.channel === ch && b.active)" />
      </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { trackedSymbolPending, reloadTrackedSymbolSource } from '../../lib/trackedSymbolSource'
import { Search } from '@lucide/vue'
import { CAPTURE_START_TIMEOUT_MS } from '../../lib/captureStartup'
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
import { useToast } from '../../composables/useToast'
const props = defineProps<{ deviceConnected: boolean }>()
const dash = useDashboard('rtt')
const toast = useToast()
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
const backendSourcePending = ref(false)
const sourcePending = computed(() => backendSourcePending.value || trackedSymbolPending.value > 0)
const reloadingSources = ref(false)
const statusKnown = ref(false)
const downBuffers = ref<Array<{ channel?: number, active?: boolean }>>([])
const runtimeError = ref<string | null>(null)
const actionError = ref<string | null>(null)
const activeChannels = ref<number[]>([0])
const hiddenChannels = ref(new Set<number>(settings.value.rttHiddenChannels || []))
const upBuffers = ref<Array<{ channel: number, name?: string, active?: boolean }>>([])
const channelGrid = ref<HTMLElement | null>(null)
const autoFit = ref(false)
const inspectedChannels = ref<{ address: string, channels: number[], up_buffers: typeof upBuffers.value } | null>(null)
function fitPanels(event: MouseEvent): void {
  const target = event.target
  if (!(target instanceof HTMLElement) || !target.matches(
    '.rtt-view-tab, .rtt-channel-grid, .rtt-channel-panel, .rtt-channel-panel header, .channel-content, .rtt-view-toolbar, .rtt-primary-tools, .resize-hint',
  )) return
  channelGrid.value?.querySelectorAll<HTMLElement>('.rtt-channel-panel').forEach(panel => {
    panel.style.removeProperty('width')
    panel.style.removeProperty('height')
  })
  autoFit.value = true
}
watch(() => props.deviceConnected, () => {
  searchGeneration++
  searching.value = false
  inspectedChannels.value = null
})
const availableChannels = computed(() => activeChannels.value.map(channel => ({
  channel, name: upBuffers.value.find(item => item.channel === channel)?.name,
})))
function toggleChannel(channel: number): void {
  const next = new Set(hiddenChannels.value)
  if (next.has(channel)) next.delete(channel)
  else next.add(channel)
  hiddenChannels.value = next
  persistSettings({ ...loadDesktopSettings(desktopStorage), rttHiddenChannels: [...next] })
}
const captureSession = ref<string>()
const channelStatus = ref<Record<string, { numeric_channels?: string[], encoding?: string }>>({})
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
    inspectedChannels.value = null
    searchGeneration++
    searching.value = false
  }
  settings.value = latest
  hiddenChannels.value = new Set(latest.rttHiddenChannels || [])
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
  inspectedChannels.value = null
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
    inspectedChannels.value = null
    if (props.deviceConnected) {
      const deviceResponse = await fetch(`${API_BASE}/api/device/status`)
      if (!deviceResponse.ok) throw new Error(tr('读取设备状态失败', 'Could not read device status'))
      const device = await deviceResponse.json()
      if (disposed || generation !== searchGeneration) return
      if (device.connected && Number(device.idcode) > 0) {
        const response = await fetch(`${API_BASE}/api/device/rtt-control-block`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ address: result.addr }),
        })
        const info = await response.json()
        if (disposed || generation !== searchGeneration) return
        if (!response.ok) throw new Error(typeof info.detail === 'string' ? info.detail : tr('RTT 控制块读取失败', 'Could not read RTT control block'))
        inspectedChannels.value = { address: result.addr, channels: info.channels, up_buffers: info.up_buffers }
        if (!statusRunning.value) {
          activeChannels.value = info.channels
          upBuffers.value = info.up_buffers
        }
      }
    }
  } catch (caught) {
    if (!disposed && generation === searchGeneration) {
      addressError.value = caught instanceof Error ? caught.message : String(caught)
    }
  } finally {
    if (!disposed && generation === searchGeneration) searching.value = false
  }
}

let lastSourceChange = 0
async function reloadSources(): Promise<void> {
  reloadingSources.value = true
  try {
    if (!await reloadTrackedSymbolSource()) {
      const response = await fetch(`${API_BASE}/api/symbols/reload-sources`, { method: 'POST' })
      const result = await response.json()
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : tr('重载失败', 'Reload failed'))
    }
    await refreshStatus()
    toast.success(tr('符号已重新加载', 'Symbols reloaded'), 2500)
  } catch (error) {
    toast.error(error instanceof Error ? error.message : String(error))
  } finally {
    reloadingSources.value = false
  }
}
async function refreshStatus(): Promise<Record<string, any> | null> {
  try {
    const response = await fetch(`${API_BASE}/api/dash/rtt/status`)
    if (response.ok) {
      const status = await response.json()
      const changed = status.file_source_change
      backendSourcePending.value = changed?.state === 'awaiting-reload' || changed?.state === 'failed'
      if (changed && changed.sequence !== lastSourceChange) {
        lastSourceChange = changed.sequence
        if (changed.error) toast.error(changed.error)
        if (!changed.pending && changed.state === 'applied') {
          rttAddress.value = changed.rtt_addr && isRttAddress(changed.rtt_addr) ? changed.rtt_addr : ''
          persistSettings({ ...settings.value, rttAddress: rttAddress.value })
        }
      }
      statusKnown.value = true
      statusRunning.value = status.running === true
      const newSession = status.session && status.session !== captureSession.value
      captureSession.value = status.session
      channelStatus.value = status.channel_status || {}
      const preview = !status.running && inspectedChannels.value?.address === rttAddress.value ? inspectedChannels.value : null
      activeChannels.value = preview ? preview.channels : Array.isArray(status.channels) && status.channels.length ? status.channels : [0]
      upBuffers.value = preview ? preview.up_buffers : Array.isArray(status.up_buffers) ? status.up_buffers : []
      downBuffers.value = Array.isArray(status.down_buffers) ? status.down_buffers : []
      if (typeof status.error === 'string' && status.error) runtimeError.value = status.error
      else if (newSession) runtimeError.value = null
      return status
    }
  } catch { /* low-rate status retries below */ }
  return null
}

async function pollStatus(): Promise<void> {
  await refreshStatus()
  if (!disposed) statusTimer = setTimeout(pollStatus, 1_000)
}

async function waitForRttReady(timeoutMs = CAPTURE_START_TIMEOUT_MS): Promise<boolean> {
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
    runtimeError.value = tr('RTT 后台准备超时；请查看后台错误和连接状态，地址不一定有误', 'RTT backend preparation timed out. Check backend errors and connection status; the address may be valid.')
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
    const started = await dash.start({
      all_channels: true,
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
.rtt-channel-grid { display: flex; flex-wrap: wrap; align-content: start; align-items: flex-start; gap: 12px; flex: 1; min-height: 0; overflow: auto; padding-top: 8px; }
.rtt-channel-grid.multiple > :deep(.rtt-channel-panel) { width: calc(50% - 6px); }
.rtt-channel-grid.auto-fit { display: grid; grid-template-columns: minmax(0, 1fr); grid-auto-rows: minmax(320px, 1fr); align-content: stretch; align-items: stretch; }
.rtt-channel-grid.auto-fit.multiple { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.rtt-channel-grid.auto-fit > :deep(.rtt-channel-panel) { width: 100%; height: 100%; }
@media (max-width: 1000px) { .rtt-channel-grid.auto-fit.multiple { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 1000px) { .rtt-channel-grid.multiple > :deep(.rtt-channel-panel) { width: 100%; } }
.rtt-view-tab { display: flex; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; }
.rtt-config-row { display: flex; align-items: center; gap: 10px; min-height: 38px; flex-shrink: 0; padding: 2px 0 7px; border-bottom: 1px solid var(--border-subtle); overflow-x: auto; }
.rtt-config-row label { font-size: 12px; color: var(--muted); white-space: nowrap; }
#rtt-address { width: 136px; min-width: 110px; height: 30px; padding: 0 8px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: inherit; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.rtt-channel-options { display: flex; align-items: center; gap: 10px; }
.rtt-channel-options label { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; }
.rtt-channel-options input { accent-color: var(--accent); }
.rtt-config-row :deep(.control-toolbar) { padding: 0; flex-shrink: 0; margin-left: auto; }
.btn-search { height: 30px; display: inline-flex; align-items: center; gap: 5px; padding: 0 9px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: inherit; cursor: pointer; }
.address-error { min-width: 0; color: var(--danger, #dc2626); font-size: 12px; overflow-wrap: anywhere; }
.btn-search { flex-shrink: 0; }
</style>
