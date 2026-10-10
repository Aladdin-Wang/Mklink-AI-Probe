<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { Download, RefreshCw, RotateCcw, Tag, Unplug, Usb } from '@lucide/vue'
import { invoke } from '@tauri-apps/api/core'
import { useMklinkApi } from '../composables/useMklinkApi'
import { useToast } from '../composables/useToast'
import { useSymbolCatalog } from '../composables/useSymbolCatalog'
import { tr } from '../composables/useLanguage'
import {
  isSameFileSourcePath,
  isSymbolFilePath,
  loadDesktopSettings,
  saveDesktopSettings,
  type DesktopSettings,
} from '../lib/desktopSettings'
import { pickSymbolFile, type PickedFile } from '../lib/filePicker'
import { saveBlobFile } from '../lib/downloadTextFile'
import { refreshRttAddressForSymbol } from '../lib/rttSymbolAddress'
import { IS_TAURI } from '../lib/runtimeEndpoint'
import { rememberSymbolPath } from '../lib/symbolPathHistory'
import { sharedRuntime } from '../composables/useBackendHealth'
import type { AxlStatus, FileSourceKind, PortInfo, ProbeFirmwareCheck, ProbeFirmwareUpgrade, ProjectConfig } from '../types/mklink'
import ConfigSectionNav, { type ConfigSection } from '../components/config/ConfigSectionNav.vue'
import FileSourcesPanel from '../components/config/FileSourcesPanel.vue'
import RuntimePanel from '../components/config/RuntimePanel.vue'

const {
  deviceStatus,
  listPorts,
  getConfig,
  updateConfig,
  refreshStatus,
  uploadFileSource,
  connectDevice,
  disconnectDevice,
  parseAxf,
  findRtt,
  probeFirmwareCheck,
  upgradeProbeFirmware,
  downloadProbeFirmware,
} = useMklinkApi()
const toast = useToast()
const symbolCatalog = useSymbolCatalog()

const activeSection = ref<ConfigSection>('local')
const config = ref<ProjectConfig>({})
// Keep the stored/API value in Hz; only the editable presentation uses MHz.
const swdClockMhz = computed({
  get: () => config.value.swd_clock ? String(Number(config.value.swd_clock) / 1_000_000) : '',
  set: (value: string | number) => {
    const text = String(value).trim()
    const hz = Number(text) * 1_000_000
    const rounded = Math.round(hz)
    config.value.swd_clock = text ? String(Math.abs(hz - rounded) < 0.000001 ? rounded : hz) : ''
  },
})
const confirmedClockMhz = computed(() => {
  const hz = deviceStatus.value.clock_hz
  return typeof hz === 'number' && hz > 0 ? String(hz / 1_000_000) : null
})
const localPort = ref('')
const portOptions = ref<{ label: string; value: string }[]>([])
const localPortExplicit = ref(false)
let localPortTouched = false
const probePorts = ref<PortInfo[]>([])
const selectedProbe = computed(() => probePorts.value.find(port => port.device === localPort.value))
const switchingProbe = computed(() => sharedRuntime.value && localPortExplicit.value
  && !!selectedProbe.value && localPort.value !== deviceStatus.value.port)
const settings = ref<DesktopSettings>(loadDesktopSettings(window.localStorage))

const portsLoading = ref(false)
const savingLocal = ref(false)
const connecting = ref(false)
const disconnecting = ref(false)
const connectionOwners = ref<string[] | null>(null)
const browsingFiles = ref(false)
const parsingSymbols = ref(false)
let symbolParseGeneration = 0
let disposed = false
const localSaveState = ref<'idle' | 'saving' | 'saved' | 'unconfirmed'>('idle')

