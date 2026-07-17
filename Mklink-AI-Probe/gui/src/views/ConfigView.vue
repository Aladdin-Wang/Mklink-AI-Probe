<template>
  <div>
    <!-- 顶层 Tab -->
    <div class="tabs-bar" style="margin-bottom:20px">
      <button :class="['tab-btn', { active: topTab === 'config' }]" @click="topTab = 'config'">配置</button>
      <button :class="['tab-btn', { active: topTab === 'connect' }]" @click="topTab = 'connect'">连接</button>
    </div>

    <!-- ==================== 配置 Tab ==================== -->
    <template v-if="topTab === 'config'">
      <!-- 全局状态栏 -->
      <GlobalConfigStatusBar
        :device-status="deviceStatus"
        :config-status="configStatus"
        :microkeen="microkeen"
      />

      <!-- Zone 1: 项目概览 -->
      <section class="config-zone">
        <h3 class="zone-title">项目概览</h3>
        <ProjectDirectoryCard
          v-model="projectRoot"
          :applying="applyingRoot"
          :initing="initing"
          :browser-open="browserOpen"
          :init-result="initResult"
          :root-error="rootError"
          @applied="applyProjectRoot"
          @toggle-browser="toggleBrowser"
          @init-project="doProjectInit"
          @clear-init-result="initResult = null"
        >
          <template #browser>
            <!-- 内联目录浏览器 -->
            <div v-if="browserOpen" class="browser-panel">
              <div class="drive-bar">
                <button
                  v-for="d in drives" :key="d"
                  :class="['drive-btn', { active: browserCurrent.startsWith(d) }]"
                  @click="navigateDrive(d)"
                >{{ d }}</button>
              </div>
              <div class="addr-bar">
                <button class="btn btn-sm" @click="browseUp" :disabled="!browserParent">上级</button>
                <div class="breadcrumb">
                  <template v-for="(seg, i) in pathSegments" :key="i">
                    <span class="bc-sep" v-if="i > 0">›</span>
                    <span class="bc-item" @click="browseToSegment(i)">{{ seg }}</span>
                  </template>
                </div>
              </div>
              <div class="dir-list">
                <div v-for="d in browserDirs" :key="d.path" class="dir-item" @click="browseInto(d.path)">
                  <span class="dir-icon">📁</span> {{ d.name }}
                </div>
                <div v-if="!browserDirs.length" class="dir-empty">此目录无子目录</div>
              </div>
              <div class="browser-footer">
                <span class="footer-path">{{ browserCurrent }}</span>
                <button class="btn btn-primary btn-sm" @click="selectCurrentDir">选择此目录</button>
              </div>
            </div>
          </template>
        </ProjectDirectoryCard>

        <div class="grid-2" style="gap:12px">
          <ProjectStatusCard
            :project-info="projectInfo"
            :config-status="configStatus"
            :microkeen="microkeen"
          />
          <HistoryCard
            :current-path="projectRoot"
            @select="selectHistoryProject"
          />
        </div>
      </section>

      <!-- Zone 2: 设备连接 -->
      <section class="config-zone">
        <h3 class="zone-title">设备连接</h3>
        <div class="grid-2">
          <div class="card">
            <div class="card-title">设备配置</div>
            <div class="form-row">
              <span class="form-label">串口</span>
              <select class="form-select" v-model="config.com_port">
                <option value="">自动检测</option>
                <option v-for="p in portOptions" :key="p.value" :value="p.value">{{ p.label }}</option>
              </select>
              <button class="btn btn-sm" @click="refreshPorts" :disabled="portsLoading">刷新</button>
              <button class="btn btn-sm btn-primary" @click="autoDiscover">自动</button>
            </div>
            <div class="form-row">
              <span class="form-label">MCU 类型</span>
              <select class="form-select" v-model="config.mcu_key">
                <option value="">选择 MCU</option>
                <option v-for="m in mcuOptions" :key="m.value" :value="m.value">{{ m.label }}</option>
              </select>
            </div>
            <div class="form-row">
              <span class="form-label">SWD 时钟</span>
              <input class="form-input" v-model="config.swd_clock" placeholder="如 1000000" />
            </div>
            <div class="form-row">
              <span class="form-label"></span>
              <div class="btn-group">
                <button class="btn btn-primary" @click="saveConfig" :disabled="saving">保存配置</button>
                <button class="btn" @click="loadConfig" :disabled="loading">重新加载</button>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-title" style="display:flex;align-items:center;gap:8px">
              AXF 符号表
              <span :class="['status-dot', deviceStatus.axf?.loaded ? 'dot-ok' : 'dot-warn']"></span>
            </div>
            <div v-if="deviceStatus.axf?.loaded" class="axf-summary">
              <span class="badge badge-ok">已加载</span>
              <span class="axf-stat">{{ deviceStatus.axf.variable_count }} 变量 · {{ deviceStatus.axf.struct_count }} 结构体 · {{ deviceStatus.axf.enum_count }} 枚举</span>
            </div>
            <div v-else class="axf-summary">
              <span class="badge badge-warn">未加载</span>
              <span class="axf-hint">SuperWatch/符号表功能需要 AXF 解析</span>
            </div>
            <div class="form-row" style="margin-top:8px">
              <span class="form-label">AXF 路径</span>
              <input class="form-input path-input" v-model="axfPath" placeholder=".axf 或 .elf 文件路径" />
            </div>
            <div class="form-row">
              <span class="form-label"></span>
              <button class="btn btn-primary" @click="doParseAxf" :disabled="parsingAxf || !deviceStatus.connected">
                {{ parsingAxf ? '解析中...' : (deviceStatus.axf?.loaded ? '重新解析' : '解析符号表') }}
              </button>
              <span v-if="!deviceStatus.connected" style="font-size:12px;color:var(--dim)">需先连接设备</span>
            </div>
            <div v-if="deviceStatus.axf?.axf_path" class="axf-path">{{ deviceStatus.axf.axf_path }}</div>
          </div>
        </div>
      </section>

      <!-- Zone 3: 高级配置 (RTT, collapsible) -->
      <section class="config-zone">
        <h3 class="zone-title collapsible-header" @click="advancedOpen = !advancedOpen">
          高级配置 (RTT)
          <span class="collapse-icon">{{ advancedOpen ? '▼' : '▶' }}</span>
        </h3>
        <div v-show="advancedOpen" class="card">
          <div class="form-row">
            <span class="form-label">RTT 地址</span>
            <input class="form-input" v-model="rttConfig.rtt_addr" placeholder="如 0x20000E24" style="font-family:var(--font-mono);font-size:12px" />
            <button class="btn btn-sm btn-primary" @click="autoFindRtt" :disabled="rttFinding">{{ rttFinding ? '搜索中...' : '自动检测' }}</button>
          </div>
          <div class="form-row">
            <span class="form-label">控制块存储方式</span>
            <select class="form-select" v-model.number="rttConfig.rtt_storage_mode" style="width:240px;flex:none">
              <option :value="0">动态搜寻（PC 从 MAP/ELF 自动检测）</option>
              <option :value="1">静态编译（C 宏固定地址）</option>
            </select>
          </div>
          <div v-if="rttConfig.rtt_storage_mode === 1" class="alert alert-info" style="margin-top:4px;font-size:12px">
            静态模式：需在目标 C 代码中用 <code>SEGGER_RTT_SECTION</code> 宏把控制块固定到已知地址，并在上方"自动检测"或手填对应的精确地址。<br>
            探针固件将按 <code>search_size=0</code> 直接访问该地址，不再扫描。
          </div>
          <div class="form-row">
            <span class="form-label">通道</span>
            <input class="form-input" type="number" v-model.number="rttConfig.channel" style="width:80px;flex:none" />
          </div>
          <div class="form-row">
            <span class="form-label">搜索范围</span>
            <input class="form-input" type="number" v-model.number="rttConfig.search_size" placeholder="1024" style="width:100px;flex:none" />
          </div>
          <div v-if="rttFindResult" class="alert" :class="rttFindResult.found ? 'alert-success' : 'alert-warn'" style="margin-top:8px">
            <template v-if="rttFindResult.found">
              找到 RTT 地址: <strong>{{ rttFindResult.addr }}</strong> (来源: {{ rttFindResult.source }})
            </template>
            <template v-else>
              未找到 RTT 地址: {{ rttFindResult.details?.join('; ') }}
            </template>
          </div>
          <div class="form-row" style="margin-top:8px">
            <span class="form-label"></span>
            <button class="btn btn-primary" @click="saveRttConfig" :disabled="savingRtt">保存 RTT 配置</button>
          </div>
        </div>
      </section>
    </template>

    <!-- ==================== 连接 Tab ==================== -->
    <template v-if="topTab === 'connect'">
      <div class="card">
        <div class="card-title">设备连接</div>
        <div class="tabs-bar">
          <button :class="['tab-btn', { active: connTab === 'local' }]" @click="connTab = 'local'">本地设备</button>
          <button :class="['tab-btn', { active: connTab === 'remote' }]" @click="connTab = 'remote'">远程服务器</button>
          <button :class="['tab-btn', { active: connTab === 'serve' }]" @click="connTab = 'serve'">启动服务</button>
        </div>

        <!-- 本地设备 -->
        <div v-if="connTab === 'local'">
          <div class="form-row">
            <span class="form-label">串口</span>
            <select class="form-select" v-model="localReq.port">
              <option value="">自动检测</option>
              <option v-for="p in portOptions" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </div>
          <div class="form-row">
            <span class="form-label">AXF/ELF</span>
            <input class="form-input" v-model="localReq.axf" placeholder="AXF/ELF 文件路径" />
          </div>
          <div class="form-row">
            <span class="form-label">MCU 提示</span>
            <input class="form-input" v-model="localReq.mcu" placeholder="如 N32G435" />
          </div>
          <div class="form-row">
            <span class="form-label"></span>
            <div class="btn-group">
              <button class="btn btn-primary" @click="connectLocal" :disabled="connecting || deviceStatus.connected">连接设备</button>
              <button class="btn" @click="disconnect" :disabled="disconnecting || !deviceStatus.connected">断开</button>
            </div>
          </div>
        </div>

        <!-- 远程服务器 -->
        <div v-if="connTab === 'remote'">
          <div class="form-row">
            <span class="form-label">服务器地址</span>
            <input class="form-input" v-model="remoteUrl" placeholder="ws://192.168.1.100:8765" />
          </div>
          <div class="form-row">
            <span class="form-label">认证 Token</span>
            <input class="form-input" v-model="remoteToken" type="password" placeholder="可选" />
          </div>
          <div class="form-row">
            <span class="form-label"></span>
            <div class="btn-group">
              <button class="btn btn-primary" @click="connectRemote" :disabled="wsConnecting">连接</button>
              <button class="btn" @click="disconnectRemote" :disabled="!wsConnected">断开</button>
            </div>
          </div>
        </div>

        <!-- 启动服务 -->
        <div v-if="connTab === 'serve'">
          <div class="alert alert-info">在本地启动 MKLink 远程服务，供其他客户端连接。</div>
          <div class="form-row">
            <span class="form-label">绑定地址</span>
            <input class="form-input" v-model="serveConfig.host" />
          </div>
          <div class="form-row">
            <span class="form-label">端口</span>
            <input class="form-input" type="number" v-model.number="serveConfig.port" />
          </div>
          <div class="form-row">
            <span class="form-label">Token</span>
            <input class="form-input" v-model="serveConfig.token" type="password" placeholder="可选" />
          </div>
          <div class="form-row">
            <span class="form-label"></span>
            <button class="btn btn-primary" @click="launchServer" :disabled="launching">启动服务</button>
          </div>
        </div>
      </div>

      <!-- 设备状态 -->
      <div class="card">
        <div class="card-title">设备状态</div>
        <table class="desc-table">
          <tr>
            <th>连接状态</th>
            <td><span :class="['badge', deviceStatus.connected ? 'badge-ok' : 'badge-err']">{{ deviceStatus.connected ? '已连接' : '未连接' }}</span></td>
            <th>运行状态</th>
            <td>{{ deviceStatus.state }}</td>
          </tr>
          <tr>
            <th>MCU</th>
            <td>{{ deviceStatus.mcu || '—' }}</td>
            <th>IDCODE</th>
            <td>{{ deviceStatus.idcode || '—' }}</td>
          </tr>
          <tr>
            <th>串口</th>
            <td colspan="3">{{ deviceStatus.port || '—' }}</td>
          </tr>
        </table>
      </div>
    </template>

    <!-- 探针固件升级警告条 -->
    <div v-if="firmwareCheck?.status === 'upgrade_required'" class="firmware-banner">
      <span>⚠ 探针固件需要升级</span>
      <button class="btn btn-sm" @click="showFirmwareModal = true">查看升级步骤</button>
      <button class="btn btn-sm" @click="recheckFirmware">重新检测</button>
    </div>

    <!-- 模态 -->
    <FirmwareUpdateModal
      v-if="showFirmwareModal && firmwareCheck"
      :check="firmwareCheck"
      @close="showFirmwareModal = false"
      @recheck="recheckFirmware"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useMklinkApi } from '../composables/useMklinkApi'
