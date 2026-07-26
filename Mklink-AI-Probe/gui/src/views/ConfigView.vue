<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { RefreshCw, Search, TriangleAlert, Unplug, Usb } from '@lucide/vue'
import { useMklinkApi } from '../composables/useMklinkApi'
import { useMklinkWs } from '../composables/useMklinkWs'
import { useToast } from '../composables/useToast'
import { useSymbolCatalog } from '../composables/useSymbolCatalog'
import {
  isSameFileSourcePath,
  isSymbolFilePath,
  loadDesktopSettings,
  saveDesktopSettings,
  type DesktopSettings,
} from '../lib/desktopSettings'
import { pickMapFile, pickSymbolFile, type PickedFile } from '../lib/filePicker'
import type { AxlStatus, FileSourceKind, PortInfo, ProbeFirmwareCheck, ProjectConfig } from '../types/mklink'
import ConfigSectionNav, { type ConfigSection } from '../components/config/ConfigSectionNav.vue'
import FileSourcesPanel from '../components/config/FileSourcesPanel.vue'
import FirmwareUpdateModal from '../components/config/FirmwareUpdateModal.vue'

const {
  deviceStatus,
  listPorts,
  discoverPort,
  getConfig,
  updateConfig,
  uploadFileSource,
  connectDevice,
  disconnectDevice,
  parseAxf,
  probeFirmwareCheck,
} = useMklinkApi()
const { wsConnected, connect: wsConnect, disconnect: wsDisconnect } = useMklinkWs()
const toast = useToast()
const symbolCatalog = useSymbolCatalog()

const activeSection = ref<ConfigSection>('local')
const config = ref<ProjectConfig>({})
const localPort = ref('')
const portOptions = ref<{ label: string; value: string }[]>([])
const settings = ref<DesktopSettings>(loadDesktopSettings(window.localStorage))

const portsLoading = ref(false)
const savingLocal = ref(false)
const connecting = ref(false)
const disconnecting = ref(false)
const browsingFiles = ref(false)
const parsingSymbols = ref(false)
const localSaveState = ref<'idle' | 'saving' | 'saved'>('idle')

const remoteUrl = ref('ws://127.0.0.1:8765')
const remoteToken = ref('')
const wsConnecting = ref(false)
const serveConfig = reactive({ host: '127.0.0.1', port: 8765, token: '' })
const launching = ref(false)

const firmwareCheck = ref<ProbeFirmwareCheck | null>(null)
const showFirmwareModal = ref(false)

async function refreshPorts() {
  portsLoading.value = true
  try {
    const ports: PortInfo[] = await listPorts()
    portOptions.value = ports.map(port => ({
      label: `${port.device} — ${port.description} (${port.manufacturer})`,
      value: port.device,
    }))
  } catch (error: any) {
    toast.error('读取串口失败: ' + error.message)
  } finally {
    portsLoading.value = false
  }
}

async function autoDiscover() {
  portsLoading.value = true
  try {
    const result = await discoverPort()
    if (result.port) {
      localPort.value = result.port
      await saveLocalConfig()
    }
  } catch (error: any) {
    toast.error('自动检测失败: ' + error.message)
  } finally {
    portsLoading.value = false
  }
}

async function loadConfig() {
  try {
    config.value = await getConfig()
    localPort.value = config.value.com_port || ''
  } catch (error: any) {
    toast.error('读取配置失败: ' + error.message)
  }
}

async function saveLocalConfig() {
  const rawClock = String(config.value.swd_clock ?? '').trim()
  if (rawClock) {
    const clock = Number(rawClock)
    if (!Number.isInteger(clock) || clock < 1 || clock > 10_000_000) {
      toast.error('SWD 时钟必须是 1 Hz 到 10 MHz 之间的整数')
      return
    }
  }
  savingLocal.value = true
  localSaveState.value = 'saving'
  try {
    config.value = await updateConfig({
      ...config.value,
      com_port: localPort.value || undefined,
      swd_clock: rawClock || undefined,
    })
    localSaveState.value = 'saved'
  } catch (error: any) {
    localSaveState.value = 'idle'
    toast.error('保存配置失败: ' + error.message)
  } finally {
    savingLocal.value = false
  }
}

async function connectLocal() {
  connecting.value = true
  try {
    await connectDevice({
      port: localPort.value || config.value.com_port || undefined,
      axf: isSymbolFilePath(settings.value.symbolPath)
        ? settings.value.symbolPath.trim()
        : undefined,
    })
  } catch (error: any) {
    toast.error('连接失败: ' + error.message)
  } finally {
    connecting.value = false
  }
}