const firmwareCheck = ref<ProbeFirmwareCheck | null>(null)
const firmwareUpgrading = ref(false)
const firmwareUpgradeStatus = ref('')
const firmwareUpgradeResult = ref<ProbeFirmwareUpgrade | null>(null)
const firmwareDownloading = ref(false)
const firmwareDownloadStatus = ref('')
const manualFirmwareChoice = ref('')
const usbNamingAction = ref<'idle' | 'apply' | 'restore'>('idle')
const manualFirmwareUpgrade = computed(() => {
  const result = firmwareUpgradeResult.value
  if (!result || result.status === 'updated' || result.status === 'up_to_date') return null
  return result
})
const firmwareDownloadTarget = computed(() => {
  const result = manualFirmwareUpgrade.value
  if (result?.download_available && result.model) return { model: result.model, family: result.family || 'microlink' as const }
  const choices = {
    v3: { model: 'V3', family: 'microlink' },
    v4: { model: 'V4', family: 'microlink' },
    hpm: { model: 'V4', family: 'hpmlink' },
  } as const
  return choices[manualFirmwareChoice.value as keyof typeof choices] || null
})

async function refreshPorts() {
  portsLoading.value = true
  try {
    const ports: PortInfo[] = await listPorts()
    probePorts.value = ports
    portOptions.value = ports.map(port => ({
      label: `${port.alias ? port.alias + ' · ' : ''}${port.device} — ${port.description} (${port.manufacturer})`,
      value: port.device,
    }))
  } catch (error: any) {
    toast.error(tr('读取串口失败: ', 'Failed to read serial ports: ') + error.message)
  } finally {
    portsLoading.value = false
  }
}

async function loadConfig() {
  try {
    const loaded = await getConfig()
    if (disposed) return
    // Initial loading must not overwrite edits made while the request was pending.
    config.value = { ...loaded, ...config.value }
    if (!localPortTouched) {
      localPort.value = loaded.com_port || ''
      localPortExplicit.value = false
    }
  } catch (error: any) {
    toast.error(tr('读取配置失败: ', 'Failed to load configuration: ') + error.message)
  }
}

async function saveLocalConfig() {
  if (savingLocal.value) return
  const rawClock = String(config.value.swd_clock ?? '').trim()
  if (rawClock) {
    const clock = Number(rawClock)
    if (!Number.isInteger(clock) || !(clock >= 1 && clock <= 10_000_000 || clock === 20_000_000 || clock === 30_000_000)) {
      localSaveState.value = 'idle'
      toast.error(tr('SWD 时钟支持 1 Hz 至 10 MHz，或 20 MHz、30 MHz 档位', 'SWD clock supports 1 Hz to 10 MHz, or the 20 MHz / 30 MHz profiles'))
      return
    }
  }
  savingLocal.value = true
  localSaveState.value = 'saving'
  const payload = {
    ...config.value,
    com_port: localPort.value.trim(),
    swd_clock: rawClock || undefined,
  }
  try {
    config.value = await updateConfig(payload)
    localSaveState.value = 'saved'
  } catch (error: any) {
    localSaveState.value = 'unconfirmed'
    toast.error(tr('保存配置失败: ', 'Failed to save configuration: ') + error.message)
  } finally {
    if (deviceStatus.value.connected) await refreshStatus()
    savingLocal.value = false
  }
}

async function selectLocalPort() {
  localPortTouched = true
  localPortExplicit.value = Boolean(localPort.value.trim())
  if (sharedRuntime.value) return
  await saveLocalConfig()
}

async function connectLocal() {
  if (connecting.value || disconnecting.value) return
  connectionOwners.value = null
  localPortTouched = true
  connecting.value = true
  try {
    const selectedPort = localPort.value.trim()
    const result = await connectDevice({
      ...(localPortExplicit.value && selectedPort
        ? { port: selectedPort }
        : { restore_last: true }),
      axf: isSymbolFilePath(settings.value.symbolPath)
        ? settings.value.symbolPath.trim()
        : undefined,
    })
    const connectedPort = result.port || deviceStatus.value.port
    if (connectedPort) {
      localPort.value = connectedPort
      localPortExplicit.value = false
      config.value = { ...config.value, com_port: connectedPort }
    }
    const symbolPath = settings.value.symbolPath.trim()
    if (
      isSymbolFilePath(symbolPath)
      && deviceStatus.value.axf?.loaded
      && isSameFileSourcePath(symbolPath, deviceStatus.value.axf.axf_path)
    ) {
      await refreshRttForSymbols(symbolPath)
    }
  } catch (error: any) {
    // A failed explicit selection must stay selected for the next attempt.
    if (!localPortExplicit.value) {
      localPort.value = ''
      config.value = { ...config.value, com_port: '' }
    }
    toast.error(tr('连接失败: ', 'Connection failed: ') + error.message)
  } finally {
    connecting.value = false
  }
}

