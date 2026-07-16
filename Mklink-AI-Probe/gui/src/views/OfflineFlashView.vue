<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useOfflineFlashApi } from '../composables/useOfflineFlashApi'
import { useOnlineFlashApi } from '../composables/useOnlineFlashApi'
import type { TargetRecord } from '../types/onlineFlash'
import type {
  OfflineAlgorithmCandidate,
  OfflineAlgorithmConfig,
  OfflineConfigPayload,
  OfflineDiskStatus,
  OfflineFirmwareConfig,
  OfflinePreview,
} from '../types/offlineFlash'

interface AlgorithmRow extends Omit<OfflineAlgorithmCandidate, 'source_kind'> {
  source_kind: 'upload' | 'pack' | 'profile' | 'existing'
  file: File | null
}

interface FirmwareRow {
  id: string
  file: File
  file_name: string
  format: 'bin' | 'hex'
  base_address: string
  algorithm_id: string
}

const offline = useOfflineFlashApi()
const online = useOnlineFlashApi()

const disk = ref<OfflineDiskStatus | null>(null)
const model = ref<'auto' | 'V2' | 'V3' | 'V4'>('auto')
const detectedModel = ref<'V2' | 'V3' | 'V4' | ''>('')
const detectedVersion = ref('')
const scriptName = ref('factory-download.py')
const automaticCount = ref(1)
const idcodeTimeout = ref(10000)
const swdClock = ref(10000000)

const algorithms = ref<AlgorithmRow[]>([])
const firmwares = ref<FirmwareRow[]>([])
const targetQuery = ref('STM32F103RC')
const targets = ref<TargetRecord[]>([])
const targetBusy = ref(false)
const operationBusy = ref(false)
const error = ref('')
const notice = ref('')
const preview = ref<OfflinePreview | null>(null)
const triggerLines = ref<string[]>([])
const deployedScriptName = ref('')

let sequence = 0
const nextId = (prefix: string) => `${prefix}-${++sequence}`

const effectiveModel = computed(() => model.value === 'auto' ? detectedModel.value : model.value)
const effectiveScriptName = computed(() => (
  effectiveModel.value === 'V2' || effectiveModel.value === 'V3'
    ? 'offline_download.py'
    : scriptName.value
))
const canBuild = computed(() => (
  !!effectiveModel.value
  && !!disk.value?.available
  && algorithms.value.length > 0
  && firmwares.value.length > 0
  && algorithms.value.every(item => item.source_kind !== 'upload' || item.file)
  && firmwares.value.every(item => item.file && item.algorithm_id)
))
const canTrigger = computed(() => (
  !!disk.value?.available
  && !!deployedScriptName.value
  && !operationBusy.value
))

watch(
  [model, scriptName, automaticCount, idcodeTimeout, swdClock, algorithms, firmwares],
  () => {
    deployedScriptName.value = ''
    triggerLines.value = []
  },
  { deep: true },
)

function message(value: unknown): string {
  return value instanceof Error ? value.message : String(value)
}

async function refreshDisk(): Promise<void> {
  try { disk.value = await offline.getStatus() }
  catch (value) { error.value = message(value) }
}

async function detectModel(): Promise<void> {
  operationBusy.value = true
  error.value = ''
  try {
    const result = await offline.detectModel()
    detectedModel.value = result.model
    detectedVersion.value = result.version
    if (result.model === 'V2') automaticCount.value = 1
  } catch (value) { error.value = message(value) }
  finally { operationBusy.value = false }
}

function modelChanged(): void {
  preview.value = null
  if (effectiveModel.value === 'V2') automaticCount.value = 1
}

async function searchTargets(): Promise<void> {
  targetBusy.value = true
  error.value = ''
  try { targets.value = await online.searchTargets(targetQuery.value, { limit: 30 }) }
  catch (value) { error.value = message(value) }
  finally { targetBusy.value = false }
}