import { useMklinkWs } from '../composables/useMklinkWs'
import { useToast } from '../composables/useToast'
import { useProjectHistory } from '../composables/useProjectHistory'
import type { PortInfo, McuProfile, ProjectConfig, ProjectInfo, ConfigStatus, MicrokeenInfo } from '../types/mklink'

import GlobalConfigStatusBar from '../components/config/GlobalConfigStatusBar.vue'
import ProjectDirectoryCard from '../components/config/ProjectDirectoryCard.vue'
import ProjectStatusCard from '../components/config/ProjectStatusCard.vue'
import HistoryCard from '../components/config/HistoryCard.vue'
import FirmwareUpdateModal from '../components/config/FirmwareUpdateModal.vue'
import type { ProbeFirmwareCheck } from '../types/mklink'

const {
  deviceStatus, listPorts, discoverPort, getProfiles, getConfig, updateConfig,
  getConfigStatus, getProjectInfo, getMicrokeenInfo, connectDevice, disconnectDevice,
  getRttConfig, updateRttConfig, setProjectRoot, getProjectRoot, browseProjectRoot, findRtt,
  parseAxf, probeFirmwareCheck,
} = useMklinkApi()
const { wsConnected, connect: wsConnect, disconnect: wsDisconnect } = useMklinkWs()
const toast = useToast()
const { addEntry } = useProjectHistory()