async function disconnectLocal() {
  if (disconnecting.value || connecting.value) return
  connectionOwners.value = null
  disconnecting.value = true
  try {
    await disconnectDevice()
  } catch (error: any) {
    if (error.detail?.reason === 'shared_clients_attached') {
      connectionOwners.value = (error.detail.clients || []).map((client: { name: string; kind: string }) => `${client.name} (${client.kind})`)
    } else {
      toast.error(tr('断开失败: ', 'Disconnect failed: ') + error.message)
    }
  } finally {
    disconnecting.value = false
  }
}

async function renameUsbPorts(action: 'apply' | 'restore') {
  if (!IS_TAURI) {
    toast.warn(tr('端口名称管理仅支持 Windows 桌面版', 'Port naming is available only in the Windows desktop app'))
    return
  }
  if (usbNamingAction.value !== 'idle') return
  const restoring = action === 'restore'
  const prompt = restoring
    ? tr('将恢复已由 MKLink 修改的端口显示名称，并请求管理员权限。继续吗？', 'This restores MKLink port display names and requests administrator permission. Continue?')
    : tr('将严格识别当前在线的 MKLink V2/V3/V4 端口并修改显示名称，需要管理员权限。继续吗？', 'This verifies connected MKLink V2/V3/V4 ports and changes their display names. Administrator permission is required. Continue?')
  if (!window.confirm(prompt)) return

  usbNamingAction.value = action
  try {
    await invoke('rename_usb_ports', { action })
    toast.success(restoring
      ? tr('端口名称已恢复；如设备管理器未刷新，请重新插拔下载器。', 'Port names restored; reconnect the probe if Device Manager has not refreshed.')
      : tr('端口名称处理完成；如设备管理器未刷新，请重新插拔下载器。', 'Port naming completed; reconnect the probe if Device Manager has not refreshed.'))
    await refreshPorts()
  } catch (error: any) {
    toast.error((restoring ? tr('恢复端口名称失败: ', 'Failed to restore port names: ') : tr('修改端口名称失败: ', 'Failed to rename ports: ')) + (error?.message || error))
  } finally {
    usbNamingAction.value = 'idle'
  }
}

interface SelectedFileSource {
  path: string
  displayPath: string
}

async function selectedFilePath(
  kind: FileSourceKind,
  selected: PickedFile,
): Promise<SelectedFileSource | null> {
  if (!selected) return null
  if (typeof selected === 'string') return { path: selected, displayPath: selected }
  const uploaded = await uploadFileSource(kind, selected)
  return { path: uploaded.path, displayPath: uploaded.name || selected.name }
}

async function browseSymbolFile() {
  if (browsingFiles.value || parsingSymbols.value) return
  browsingFiles.value = true
  try {
    const source = await selectedFilePath('symbol', await pickSymbolFile())
    if (source) {
      updateFilePath(source.path, source.displayPath)
      rememberSymbolPath(window.localStorage, source.path, source.displayPath)
    }
  } catch (error: any) {
    toast.error(tr('加载 AXF / ELF 文件失败: ', 'Failed to load AXF / ELF file: ') + error.message)
  } finally {
    browsingFiles.value = false
  }
}

function updateFilePath(value: string, displayPath = value) {
  symbolParseGeneration++
  parsingSymbols.value = false
  try {
    const latest = loadDesktopSettings(window.localStorage)
    const sourceChanged = !isSameFileSourcePath(latest.symbolPath, value)
    settings.value = saveDesktopSettings(window.localStorage, {
      ...latest,
      symbolPath: value,
      symbolDisplayPath: displayPath === value ? '' : displayPath,
      rttAddress: sourceChanged ? '' : latest.rttAddress,
    })
  } catch (error: any) {
    toast.error(tr('保存文件路径失败: ', 'Failed to save file paths: ') + error.message)
  }
}