function mergeAlgorithms(items: OfflineAlgorithmCandidate[]): void {
  for (const item of items) {
    const duplicate = algorithms.value.some(existing => (
      existing.file_name.toLowerCase() === item.file_name.toLowerCase()
      && existing.flash_base === item.flash_base
      && existing.ram_base === item.ram_base
    ))
    if (!duplicate) algorithms.value.push({ ...item, file: null })
  }
  if (algorithms.value.length === 1) {
    firmwares.value.forEach(item => { item.algorithm_id = algorithms.value[0].id })
  }
}

async function addTargetAlgorithms(target: TargetRecord): Promise<void> {
  targetBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    if (!target.installed) await online.installPack(target.part_number)
    const items = await offline.listAlgorithms(target.part_number)
    if (!items.length) throw new Error(`未找到 ${target.part_number} 的 FLM 算法`)
    mergeAlgorithms(items)
    notice.value = `已加入 ${items.length} 个 ${target.part_number} 算法候选`
  } catch (value) { error.value = message(value) }
  finally { targetBusy.value = false }
}

function addManualFlm(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.flm')) {
    error.value = '下载算法必须是 .FLM 文件'
    return
  }
  const id = nextId('flm')
  algorithms.value.push({
    id,
    file_name: file.name,
    flash_base: '0x08000000',
    ram_base: '0x20000000',
    source_kind: 'upload',
    source_token: null,
    origin: '本地文件',
    available: true,
    on_probe: false,
    file,
  })
  if (algorithms.value.length === 1) {
    firmwares.value.forEach(item => { item.algorithm_id = id })
  }
}

function removeAlgorithm(index: number): void {
  const [removed] = algorithms.value.splice(index, 1)
  const fallback = algorithms.value[0]?.id || ''
  firmwares.value.forEach(item => {
    if (item.algorithm_id === removed.id) item.algorithm_id = fallback
  })
  preview.value = null
}

function addFirmware(event: Event): void {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  for (const file of files) {
    const suffix = file.name.split('.').pop()?.toLowerCase()
    if (suffix !== 'bin' && suffix !== 'hex') {
      error.value = '固件只支持 BIN 或 HEX'
      continue
    }
    firmwares.value.push({
      id: nextId('firmware'),
      file,
      file_name: file.name,
      format: suffix,
      base_address: suffix === 'bin' ? '0x08000000' : '',
      algorithm_id: algorithms.value[0]?.id || '',
    })
  }
  preview.value = null
}

function moveFirmware(index: number, delta: number): void {
  const target = index + delta
  if (target < 0 || target >= firmwares.value.length) return
  const rows = [...firmwares.value]
  ;[rows[index], rows[target]] = [rows[target], rows[index]]
  firmwares.value = rows
  preview.value = null
}

function buildRequest(): {
  payload: OfflineConfigPayload
  firmwareFiles: File[]
  flmFiles: File[]
} {
  const flmFiles: File[] = []
  const algorithmPayload: OfflineAlgorithmConfig[] = algorithms.value.map(item => {
    let uploadIndex: number | null = null
    if (item.source_kind === 'upload') {
      if (!item.file) throw new Error(`请选择 ${item.file_name} 的 FLM 文件`)
      uploadIndex = flmFiles.push(item.file) - 1
    }
    return {
      id: item.id,
      file_name: item.file_name,
      flash_base: item.flash_base,
      ram_base: item.ram_base,
      source_kind: item.source_kind,
      source_token: item.source_token,
      upload_index: uploadIndex,
    }
  })
  const firmwareFiles = firmwares.value.map(item => item.file)
  const firmwarePayload: OfflineFirmwareConfig[] = firmwares.value.map((item, index) => ({
    id: item.id,
    file_name: item.file_name,
    format: item.format,
    base_address: item.format === 'bin' ? item.base_address : null,
    algorithm_id: item.algorithm_id,
    upload_index: index,
  }))
  return {
    payload: {
      model: model.value,
      script_name: scriptName.value,
      auto_download_count: Number(automaticCount.value),
      wait_idcode_timeout_ms: Number(idcodeTimeout.value),
      swd_clock_hz: Number(swdClock.value),
      algorithms: algorithmPayload,
      firmwares: firmwarePayload,
    },
    firmwareFiles,
    flmFiles,
  }
}