const API_BASE = import.meta.env.VITE_MKLINK_API || ''

// ---- Tab state ----
const topTab = ref('config')
const connTab = ref('local')
const advancedOpen = ref(false)

// ---- 配置 Tab ----
const projectRoot = ref('')
const rootError = ref('')
const applyingRoot = ref(false)
const config = ref<ProjectConfig>({})
const projectInfo = ref<ProjectInfo | null>(null)
const configStatus = ref<ConfigStatus | null>(null)
const microkeen = ref<MicrokeenInfo | null>(null)
const portOptions = ref<{ label: string; value: string }[]>([])
const mcuOptions = ref<{ label: string; value: string }[]>([])
const portsLoading = ref(false)
const saving = ref(false)
const loading = ref(false)

const browserOpen = ref(false)
const browserCurrent = ref('')
const browserParent = ref('')
const browserDirs = ref<{ name: string; path: string }[]>([])
const drives = ref<string[]>([])

const pathSegments = computed(() => {
  const p = browserCurrent.value.replace(/\\/g, '/')
  return p.split('/').filter(Boolean)
})

async function applyProjectRoot() {
  applyingRoot.value = true
  rootError.value = ''
  initResult.value = null
  try {
    await setProjectRoot(projectRoot.value)
    await addEntry(projectRoot.value)
    await loadConfig()
  } catch (e: any) {
    rootError.value = e.message
  } finally { applyingRoot.value = false }
}