async function refreshRttForSymbols(sourcePath: string) {
  const refreshed = await refreshRttAddressForSymbol(
    window.localStorage,
    sourcePath,
    findRtt,
  )
  settings.value = refreshed.settings
  if (refreshed.error) {
    toast.warn(
      tr('AXF 已加载，但 RTT 地址自动刷新失败: ', 'AXF loaded, but automatic RTT address refresh failed: ')
      + (refreshed.error instanceof Error ? refreshed.error.message : String(refreshed.error)),
    )
  }
}

async function parseSymbols() {
  if (!deviceStatus.value.connected || !isSymbolFilePath(settings.value.symbolPath)) return
  const requestedPath = settings.value.symbolPath.trim()
  rememberSymbolPath(window.localStorage, requestedPath, settings.value.symbolDisplayPath)
  const generation = ++symbolParseGeneration
  parsingSymbols.value = true
  try {
    const result = await parseAxf(requestedPath) as AxlStatus
    if (!isActiveSymbolParse(generation, requestedPath)) return
    if (result.loaded) {
      if (!isSameFileSourcePath(requestedPath, result.axf_path)) {
        toast.error(tr(`AXF 解析失败: 后端仍在使用 ${result.axf_path || '未知文件'}`, `AXF parsing failed: backend is still using ${result.axf_path || 'an unknown file'}`))
        return
      }
      await refreshRttForSymbols(requestedPath)
      if (!isActiveSymbolParse(generation, requestedPath)) return
      try {
        await symbolCatalog.ensureLoaded(true)
      } catch (error: any) {
        if (!isActiveSymbolParse(generation, requestedPath)) return
        toast.error(tr('符号目录刷新失败: ', 'Failed to refresh symbol catalog: ') + error.message)
        return
      }
      if (!isActiveSymbolParse(generation, requestedPath)) return
      toast.success(tr(`AXF 解析成功: ${result.variable_count || 0} 个固定可读变量`, `AXF parsed: ${result.variable_count || 0} fixed readable variables`))
    } else {
      toast.error(tr('AXF 解析失败', 'AXF parsing failed'))
    }
  } catch (error: any) {
    if (isActiveSymbolParse(generation, requestedPath)) {
      toast.error(tr('AXF 解析失败: ', 'AXF parsing failed: ') + error.message)
    }
  } finally {
    if (generation === symbolParseGeneration) parsingSymbols.value = false
  }
}

function isActiveSymbolParse(generation: number, requestedPath: string): boolean {
  return !disposed
    && generation === symbolParseGeneration
    && isSameFileSourcePath(requestedPath, settings.value.symbolPath)
}

async function recheckFirmware() {
  try {
    firmwareCheck.value = await probeFirmwareCheck()
  } catch {
    // Firmware checks are advisory and must not block configuration.
  }
}

async function upgradeFirmware() {
  if (firmwareUpgrading.value) return
  if (!window.confirm(tr(
    deviceStatus.value.connected
      ? '将让探针进入 Bootloader 并重启连接，随后自动复制 UF2 固件。继续吗？'
      : '将读取 MICROKEEN U 盘并检查固件；若未连接命令端口，请按住升级键手动进入 Bootloader。继续吗？',
    deviceStatus.value.connected
      ? 'The probe will enter Bootloader and restart its connection before copying the UF2 firmware. Continue?'
      : 'The MICROKEEN drive will be checked; without a command-port session, hold the upgrade button to enter Bootloader manually. Continue?',
  ))) return
  firmwareUpgrading.value = true
  firmwareUpgradeResult.value = null
  manualFirmwareChoice.value = ''
  firmwareDownloadStatus.value = ''
  firmwareUpgradeStatus.value = tr('正在升级探针固件...', 'Upgrading probe firmware...')
  try {
    const result = await upgradeProbeFirmware(true)
    firmwareUpgradeResult.value = result
    if (result.status === 'updated') {
      firmwareUpgradeStatus.value = tr(
        `升级完成：${result.verified_version || result.latest_version || ''}`,
        `Update complete: ${result.verified_version || result.latest_version || ''}`,
      )
      toast.success(firmwareUpgradeStatus.value)
    } else if (result.status === 'up_to_date') {
      firmwareUpgradeStatus.value = tr('当前已是最新固件', 'The probe firmware is already up to date')
      toast.success(firmwareUpgradeStatus.value)
    } else {
      firmwareUpgradeStatus.value = result.message || tr('未完成自动升级，请按提示手动升级', 'Automatic update did not complete; follow the manual update instructions')
    }
    await recheckFirmware()
  } catch (error: any) {
    firmwareUpgradeStatus.value = error?.message || tr('固件升级失败', 'Firmware update failed')
    toast.error(firmwareUpgradeStatus.value)
  } finally {
    firmwareUpgrading.value = false
  }
}

