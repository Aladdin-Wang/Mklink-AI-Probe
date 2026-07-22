<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { RefreshCw, Search, Save, TriangleAlert, Unplug, Usb } from '@lucide/vue'
import { useMklinkApi } from '../composables/useMklinkApi'
import { useMklinkWs } from '../composables/useMklinkWs'
import { useToast } from '../composables/useToast'
import { useSymbolCatalog } from '../composables/useSymbolCatalog'
import {
  isSymbolFilePath,
  loadDesktopSettings,
  saveDesktopSettings,
  type DesktopSettings,
} from '../lib/desktopSettings'
import { pickMapFile, pickSymbolFile, type PickedFile } from '../lib/filePicker'
import type { FileSourceKind, PortInfo, ProbeFirmwareCheck, ProjectConfig } from '../types/mklink'
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
const savingFiles = ref(false)
const parsingSymbols = ref(false)

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
    if (result.port) localPort.value = result.port
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
  try {
    config.value = await updateConfig({
      ...config.value,
      com_port: localPort.value || undefined,
      swd_clock: rawClock || undefined,
    })
    toast.success('设备配置已保存')
  } catch (error: any) {
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

async function selectedFilePath(kind: FileSourceKind, selected: PickedFile): Promise<string | null> {
  if (!selected) return null
  if (typeof selected === 'string') return selected
  const uploaded = await uploadFileSource(kind, selected)
  return uploaded.path
}

async function browseSymbolFile() {
  browsingFiles.value = true
  try {
    const path = await selectedFilePath('symbol', await pickSymbolFile())
    if (path) settings.value.symbolPath = path
  } catch (error: any) {
    toast.error('加载 AXF / ELF 文件失败: ' + error.message)
  } finally {
    browsingFiles.value = false
  }
}

async function browseMapFile() {
  browsingFiles.value = true
  try {
    const path = await selectedFilePath('map', await pickMapFile())
    if (path) settings.value.mapPath = path
  } catch (error: any) {
    toast.error('加载 MAP 文件失败: ' + error.message)
  } finally {
    browsingFiles.value = false
  }
}

function saveFilePaths() {
  savingFiles.value = true
  try {
    saveDesktopSettings(window.localStorage, settings.value)
    toast.success('文件路径已保存')
  } catch (error: any) {
    toast.error('保存文件路径失败: ' + error.message)
  } finally {
    savingFiles.value = false
  }
}

async function parseSymbols() {
  if (!deviceStatus.value.connected || !isSymbolFilePath(settings.value.symbolPath)) return
  parsingSymbols.value = true
  try {
    const result = await parseAxf(settings.value.symbolPath.trim()) as {
      loaded?: boolean
      variable_count?: number
    }
    if (result.loaded) {
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
          <select id="local-port" v-model="localPort" class="form-select" data-testid="local-port">
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
          />
        </div>

        <div class="local-actions">
          <button
            class="btn icon-command"
            type="button"
            data-testid="save-local"
            :disabled="savingLocal"
            @click="saveLocalConfig"
          >
            <Save :size="15" aria-hidden="true" />
            {{ savingLocal ? '保存中...' : '保存配置' }}
          </button>
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
        :map-path="settings.mapPath"
        :connected="deviceStatus.connected"
        :symbol-status="deviceStatus.axf"
        :browsing="browsingFiles"
        :saving="savingFiles"
        :parsing="parsingSymbols"
        @update:symbol-path="settings.symbolPath = $event"
        @update:map-path="settings.mapPath = $event"
        @browse-symbol="browseSymbolFile"
        @browse-map="browseMapFile"
        @save="saveFilePaths"
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