const initing = ref(false)
const initResult = ref<{ output?: string; error?: string } | null>(null)

// ---- 探针固件升级状态 ----
const showFirmwareModal = ref(false)
const firmwareCheck = ref<ProbeFirmwareCheck | null>(null)

async function recheckFirmware() {
  try {
    const result = await probeFirmwareCheck()
    firmwareCheck.value = result
    if (result.status === 'upgrade_required') {
      showFirmwareModal.value = true
    }
  } catch (e: any) {
    // silent
  }
}

async function doProjectInit() {
  if (!projectRoot.value) {
    rootError.value = '请先设置项目目录'
    return
  }
  initing.value = true
  initResult.value = null
  try {
    await setProjectRoot(projectRoot.value)
    const res = await fetch(`${API_BASE}/api/project-init`, { method: 'POST' })
    const data = await res.json()
    initResult.value = data
    firmwareCheck.value = data.firmware_check ?? null
    if (firmwareCheck.value?.status === 'upgrade_required') {
      showFirmwareModal.value = true
    }
    if (data.success) {
      toast.success('工程初始化完成')
      await loadConfig()
    } else {
      toast.error('初始化失败: ' + (data.error || '未知错误'))
    }
  } catch (e: any) {
    initResult.value = { error: e.message }
    toast.error('初始化失败: ' + e.message)
  } finally {
    initing.value = false
  }
}