async function downloadFirmware() {
  const result = firmwareDownloadTarget.value
  if (!result?.model || firmwareDownloading.value) return
  firmwareDownloading.value = true
  firmwareDownloadStatus.value = tr('正在下载固件...', 'Downloading firmware...')
  try {
    const downloaded = await downloadProbeFirmware(
      result.model,
      result.family || 'microlink',
    )
    const saved = await saveBlobFile(downloaded.filename, downloaded.blob)
    if (!saved) {
      firmwareDownloadStatus.value = ''
      return
    }
    const source = downloaded.source === 'gitee'
      ? tr('Gitee', 'Gitee')
      : downloaded.source === 'local'
        ? tr('本地固件包', 'local firmware package')
        : tr('GitHub', 'GitHub')
    firmwareDownloadStatus.value = tr(
      `已保存 ${downloaded.filename}（来源：${source}）`,
      `Saved ${downloaded.filename} (source: ${source})`,
    )
    toast.success(firmwareDownloadStatus.value)
  } catch (error: any) {
    firmwareDownloadStatus.value = error?.message || tr('固件下载失败', 'Firmware download failed')
    toast.error(firmwareDownloadStatus.value)
  } finally {
    firmwareDownloading.value = false
  }
}

onMounted(async () => {
  // Firmware status is checked from the dedicated upgrade action. Avoid a
  // network manifest lookup during login so the local connection controls are
  // immediately responsive.
  await Promise.all([refreshPorts(), loadConfig()])
  const restoredPort = localPort.value.trim()
  if (!localPortTouched && restoredPort && !portOptions.value.some(option => option.value === restoredPort)) {
    localPort.value = ''
  }
})

onUnmounted(() => {
  disposed = true
  symbolParseGeneration++
})
</script>