async function generatePreview(): Promise<void> {
  operationBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    preview.value = await offline.preview(buildRequest().payload)
    detectedModel.value = preview.value.model
    notice.value = `已生成 ${preview.value.script_name}`
  } catch (value) { error.value = message(value) }
  finally { operationBusy.value = false }
}

async function deploy(): Promise<void> {
  operationBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    const request = buildRequest()
    const result = await offline.deploy(request.payload, request.firmwareFiles, request.flmFiles)
    detectedModel.value = result.model
    deployedScriptName.value = result.script_name
    notice.value = `已部署 ${result.files.length} 个文件，脚本 ${result.script_name}`
    await refreshDisk()
  } catch (value) { error.value = message(value) }
  finally { operationBusy.value = false }
}

async function triggerOffline(): Promise<void> {
  if (
    effectiveModel.value === 'V4'
    && deployedScriptName.value !== 'offline_download.py'
    && !window.confirm(`请先在 V4 下载器屏幕选择 ${deployedScriptName.value}，然后再触发测试。`)
  ) return
  operationBusy.value = true
  error.value = ''
  triggerLines.value = []
  try {
    const result = await offline.trigger()
    triggerLines.value = result.lines
    notice.value = result.status === 'completed' ? '脱机下载执行完成' : '脱机下载执行失败'
  } catch (value) { error.value = message(value) }
  finally { operationBusy.value = false }
}

onMounted(async () => {
  await Promise.all([refreshDisk(), detectModel(), searchTargets()])
})
</script>