function toggleBrowser() {
  if (browserOpen.value) {
    browserOpen.value = false
  } else {
    browserOpen.value = true
    loadBrowserDir(projectRoot.value || 'C:\\')
  }
}

async function loadBrowserDir(path: string) {
  try {
    const data = await browseProjectRoot(path)
    browserCurrent.value = data.current
    browserParent.value = data.parent
    browserDirs.value = data.dirs
    if (data.drives?.length) drives.value = data.drives
  } catch { /* ignore */ }
}

function navigateDrive(drive: string) { loadBrowserDir(drive + '\\') }
function browseUp() { if (browserParent.value) loadBrowserDir(browserParent.value) }
function browseInto(path: string) { loadBrowserDir(path) }

function browseToSegment(index: number) {
  const segs = pathSegments.value.slice(0, index + 1)
  let p = segs[0]
  for (let i = 1; i < segs.length; i++) p += '\\' + segs[i]
  loadBrowserDir(p)
}

function selectCurrentDir() {
  projectRoot.value = browserCurrent.value
  applyProjectRoot()
}

async function selectHistoryProject(path: string) {
  projectRoot.value = path
  await applyProjectRoot()
}

async function refreshPorts() {
  portsLoading.value = true
  try {
    const ports: PortInfo[] = await listPorts()
    portOptions.value = ports.map((p) => ({
      label: `${p.device} — ${p.description} (${p.manufacturer})`,
      value: p.device,
    }))
  } finally { portsLoading.value = false }
}

async function autoDiscover() {
  portsLoading.value = true
  try {
    const result = await discoverPort()
    if (result.port) config.value.com_port = result.port
  } finally { portsLoading.value = false }
}

async function saveConfig() {
  saving.value = true
  try { await updateConfig(config.value) } finally { saving.value = false }
}

async function loadConfig() {
  loading.value = true
  try {
    config.value = await getConfig()
    projectInfo.value = await getProjectInfo()
    configStatus.value = await getConfigStatus()
    microkeen.value = await getMicrokeenInfo()
    rttConfig.value = await getRttConfig()
    // 旧配置无 rtt_storage_mode 时默认为 0（动态搜寻），向后兼容
    if (rttConfig.value.rtt_storage_mode === undefined ||
        rttConfig.value.rtt_storage_mode === null) {
      rttConfig.value.rtt_storage_mode = 0
    }
    // 自动填充 AXF 路径（如果 project_info.json 中有）
    const axf = projectInfo.value?.axf_path
    if (axf) {
      localReq.axf = axf
      axfPath.value = axf
    }
  } finally { loading.value = false }
}

// ---- RTT Config ----
const rttConfig = ref<any>({})
const rttFinding = ref(false)
const rttFindResult = ref<any>(null)
const savingRtt = ref(false)

async function autoFindRtt() {
  rttFinding.value = true
  rttFindResult.value = null
  try {
    rttFindResult.value = await findRtt()
    if (rttFindResult.value.found) {
      rttConfig.value.rtt_addr = rttFindResult.value.addr
    }
  } catch (e: any) {
    rttFindResult.value = { found: false, details: [e.message] }
  } finally { rttFinding.value = false }
}

async function saveRttConfig() {
  savingRtt.value = true
  try { await updateRttConfig(rttConfig.value) } finally { savingRtt.value = false }
}

// ---- 连接 Tab ----
const localReq = reactive({ port: '', axf: '', mcu: '' })
const remoteUrl = ref('ws://127.0.0.1:8765')
const remoteToken = ref('')
const serveConfig = reactive({ host: '127.0.0.1', port: 8765, token: '' })
const connecting = ref(false)
const disconnecting = ref(false)
const wsConnecting = ref(false)
const launching = ref(false)
const axfPath = ref('')
const parsingAxf = ref(false)

async function doParseAxf() {
  parsingAxf.value = true
  try {
    const result = await parseAxf(axfPath.value || undefined) as any
    if (result.loaded) {
      toast.success(`AXF 解析成功: ${result.variable_count} 变量`)
      if (result.axf_path) localReq.axf = result.axf_path
    } else {
      toast.error('AXF 解析失败')
    }
  } catch (e: any) {
    toast.error('AXF 解析失败: ' + e.message)
  } finally {
    parsingAxf.value = false
  }
}