async function disconnectLocal() {
  disconnecting.value = true
  try {
    await disconnectDevice()
  } catch (error: any) {
    toast.error('断开失败: ' + error.message)
  } finally {
    disconnecting.value = false
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
  browsingFiles.value = true
  try {
    const source = await selectedFilePath('symbol', await pickSymbolFile())
    if (source) updateFilePath('symbol', source.path, source.displayPath)
  } catch (error: any) {
    toast.error('加载 AXF / ELF 文件失败: ' + error.message)
  } finally {
    browsingFiles.value = false
  }
}

async function browseMapFile() {
  browsingFiles.value = true
  try {
    const source = await selectedFilePath('map', await pickMapFile())
    if (source) updateFilePath('map', source.path, source.displayPath)
  } catch (error: any) {
    toast.error('加载 MAP 文件失败: ' + error.message)
  } finally {
    browsingFiles.value = false
  }
}

function persistFilePaths() {
  try {
    saveDesktopSettings(window.localStorage, settings.value)
  } catch (error: any) {
    toast.error('保存文件路径失败: ' + error.message)
  }
}

function updateFilePath(kind: 'symbol' | 'map', value: string, displayPath = value) {
  if (kind === 'symbol') {
    settings.value.symbolPath = value
    settings.value.symbolDisplayPath = displayPath === value ? '' : displayPath
  } else {
    settings.value.mapPath = value
    settings.value.mapDisplayPath = displayPath === value ? '' : displayPath
  }
  persistFilePaths()
}

async function parseSymbols() {
  if (!deviceStatus.value.connected || !isSymbolFilePath(settings.value.symbolPath)) return
  parsingSymbols.value = true
  try {
    const requestedPath = settings.value.symbolPath.trim()
    const result = await parseAxf(requestedPath) as AxlStatus
    if (result.loaded) {
      if (!isSameFileSourcePath(requestedPath, result.axf_path)) {
        toast.error(`AXF 解析失败: 后端仍在使用 ${result.axf_path || '未知文件'}`)
        return
      }
      try {
        await symbolCatalog.ensureLoaded(true)
      } catch (error: any) {
        toast.error('符号目录刷新失败: ' + error.message)
        return
      }
      toast.success(`AXF 解析成功: ${result.variable_count || 0} 个固定可读变量`)
    } else {
      toast.error('AXF 解析失败')
    }
  } catch (error: any) {
    toast.error('AXF 解析失败: ' + error.message)
  } finally {
    parsingSymbols.value = false
  }
}

function connectRemote() {
  wsConnecting.value = true
  try {
    wsConnect(remoteToken.value || undefined, remoteUrl.value || undefined)
  } finally {
    wsConnecting.value = false
  }
}

function launchServer() {
  launching.value = true
  window.open(`http://${serveConfig.host}:${serveConfig.port}/docs`, '_blank')
  launching.value = false
}

async function recheckFirmware(openModal = true) {
  try {
    firmwareCheck.value = await probeFirmwareCheck()
    if (openModal && firmwareCheck.value.status === 'upgrade_required') {
      showFirmwareModal.value = true
    }
  } catch {
    // Firmware checks are advisory and must not block configuration.
  }
}

onMounted(async () => {
  await Promise.all([refreshPorts(), loadConfig(), recheckFirmware(false)])
})
</script>

<template>
  <div class="config-workspace">
    <ConfigSectionNav v-model="activeSection" />

    <main class="section-content">
      <section
        v-if="activeSection === 'local'"
        class="card local-panel"
        data-testid="local-device-panel"
        aria-labelledby="local-device-title"
      >
        <header class="panel-header">
          <h2 id="local-device-title">本地设备</h2>
          <span :class="['badge', deviceStatus.connected ? 'badge-ok' : 'badge-err']">
            {{ deviceStatus.connected ? '已连接' : '未连接' }}
          </span>
        </header>

        <div class="form-row">
          <label class="form-label" for="local-port">串口</label>
          <select id="local-port" v-model="localPort" class="form-select" data-testid="local-port" @change="saveLocalConfig">
            <option value="">自动检测</option>
            <option v-for="port in portOptions" :key="port.value" :value="port.value">
              {{ port.label }}
            </option>
          </select>
          <button
            class="btn btn-sm icon-button"
            type="button"
            title="刷新串口"
            data-testid="refresh-ports"
            :disabled="portsLoading"
            @click="refreshPorts"
          >
            <RefreshCw :size="14" aria-hidden="true" />
          </button>
          <button
            class="btn btn-sm icon-command"
            type="button"
            data-testid="auto-port"
            :disabled="portsLoading"
            @click="autoDiscover"
          >
            <Search :size="14" aria-hidden="true" />
            自动
          </button>
        </div>

        <div class="form-row">
          <label class="form-label" for="swd-clock">SWD 时钟</label>
          <input
            id="swd-clock"
            v-model="config.swd_clock"
            type="number"
            min="1"
            max="10000000"
            step="1"
            class="form-input"
            data-testid="swd-clock"
            placeholder="如 1000000"
            @change="saveLocalConfig"
          />
        </div>

        <div class="local-actions">
          <span class="auto-save-state" data-testid="local-auto-save">
            {{ localSaveState === 'saving' ? '自动保存中...' : localSaveState === 'saved' ? '已自动保存' : '修改后自动保存' }}
          </span>
          <button
            class="btn btn-primary icon-command"
            type="button"
            data-testid="connect-local"
            :disabled="connecting || deviceStatus.connected"
            @click="connectLocal"
          >
            <Usb :size="15" aria-hidden="true" />
            {{ connecting ? '连接中...' : '连接设备' }}
          </button>
          <button
            class="btn icon-command"
            type="button"
            data-testid="disconnect-local"
            :disabled="disconnecting || !deviceStatus.connected"
            @click="disconnectLocal"
          >
            <Unplug :size="15" aria-hidden="true" />
            {{ disconnecting ? '断开中...' : '断开' }}
          </button>
        </div>

      </section>

      <FileSourcesPanel
        v-else-if="activeSection === 'files'"
        :symbol-path="settings.symbolPath"
        :symbol-display-path="settings.symbolDisplayPath"
        :map-path="settings.mapPath"
        :map-display-path="settings.mapDisplayPath"
        :connected="deviceStatus.connected"
        :symbol-status="deviceStatus.axf"
        :browsing="browsingFiles"
        :parsing="parsingSymbols"
        @update:symbol-path="updateFilePath('symbol', $event)"
        @update:map-path="updateFilePath('map', $event)"
        @browse-symbol="browseSymbolFile"
        @browse-map="browseMapFile"
        @parse="parseSymbols"
      />

      <section v-else-if="activeSection === 'remote'" class="card remote-panel">
        <header class="panel-header">
          <h2>远程连接</h2>
          <span :class="['badge', wsConnected ? 'badge-ok' : 'badge-err']">
            {{ wsConnected ? '已连接' : '未连接' }}
          </span>
        </header>
        <div class="form-row">
          <label class="form-label" for="remote-url">服务器地址</label>
          <input id="remote-url" v-model="remoteUrl" class="form-input" data-testid="remote-url" placeholder="ws://192.168.1.100:8765" />
        </div>
        <div class="form-row">
          <label class="form-label" for="remote-token">认证 Token</label>
          <input id="remote-token" v-model="remoteToken" class="form-input" data-testid="remote-token" type="password" placeholder="可选" />
        </div>
        <div class="panel-actions">
          <button class="btn btn-primary" type="button" data-testid="connect-remote" :disabled="wsConnecting" @click="connectRemote">连接</button>
          <button class="btn" type="button" data-testid="disconnect-remote" :disabled="!wsConnected" @click="wsDisconnect">断开</button>
        </div>
      </section>

      <section v-else class="card serve-panel">
        <header class="panel-header"><h2>启动服务</h2></header>
        <div class="alert alert-info">在本地启动 MKLink 远程服务，供其他客户端连接。</div>
        <div class="form-row">
          <label class="form-label" for="serve-host">绑定地址</label>
          <input id="serve-host" v-model="serveConfig.host" class="form-input" data-testid="serve-host" />
        </div>
        <div class="form-row">
          <label class="form-label" for="serve-port">端口</label>
          <input id="serve-port" v-model.number="serveConfig.port" class="form-input" data-testid="serve-port" type="number" />
        </div>
        <div class="form-row">
          <label class="form-label" for="serve-token">Token</label>
          <input id="serve-token" v-model="serveConfig.token" class="form-input" data-testid="serve-token" type="password" placeholder="可选" />
        </div>
        <div class="panel-actions">
          <button class="btn btn-primary" type="button" data-testid="launch-server" :disabled="launching" @click="launchServer">启动服务</button>
        </div>
      </section>
    </main>

    <div
      v-if="firmwareCheck?.status === 'upgrade_required'"
      class="firmware-banner"
      data-testid="firmware-warning"
    >
      <TriangleAlert :size="18" aria-hidden="true" />
      <span>探针固件需要升级</span>
      <button class="btn btn-sm" type="button" @click="showFirmwareModal = true">查看升级步骤</button>
      <button class="btn btn-sm" type="button" @click="recheckFirmware(true)">重新检测</button>
    </div>

    <FirmwareUpdateModal
      v-if="showFirmwareModal && firmwareCheck"
      :check="firmwareCheck"
      @close="showFirmwareModal = false"
      @recheck="recheckFirmware(true)"
    />
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
}

.local-panel,
.remote-panel,
.serve-panel {
  min-height: 270px;
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
  background: #fef3c7;
  color: #7c4a03;
}

.firmware-banner span {
  margin-right: auto;
}

@media (max-width: 760px) {
  .config-workspace {
    grid-template-columns: 1fr;
  }

  .local-actions,
  .panel-actions {
    margin-left: 0;
    flex-wrap: wrap;
  }

  .firmware-banner {
    grid-column: 1;
    flex-wrap: wrap;
  }
}
</style>