<template>
  <div class="offline-page">
    <header class="status-strip">
      <div><span class="status-label">下载器</span><b>{{ detectedVersion || effectiveModel || '未识别' }}</b></div>
      <div><span class="status-label">U 盘</span><b :class="disk?.available ? 'ok' : 'bad'">{{ disk?.available ? disk.disk_path : '未发现' }}</b></div>
      <div><span class="status-label">脚本</span><b>{{ effectiveScriptName }}</b></div>
      <div class="status-actions">
        <button class="btn" :disabled="operationBusy" @click="detectModel">识别版本</button>
        <button class="btn" :disabled="operationBusy" @click="refreshDisk">刷新 U 盘</button>
      </div>
    </header>

    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="notice" class="alert alert-success">{{ notice }}</div>

    <div class="offline-workspace">
      <section class="work-panel target-panel">
        <div class="panel-heading"><h2>下载算法</h2><label class="btn btn-sm file-button">添加 FLM<input type="file" accept=".flm" @change="addManualFlm"></label></div>
        <div class="target-search">
          <input v-model="targetQuery" class="form-input" data-testid="offline-target-search" @keydown.enter="searchTargets">
          <button class="btn" :disabled="targetBusy" @click="searchTargets">搜索器件</button>
        </div>
        <div class="target-results">
          <button v-for="target in targets" :key="target.part_number" class="target-result" :disabled="targetBusy" @click="addTargetAlgorithms(target)">
            <span><b>{{ target.part_number }}</b><small>{{ target.vendor }}</small></span>
            <em>{{ target.installed ? '加入算法' : '下载 Pack' }}</em>
          </button>
        </div>
        <div class="algorithm-list">
          <div v-for="(item, index) in algorithms" :key="item.id" class="algorithm-row" data-testid="offline-algorithm-row">
            <div class="row-title"><input v-model="item.file_name" class="compact-input mono"><span>{{ item.origin }}</span><button class="icon-command" title="移除算法" @click="removeAlgorithm(index)">×</button></div>
            <label>Flash<input v-model="item.flash_base" class="compact-input mono"></label>
            <label>RAM<input v-model="item.ram_base" class="compact-input mono"></label>
          </div>
          <p v-if="!algorithms.length" class="empty-state">尚未配置 FLM</p>
        </div>
      </section>

      <section class="work-panel firmware-panel">
        <div class="panel-heading"><h2>烧录顺序</h2><label class="btn btn-sm file-button">添加固件<input type="file" multiple accept=".bin,.hex" @change="addFirmware"></label></div>
        <div class="firmware-list">
          <div v-for="(item, index) in firmwares" :key="item.id" class="firmware-row" data-testid="offline-firmware-row">
            <div class="sequence-number">{{ index + 1 }}</div>
            <div class="firmware-fields">
              <input v-model="item.file_name" class="compact-input mono file-name">
              <select v-model="item.algorithm_id" class="compact-input">
                <option value="" disabled>选择 FLM</option>
                <option v-for="algorithm in algorithms" :key="algorithm.id" :value="algorithm.id">{{ algorithm.file_name }}</option>
              </select>
              <input v-if="item.format === 'bin'" v-model="item.base_address" class="compact-input mono" placeholder="BIN 基地址">
              <span v-else class="embedded-address">HEX 文件内地址</span>
            </div>
            <div class="row-actions">
              <button class="icon-command" title="上移" :disabled="index === 0" @click="moveFirmware(index, -1)">↑</button>
              <button class="icon-command" title="下移" :disabled="index === firmwares.length - 1" @click="moveFirmware(index, 1)">↓</button>
              <button class="icon-command" title="移除固件" @click="firmwares.splice(index, 1)">×</button>
            </div>
          </div>
          <p v-if="!firmwares.length" class="empty-state">尚未添加固件</p>
        </div>
      </section>

      <section class="work-panel settings-panel">
        <div class="panel-heading"><h2>量产配置</h2></div>
        <label class="setting-row"><span>下载器型号</span><select v-model="model" class="form-select" @change="modelChanged"><option value="auto">自动识别</option><option value="V2">V2</option><option value="V3">V3</option><option value="V4">V4</option></select></label>
        <label class="setting-row"><span>脚本文件名</span><input v-model="scriptName" class="form-input mono" :disabled="effectiveModel === 'V2' || effectiveModel === 'V3'"></label>
        <label class="setting-row"><span>自动烧录次数</span><input v-model.number="automaticCount" type="number" min="1" max="9999" class="form-input" :disabled="effectiveModel === 'V2'"></label>
        <label class="setting-row"><span>IDCODE 超时</span><input v-model.number="idcodeTimeout" type="number" min="500" max="600000" step="500" class="form-input"><em>ms</em></label>
        <label class="setting-row"><span>SWD 速率</span><select v-model.number="swdClock" class="form-select"><option :value="1000000">1 MHz</option><option :value="5000000">5 MHz</option><option :value="8000000">8 MHz</option><option :value="10000000">10 MHz</option><option :value="20000000">20 MHz</option></select></label>
        <div class="deploy-actions">
          <button class="btn" :disabled="operationBusy || !canBuild" @click="generatePreview">生成预览</button>
          <button class="btn btn-primary" data-testid="offline-deploy" :disabled="operationBusy || !canBuild" @click="deploy">部署到 U 盘</button>
          <button class="btn" data-testid="offline-trigger" :disabled="!canTrigger" @click="triggerOffline">触发测试</button>
        </div>
        <div class="script-preview">
          <div class="preview-title"><span>{{ preview?.script_name || effectiveScriptName }}</span><span>{{ preview?.model || effectiveModel }}</span></div>
          <pre>{{ preview?.script || '等待生成配置' }}</pre>
        </div>
        <pre v-if="triggerLines.length" class="trigger-log">{{ triggerLines.join('\n') }}</pre>
      </section>
    </div>
  </div>
</template>