<template>
  <div class="config-workspace">
    <ConfigSectionNav v-model="activeSection" />

    <main class="section-content">
      <RuntimePanel v-if="activeSection === 'runtime'" />
      <section
        v-else-if="activeSection === 'local'"
        class="card local-panel"
        data-testid="local-device-panel"
        aria-labelledby="local-device-title"
      >
        <header class="panel-header">
          <h2 id="local-device-title">{{ tr('本地设备', 'Local Device') }}</h2>
          <span :class="['badge', deviceStatus.connected ? 'badge-ok' : 'badge-err']">
            {{ deviceStatus.connected ? tr('已连接', 'Connected') : tr('未连接', 'Disconnected') }}
          </span>
        </header>
        <div v-if="deviceStatus.connected && deviceStatus.port" class="connection-detail" data-testid="connected-port">
          {{ tr('当前串口：', 'Connected port: ') }}{{ deviceStatus.port }}
        </div>
        <div v-if="deviceStatus.connected" class="connection-detail" data-testid="confirmed-clock">
          {{ tr('下载器设置速率：', 'Probe clock setting: ') }}{{ confirmedClockMhz ? `${confirmedClockMhz} MHz` : tr('未确认', 'Unconfirmed') }}
        </div>
        <div v-if="deviceStatus.connected && deviceStatus.clock_warning" role="status" data-testid="clock-warning">
          <p>{{ tr('下载器已连接，但所选速率设置未获确认。可重新应用所选速率；连接下载器和设置速率均无需连接目标板。', 'The probe is connected, but the requested clock setting was not acknowledged. Retry applying it. Connecting and configuring the probe do not require a target board.') }}</p>
          <p>{{ deviceStatus.clock_warning }}</p>
          <button class="btn btn-sm" data-testid="retry-clock" :disabled="savingLocal || connecting || disconnecting" @click="saveLocalConfig">{{ tr('重新应用所选速率', 'Reapply requested clock') }}</button>
        </div>

        <div class="form-row">
          <label class="form-label" for="local-port">{{ tr('串口', 'Serial Port') }}</label>
          <select id="local-port" v-model="localPort" class="form-select" data-testid="local-port" :disabled="savingLocal" @change="selectLocalPort">
            <option value="">{{ tr('自动搜索', 'Auto Search') }}</option>
            <option v-for="port in portOptions" :key="port.value" :value="port.value">
              {{ port.label }}
            </option>
          </select>
          <button
            class="btn btn-sm icon-button"
            type="button"
            :title="tr('刷新串口', 'Refresh serial ports')"
            data-testid="refresh-ports"
            :disabled="portsLoading"
            @click="refreshPorts"
          >
            <RefreshCw :size="14" aria-hidden="true" />
          </button>
        </div>

        <div v-if="sharedRuntime && selectedProbe?.probe_id" class="connection-detail" data-testid="selected-probe-id">
          {{ selectedProbe.probe_id }}
        </div>

        <div class="form-row">
          <label class="form-label" for="swd-clock">{{ tr('设置时钟 (MHz)', 'Requested Clock (MHz)') }}</label>
          <input
            id="swd-clock"
            v-model="swdClockMhz"
            type="number"
            min="0.000001"
            max="30"
            step="any"
            class="form-input"
            data-testid="swd-clock"
            :disabled="savingLocal"
            :placeholder="tr('如 1、10、20、30', 'e.g. 1, 10, 20, 30')"
            @change="saveLocalConfig"
          />
        </div>

        <div class="local-actions">
          <span class="auto-save-state" data-testid="local-auto-save">
            {{ localSaveState === 'saving' ? tr('自动保存中...', 'Saving...') : localSaveState === 'saved' ? tr('已自动保存', 'Saved') : localSaveState === 'unconfirmed' ? tr('保存未确认，请刷新页面核对配置', 'Save unconfirmed; refresh the page to check configuration') : tr('修改后自动保存', 'Changes save automatically') }}
          </span>
          <button
            class="btn btn-primary icon-command"
            type="button"
            data-testid="connect-local"
            :disabled="connecting || disconnecting || (deviceStatus.connected && !switchingProbe)"
            @click="connectLocal"
          >
            <Usb :size="15" aria-hidden="true" />
            {{ connecting ? tr('连接中...', 'Connecting...') : switchingProbe && deviceStatus.connected ? tr('切换下载器', 'Switch Probe') : tr('连接设备', 'Connect Device') }}
          </button>
          <button
            class="btn icon-command"
            type="button"
            data-testid="disconnect-local"
            :disabled="disconnecting || connecting || !deviceStatus.connected"
            @click="disconnectLocal"
          >
            <Unplug :size="15" aria-hidden="true" />
            {{ disconnecting ? tr('断开中...', 'Disconnecting...') : tr('断开', 'Disconnect') }}
          </button>
        </div>

        <div v-if="connectionOwners !== null" role="alert" data-testid="connection-owners">
          <p>{{ tr('设备仍被以下客户端共享，断开前请在后台管理中结束相应会话：', 'The device is shared by these clients. End their sessions in Backend Management before disconnecting:') }} {{ connectionOwners.join('、') }}</p>
          <button class="btn btn-sm" type="button" data-testid="manage-connection-owners" @click="activeSection = 'runtime'">{{ tr('打开后台管理', 'Open Backend Management') }}</button>
        </div>

        <div v-if="IS_TAURI" class="port-naming-actions" data-testid="usb-port-naming">
          <span class="form-hint">{{ tr('设备管理器端口显示名称', 'Device Manager port display names') }}</span>
          <button
            class="btn btn-sm icon-command"
            type="button"
            data-testid="rename-usb-ports"
            :disabled="usbNamingAction !== 'idle'"
            @click="renameUsbPorts('apply')"
          >
            <Tag :size="14" aria-hidden="true" />
            {{ usbNamingAction === 'apply' ? tr('处理中...', 'Working...') : tr('修改端口名称', 'Rename ports') }}
          </button>
          <button
            class="btn btn-sm icon-command"
            type="button"
            data-testid="restore-usb-ports"
            :disabled="usbNamingAction !== 'idle'"
            @click="renameUsbPorts('restore')"
          >
            <RotateCcw :size="14" aria-hidden="true" />
            {{ usbNamingAction === 'restore' ? tr('处理中...', 'Working...') : tr('恢复名称', 'Restore names') }}
          </button>
        </div>

      </section>

      <FileSourcesPanel
        v-else-if="activeSection === 'files'"
        :symbol-path="settings.symbolPath"
        :symbol-display-path="settings.symbolDisplayPath"
        :connected="deviceStatus.connected"
        :symbol-status="deviceStatus.axf"
        :browsing="browsingFiles"
        :parsing="parsingSymbols"
        @update:symbol-path="updateFilePath($event)"
        @browse-symbol="browseSymbolFile"
        @parse="parseSymbols"
      />

      <section v-else class="card firmware-panel" data-testid="firmware-upgrade-panel">
        <header class="panel-header">
          <h2>{{ tr('固件升级', 'Firmware Update') }}</h2>
          <span v-if="firmwareCheck?.current_version" class="firmware-version">{{ firmwareCheck.current_version }}</span>
        </header>
        <div class="firmware-upgrade-content">
          <p>{{ tr('检查最新固件，支持的下载器会自动进入升级模式并完成升级。老版本无法自动进入时，可下载固件后按键升级。', 'Check for firmware and update automatically when supported. Older probes can be updated manually using the upgrade button and a downloaded firmware file.') }}</p>
          <button class="btn" type="button" data-testid="upgrade-firmware" :disabled="firmwareUpgrading" @click="upgradeFirmware">
            {{ firmwareUpgrading ? tr('升级中...', 'Updating...') : tr('检查并升级固件', 'Check and Update Firmware') }}
          </button>
          <div v-if="manualFirmwareUpgrade" class="manual-firmware-download" data-testid="manual-firmware-download">
            <strong>{{ manualFirmwareUpgrade.status === 'copied_unverified' ? tr('请检查升级结果', 'Check the update result') : tr('手动升级', 'Manual update') }}</strong>
            <span v-if="manualFirmwareUpgrade.latest_version">{{ tr('最新固件：', 'Latest firmware: ') }}{{ manualFirmwareUpgrade.latest_version }}</span>
            <p class="firmware-upgrade-status" data-testid="firmware-upgrade-status">{{ firmwareUpgradeStatus }}</p>
            <label v-if="!manualFirmwareUpgrade.download_available" class="firmware-model-choice">
              {{ tr('下载器型号', 'Probe model') }}
              <select v-model="manualFirmwareChoice" data-testid="firmware-model-choice" :disabled="firmwareDownloading">
                <option value="">{{ tr('请选择机身对应型号', 'Select the model shown on your probe') }}</option>
                <option value="v3">MicroLink V3</option>
                <option value="v4">MicroLink V4</option>
                <option value="hpm">HPMLink V4</option>
              </select>
            </label>
            <button class="btn icon-command" type="button" data-testid="download-firmware" :disabled="firmwareDownloading || !firmwareDownloadTarget" @click="downloadFirmware">
              <Download :size="14" aria-hidden="true" />
              {{ firmwareDownloading ? tr('下载中...', 'Downloading...') : tr('下载固件', 'Download Firmware') }}
            </button>
            <span v-if="firmwareDownloadStatus" class="firmware-download-status" data-testid="firmware-download-status">{{ firmwareDownloadStatus }}</span>
            <ol class="firmware-manual-steps" data-testid="firmware-manual-steps">
              <li>{{ tr('将对应型号的 UF2 固件下载并保存到本地。', 'Download and save the UF2 firmware for your probe model.') }}</li>
              <li>{{ tr('拔下 USB，按住升级按键再插入 USB：V3 为两个眼睛中间的按钮，V4 / HPMLink 为侧边拨轮按钮。', 'Unplug USB, hold the upgrade button, then reconnect USB. V3: the button between the two eyes. V4 / HPMLink: the side wheel button.') }}</li>
              <li>{{ tr('出现 Bootloader U 盘后，将 UF2 文件复制到该盘根目录，等待复制和升级完成。', 'When the Bootloader drive appears, copy the UF2 file to its root and wait for copying and updating to finish.') }}</li>
              <li>{{ tr('等待下载器重新启动；若未自动重启，复制完成后重新插拔 USB，再检查固件版本。', 'Wait for the probe to restart. If it does not restart automatically, reconnect USB after copying finishes, then check the firmware version.') }}</li>
            </ol>
          </div>
          <span v-else-if="firmwareUpgradeStatus" class="firmware-upgrade-status" data-testid="firmware-upgrade-status">{{ firmwareUpgradeStatus }}</span>
        </div>
      </section>
    </main>

  </div>