async function connectLocal() {
  connecting.value = true
  try {
    await connectDevice({
      port: localReq.port || config.value.com_port || undefined,
      axf: localReq.axf || undefined,
      mcu: localReq.mcu || config.value.mcu_key || undefined,
    })
  } catch (e: any) { toast.error('连接失败: ' + e.message) }
  finally { connecting.value = false }
}

async function disconnect() {
  disconnecting.value = true
  try { await disconnectDevice() } finally { disconnecting.value = false }
}

async function connectRemote() {
  wsConnecting.value = true
  try { wsConnect(remoteToken.value || undefined, remoteUrl.value || undefined) } finally { wsConnecting.value = false }
}

function disconnectRemote() { wsDisconnect() }

function launchServer() {
  launching.value = true
  window.open(`http://${serveConfig.host}:${serveConfig.port}/docs`, '_blank')
  launching.value = false
}

onMounted(async () => {
  try {
    const data = await getProjectRoot()
    projectRoot.value = data.project_root || ''
  } catch { /* ignore */ }

  await Promise.all([refreshPorts(), loadConfig()])
  try {
    const profiles: McuProfile[] = await getProfiles()
    mcuOptions.value = profiles.map((p) => ({ label: `${p.name} (${p.key})`, value: p.key }))
  } catch { /* ignore */ }
})
</script>

<style scoped>
/* Zone layout */
.config-zone {
  margin-bottom: 20px;
}
.zone-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--dim);
  margin: 0 0 10px 0;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.collapsible-header {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  user-select: none;
}
.collapsible-header:hover {
  color: var(--accent);
}
.collapse-icon {
  font-size: 11px;
}

.path-input {
  font-family: var(--font-mono);
  font-size: 12px;
}

/* 内联目录浏览器 */
.browser-panel {
  margin-top: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.drive-bar {
  display: flex;
  gap: 0;
  padding: 6px 8px;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.drive-btn {
  background: none;
  border: 1px solid transparent;
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
  cursor: pointer;
  border-radius: 4px;
  font-family: var(--font-mono);
  transition: all 0.12s;
}
.drive-btn:hover { background: var(--surface); border-color: var(--border); color: var(--fg); }
.drive-btn.active { background: #f3ece6; color: var(--accent); border-color: var(--accent); font-weight: 600; }

.addr-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--surface);
  border-bottom: 1px solid var(--border-subtle);
}
.breadcrumb {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 2px;
  overflow-x: auto;
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--dim);
}
.bc-sep { color: var(--border); margin: 0 2px; }
.bc-item {
  cursor: pointer;
  padding: 1px 4px;
  border-radius: 3px;
  white-space: nowrap;
  color: var(--muted);
}
.bc-item:hover { background: var(--bg); color: var(--accent); }

.dir-list {
  max-height: 200px;
  overflow-y: auto;
  padding: 4px 0;
}
.dir-item {
  padding: 5px 14px;
  cursor: pointer;
  font-size: 13px;
  color: var(--fg);
  display: flex;
  align-items: center;
  gap: 6px;
  transition: background 0.1s;
}
.dir-item:hover { background: var(--bg); color: var(--accent); }
.dir-icon { font-size: 13px; flex-shrink: 0; }
.dir-empty { padding: 16px; text-align: center; color: var(--dim); font-size: 12px; }

.browser-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--bg);
  border-top: 1px solid var(--border);
}
.footer-path {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* AXF 符号表 */
.axf-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}
.axf-stat {
  font-size: 12px;
  color: var(--muted);
}
.axf-hint {
  font-size: 12px;
  color: var(--warn);
}
.axf-path {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--dim);
  margin-top: 6px;
  word-break: break-all;
}
.badge-warn {
  background: #f5f0e1;
  color: var(--warn);
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.dot-ok { background: var(--success); }
.dot-warn { background: var(--warn); }

.alert ul { margin: 4px 0 0 16px; padding: 0; }
.alert li { margin: 2px 0; font-size: 12px; }

/* 探针固件升级警告条 */
.firmware-banner {
  background: #fef3c7;
  border: 1px solid #f59e0b;
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0;
  border-radius: 4px;
}
.firmware-banner button { margin-left: auto; }
.firmware-banner button + button { margin-left: 0; }
</style>