<style scoped>
.offline-page{min-height:0;display:flex;flex-direction:column;gap:10px}.status-strip{display:flex;align-items:center;gap:28px;min-height:46px;padding:8px 14px;border:1px solid var(--border);border-radius:6px;background:var(--surface)}.status-strip>div{display:flex;align-items:baseline;gap:8px;min-width:0}.status-strip b{font-size:12px;font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.status-label{font-size:11px;color:var(--muted)}.status-actions{margin-left:auto}.ok{color:var(--success)}.bad{color:var(--danger)}.offline-workspace{display:grid;grid-template-columns:minmax(260px,.9fr) minmax(360px,1.25fr) minmax(300px,1fr);gap:10px;min-height:620px}.work-panel{min-width:0;min-height:0;padding:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);overflow:auto}.panel-heading{height:34px;display:flex;align-items:flex-start;justify-content:space-between;gap:10px;border-bottom:1px solid var(--border-subtle);margin-bottom:10px}.panel-heading h2{font-size:14px}.file-button{position:relative;overflow:hidden}.file-button input{position:absolute;inset:0;opacity:0;cursor:pointer}.target-search{display:grid;grid-template-columns:1fr auto;gap:6px}.target-results{display:grid;gap:5px;max-height:150px;overflow:auto;margin:8px 0 12px}.target-result{display:flex;align-items:center;justify-content:space-between;text-align:left;padding:7px 9px;border:1px solid var(--border);border-radius:5px;background:#fff;color:var(--fg);cursor:pointer}.target-result span{display:grid}.target-result small{font-size:10px;color:var(--muted)}.target-result em{font-style:normal;font-size:10px;color:var(--accent)}.algorithm-list,.firmware-list{display:grid;gap:7px}.algorithm-row,.firmware-row{border:1px solid var(--border);border-radius:5px;background:#fff}.algorithm-row{padding:8px}.row-title{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:7px;margin-bottom:7px}.row-title span{font-size:10px;color:var(--muted)}.algorithm-row>label{display:grid;grid-template-columns:42px 1fr;align-items:center;gap:6px;margin-top:5px;font-size:10px;color:var(--muted)}.compact-input{width:100%;height:27px;padding:0 7px;border:1px solid var(--border);border-radius:4px;background:#fff;color:var(--fg);min-width:0}.mono{font-family:var(--font-mono)}.icon-command{width:27px;height:27px;border:1px solid var(--border);border-radius:4px;background:transparent;color:var(--muted);cursor:pointer}.icon-command:hover{color:var(--accent);border-color:var(--accent)}.icon-command:disabled{opacity:.35;cursor:not-allowed}.firmware-row{display:grid;grid-template-columns:34px 1fr 28px;padding:8px;gap:7px}.sequence-number{display:grid;place-items:center;width:28px;height:28px;border-radius:4px;background:var(--bg);font-family:var(--font-mono);font-weight:600}.firmware-fields{display:grid;grid-template-columns:minmax(120px,1.2fr) minmax(110px,1fr);gap:6px}.firmware-fields .file-name{grid-column:1/-1}.embedded-address{align-self:center;font-size:11px;color:var(--muted)}.row-actions{display:grid;gap:4px}.setting-row{display:grid;grid-template-columns:108px 1fr auto;align-items:center;gap:8px;margin-bottom:9px}.setting-row>span{font-size:12px;color:var(--muted);text-align:right}.setting-row em{font-size:10px;color:var(--muted);font-style:normal}.deploy-actions{display:flex;flex-wrap:wrap;gap:7px;margin:14px 0}.script-preview{border:1px solid var(--border);border-radius:5px;overflow:hidden}.preview-title{display:flex;justify-content:space-between;padding:6px 9px;background:var(--bg);font-size:10px;color:var(--muted)}.script-preview pre,.trigger-log{margin:0;padding:10px;max-height:310px;overflow:auto;background:#16191d;color:#d9dee5;font:11px/1.55 var(--font-mono);white-space:pre}.trigger-log{margin-top:8px;border-radius:5px}.empty-state{padding:20px 8px;text-align:center;color:var(--dim);font-size:12px}@media(max-width:1100px){.offline-workspace{grid-template-columns:1fr 1.25fr}.settings-panel{grid-column:1/-1}}@media(max-width:760px){.status-strip{align-items:flex-start;flex-wrap:wrap}.status-actions{margin-left:0}.offline-workspace{grid-template-columns:1fr}.settings-panel{grid-column:auto}.firmware-fields{grid-template-columns:1fr}.firmware-fields .file-name{grid-column:auto}}
</style>