</template>

<style scoped>
.config-workspace {
  display: grid;
  grid-template-columns: 176px minmax(0, 1fr);
  align-items: start;
  gap: 20px;
}

.section-content {
  min-width: 0;
  max-width: 1040px;
}

.connection-detail {
  margin: -2px 0 10px;
  color: var(--muted);
  font: 11px var(--font-mono);
  overflow-wrap: anywhere;
}

.local-panel,
.firmware-panel {
  min-height: 270px;
}

.firmware-upgrade-content {
  display: grid;
  gap: 8px;
}

.firmware-version,
.firmware-upgrade-content p,
.firmware-upgrade-status {
  color: var(--muted);
  font-size: 12px;
}

.firmware-upgrade-content p {
  margin: 0;
  line-height: 1.5;
}

.firmware-upgrade-status {
  overflow-wrap: anywhere;
}

.manual-firmware-download {
  display: grid;
  justify-items: start;
  gap: 8px;
  margin-top: 4px;
  padding: 12px;
  border-left: 3px solid var(--accent);
  background: var(--bg);
  color: var(--fg);
}

.firmware-model-choice { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.firmware-manual-steps { margin: 8px 0 0; padding-left: 22px; line-height: 1.8; }

.manual-firmware-download p {
  margin: 0;
}

.firmware-download-status {
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}

.panel-header h2 {
  font-size: 15px;
  font-weight: 600;
}

.icon-button,
.icon-command {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.icon-button {
  width: 30px;
  padding: 0;
}

.icon-command {
  gap: 7px;
}

.local-actions,
.panel-actions {
  display: flex;
  gap: 8px;
  margin: 18px 0 20px 110px;
}

.port-naming-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 0 0 8px 110px;
}

.port-naming-actions .form-hint {
  color: var(--dim);
  font-size: 12px;
  margin-right: 4px;
}

.auto-save-state {
  color: var(--dim);
  font-size: 12px;
}

.firmware-banner {
  grid-column: 2;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: -8px;
  padding: 8px 12px;
  border: 1px solid #f59e0b;
  border-radius: 4px;
  background: var(--warn-bg);
  color: var(--warn);
}

.firmware-banner span {
  margin-right: auto;
}

@media (max-width: 760px) {
  .config-workspace {
    grid-template-columns: 1fr;
  }

  .local-actions,
  .panel-actions,
  .port-naming-actions {
    margin-left: 0;
    flex-wrap: wrap;
  }

  .firmware-banner {
    grid-column: 1;
    flex-wrap: wrap;
  }
}
</style>
