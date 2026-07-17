<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import FlashActionBar from '../components/online-flash/FlashActionBar.vue'
import FlashLogPanel from '../components/online-flash/FlashLogPanel.vue'
import FlashMapPanel from '../components/online-flash/FlashMapPanel.vue'
import FirmwareWorkspace from '../components/online-flash/FirmwareWorkspace.vue'
import ProbeSettingsPanel from '../components/online-flash/ProbeSettingsPanel.vue'
import TargetPackPanel from '../components/online-flash/TargetPackPanel.vue'
import { HexPreviewModel, type FormattedHexRow } from '../lib/hexPreview'
import { OnlineFlashApiError, useOnlineFlashApi } from '../composables/useOnlineFlashApi'
import type { ImageInspection, JobAction, JobEvent, JobState, JobStreamEvent, JobSubscription, PackStatus, ProbeRecord, TargetRecord } from '../types/onlineFlash'

const STORAGE_KEY = 'mklink.onlineFlash.settings'
const PROBE_DISCOVERY_ATTEMPTS = 6
const PROBE_DISCOVERY_DELAY_MS = 500
const AUTO_INSPECT_DELAY_MS = 150
const TERMINAL = new Set<JobState>(['succeeded', 'failed', 'stopped'])
const CANONICAL_ACTIONS: JobAction[] = ['connect', 'erase', 'program', 'verify', 'reset', 'disconnect']
const FLASH_ACTIONS = new Set<JobAction>(['erase', 'program', 'verify'])
const api = useOnlineFlashApi()

interface SavedSettings { targetPart?: string; frequency?: number; connectMode?: string; resetMode?: string }
function savedSettings(): SavedSettings {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as SavedSettings } catch { return {} }
}
const saved = savedSettings()

const probes = ref<ProbeRecord[]>([])
const probeId = ref('')
const probeBusy = ref(false)
const probeError = ref('')
const frequency = ref(saved.frequency ?? 1_000_000)
const connectMode = ref(saved.connectMode ?? 'halt')
const resetMode = ref(saved.resetMode ?? 'default')
const targets = ref<TargetRecord[]>([])
const selectedTarget = ref<TargetRecord | null>(null)
const desiredPart = ref(saved.targetPart ?? '')
const packStatus = ref<PackStatus | null>(null)
const packBusy = ref(false)
const packCancelPending = ref(false)
const packProgress = ref(0)
const packError = ref('')
const firmware = ref<File | null>(null)
const baseAddress = ref('')
const inspection = ref<ImageInspection | null>(null)
const selectedSectorAddresses = ref<number[]>([])
const inspectBusy = ref(false)
const inspectError = ref('')
const rows = ref<FormattedHexRow[]>([])
const paddingTop = ref(0)
const paddingBottom = ref(0)
const actions = ref<JobAction[]>([...CANONICAL_ACTIONS])
const jobId = ref('')
const jobState = ref<JobState | null>(null)
const stageProgress = ref(0)
const totalProgress = ref(0)
const logs = ref<string[]>([])
const lastSequence = ref(0)
const streamDisconnected = ref(false)
const creatingJob = ref(false)
let subscription: JobSubscription | null = null
let inspectionController: AbortController | null = null
let inspectionGeneration = 0
let viewportGeneration = 0
let targetSearchGeneration = 0
let targetSearchController: AbortController | null = null
let packOperationToken = 0
let autoInspectTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false
let storageWarningReported = false

const preview = new HexPreviewModel((imageId, offset, length, signal) => api.previewImage(imageId, offset, length, signal))
const isBin = computed(() => firmware.value?.name.toLowerCase().endsWith('.bin') ?? false)
const parsedBase = computed(() => {
  if (!isBin.value) return null
  if (!/^0x[0-9a-f]+$/i.test(baseAddress.value)) return null
  const value = Number.parseInt(baseAddress.value.slice(2), 16)
  return Number.isSafeInteger(value) && value >= 0 && value <= 0xffff_ffff ? value : null
})
const baseError = computed(() => isBin.value && parsedBase.value === null ? 'BIN 基地址必须是有效的 0x 地址（0x00000000–0xFFFFFFFF）' : '')
const active = computed(() => !!jobId.value && !!jobState.value && !TERMINAL.has(jobState.value))
const stopping = computed(() => jobState.value === 'stopping')
const geometryReliable = computed(() => (
  inspection.value?.sector_operations_available === true
  && inspection.value.sectors.length > 0
))
const requiresSectorGeometry = computed(() => (
  actions.value.includes('erase') || actions.value.includes('program')
))
function canonicalActions(values: readonly JobAction[]): JobAction[] {
  const selected = new Set(values)
  selected.add('connect'); selected.add('disconnect')
  return CANONICAL_ACTIONS.filter(action => selected.has(action))
}
function actionsAreValid(values: readonly JobAction[]): boolean {
  const canonical = canonicalActions(values)
  return values.length === new Set(values).size
    && values.length === canonical.length
    && values.every((value, index) => value === canonical[index])
    && values[0] === 'connect'
    && values.at(-1) === 'disconnect'
    && values.some(action => FLASH_ACTIONS.has(action))
}
function setActions(values: JobAction[]): void { actions.value = canonicalActions(values) }
const canStart = computed(() => !!probeId.value && !!selectedTarget.value?.installed && !!inspection.value && !!firmware.value && !baseError.value && !active.value && !creatingJob.value && !packBusy.value && !inspectBusy.value && actionsAreValid(actions.value) && (!requiresSectorGeometry.value || geometryReliable.value))
const canErase = computed(() => !!probeId.value && !!selectedTarget.value?.installed && !active.value && !creatingJob.value)

function message(error: unknown): string {
  if (error instanceof OnlineFlashApiError) {
    const prefix = error.code ? `${error.code} · ` : ''
    return `${prefix}${error.message}`
  }
  return error instanceof Error ? error.message : String(error)
}

function persist(): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      targetPart: selectedTarget.value?.part_number || desiredPart.value,
      frequency: frequency.value,
      connectMode: connectMode.value,
      resetMode: resetMode.value,
    }))
  } catch {
    if (!storageWarningReported) {
      storageWarningReported = true
      appendLog('[WARN] 本地设置未保存；当前交互仍可继续。')
    }
  }
}
watch([frequency, connectMode, resetMode, desiredPart], persist)

async function refreshProbes(retryWhenEmpty = false): Promise<void> {
  probeBusy.value = true; probeError.value = ''
  try {
    const attempts = retryWhenEmpty ? PROBE_DISCOVERY_ATTEMPTS : 1
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        probes.value = await api.listProbes()
        if (probes.value.length > 0 || attempt === attempts - 1) break
      } catch (error) {
        if (attempt === attempts - 1) throw error
      }
      await new Promise(resolve => setTimeout(resolve, PROBE_DISCOVERY_DELAY_MS))
    }
    if (!probes.value.some(item => item.unique_id === probeId.value)) probeId.value = probes.value[0]?.unique_id ?? ''
  } catch (error) { probeError.value = message(error) } finally { probeBusy.value = false }
}

async function searchTargets(query = '', commit = true): Promise<TargetRecord[]> {
  let generation = targetSearchGeneration
  let controller: AbortController | null = null
  if (commit) {
    generation = ++targetSearchGeneration
    targetSearchController?.abort()
    controller = new AbortController()
    targetSearchController = controller
    packError.value = ''
  }
  try {
    const records = await api.searchTargets(query, { limit: 100 }, controller?.signal)
    if (commit && generation === targetSearchGeneration && !disposed) {
      targets.value = records
      const exact = records.find(target => target.part_number === desiredPart.value)
      if (exact?.installed) selectedTarget.value = exact
    }
    return records
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return []
    if (commit && generation === targetSearchGeneration) packError.value = message(error)
    else if (!commit) throw error
    return []
  } finally {
    if (targetSearchController === controller) targetSearchController = null
  }
}

function applyPackProgress(events: Awaited<ReturnType<typeof api.installPack>>['events']): void {
  for (const event of events) {
    if (event.type === 'log') appendLog(`[PACK] ${event.message}`)
    else packProgress.value = 'progress' in event ? event.progress : event.total ? event.current / event.total : 0
  }
}

async function selectTarget(target: TargetRecord): Promise<void> {
  if (active.value || packBusy.value) return
  desiredPart.value = target.part_number
  resetInspection()
  selectedTarget.value = null
  if (!target.installed) {
    if (!confirm(`器件 ${target.part_number} 尚未安装。是否联网下载对应 Pack？`)) return
    const operation = ++packOperationToken
    packBusy.value = true; packProgress.value = 0; packError.value = ''
    try {
      const response = await api.installPack(target.part_number)
      applyPackProgress(response.events)
      const result = response.result
      if (result.status === 'installed') {
        const installedPack = 'part_number' in result ? result.part_number : `${result.pack_id}@${result.version}`
        appendLog(`[PACK] 已安装 ${installedPack}`)
      }
      const [, refreshedTargets] = await Promise.all([refreshPackStatus(), searchTargets(target.part_number, false)])
      const refreshed = refreshedTargets.find(item => item.part_number === target.part_number && item.installed)
      if (refreshed) selectedTarget.value = refreshed
      else {
        selectedTarget.value = null
        packError.value = `Pack 安装完成，但安装后索引仍未确认 ${target.part_number} 已安装，请刷新索引后重试。`
      }
    } catch (error) { packError.value = message(error) } finally {
      if (operation === packOperationToken) { packBusy.value = false; packCancelPending.value = false }
    }
  } else selectedTarget.value = target
  persist()
}

async function refreshPackStatus(): Promise<void> {
  try { packStatus.value = await api.getPackStatus() } catch (error) { packError.value = message(error) }
}
async function updatePackIndex(): Promise<void> {
  if (packBusy.value) return
  const operation = ++packOperationToken
  packBusy.value = true; packProgress.value = 0; packError.value = ''
  try { const response = await api.updatePackIndex(); applyPackProgress(response.events); await Promise.all([refreshPackStatus(), searchTargets('')]) }
  catch (error) { packError.value = message(error) } finally {
    if (operation === packOperationToken) { packBusy.value = false; packCancelPending.value = false }
  }
}
async function cancelPack(): Promise<void> {
  if (!packBusy.value || packCancelPending.value) return
  packCancelPending.value = true
  try { await api.cancelPackOperation() }
  catch (error) { packCancelPending.value = false; packError.value = message(error) }
}

function resetInspection(): void {
  inspectionGeneration += 1
  viewportGeneration += 1
  inspectionController?.abort()
  inspectionController = null
  inspectBusy.value = false
  inspection.value = null; selectedSectorAddresses.value = []; rows.value = []; paddingTop.value = 0; paddingBottom.value = 0; inspectError.value = ''; preview.setSource(null)
}
function setFirmware(file: File | null): void { firmware.value = file; resetInspection() }
function setBase(value: string): void { if (value !== baseAddress.value) { baseAddress.value = value; resetInspection() } }

function scheduleAutoInspection(): void {
  if (autoInspectTimer !== null) clearTimeout(autoInspectTimer)
  autoInspectTimer = null
  if (!firmware.value || !selectedTarget.value?.installed || baseError.value) return
  autoInspectTimer = setTimeout(() => {
    autoInspectTimer = null
    void inspectImage()
  }, AUTO_INSPECT_DELAY_MS)
}

watch([firmware, () => selectedTarget.value?.part_number, baseAddress], scheduleAutoInspection)

async function inspectImage(): Promise<void> {
  if (!firmware.value || !selectedTarget.value?.installed || baseError.value) {
    inspectError.value = !selectedTarget.value?.installed ? '请先选择已安装的精确器件型号' : baseError.value || '请选择固件'
    return
  }
  resetInspection(); inspectBusy.value = true; inspectError.value = ''
  const generation = ++inspectionGeneration
  const controller = new AbortController()
  inspectionController = controller
  try {
    const result = await api.inspectImage(firmware.value, selectedTarget.value.part_number, isBin.value ? parsedBase.value : null, controller.signal)
    if (disposed || generation !== inspectionGeneration || controller.signal.aborted || inspectionController !== controller) throw new DOMException('Aborted', 'AbortError')
    if (result.end < result.start || (isBin.value && result.base_address !== parsedBase.value)) throw new Error('服务端返回的镜像地址范围无效')
    inspection.value = result
    selectedSectorAddresses.value = result.sector_operations_available
      ? result.sectors.map(sector => sector.address)
      : []
    preview.setSource({ imageId: result.image_id, start: result.start, size: result.end - result.start })
    await loadVisible(0, 360)
  } catch (error) {
    if (!(error instanceof DOMException && error.name === 'AbortError')) inspectError.value = `固件检查失败：${message(error)}`
  } finally {
    if (inspectionController === controller) { inspectionController = null; inspectBusy.value = false }
  }
}

async function loadVisible(scrollTop: number, height: number): Promise<void> {
  if (!inspection.value) return
  const generation = ++viewportGeneration
  const range = preview.visibleRange(scrollTop, height, 20)
  paddingTop.value = range.paddingTop; paddingBottom.value = range.paddingBottom
  try {
    const nextRows = await preview.loadRows(range.startRow, range.endRow)
    if (generation === viewportGeneration) rows.value = nextRows
  } catch (error) {
    if (generation === viewportGeneration && !(error instanceof DOMException && error.name === 'AbortError')) inspectError.value = `预览加载失败：${message(error)}`
  }
}

function appendLog(line: string): void { logs.value.push(line); if (logs.value.length > 5000) logs.value.splice(0, logs.value.length - 5000) }
function subscribe(after = lastSequence.value): void {
  subscription?.close(); streamDisconnected.value = false
  subscription = api.subscribeJob(jobId.value, after, receiveEvent, error => {
    streamDisconnected.value = true
    appendLog(`[SSE:${error.code}] ${error.message}`)
  })
}
function receiveEvent(event: JobStreamEvent): void {
  if (!('sequence' in event)) {
    streamDisconnected.value = true
    appendLog(`[SSE:${event.code}] ${event.message}`)
    return
  }
  if (event.sequence <= lastSequence.value) return
  lastSequence.value = event.sequence
  const jobEvent = event as JobEvent
  if (jobEvent.state) {
    jobState.value = jobEvent.state
    if (jobEvent.event === 'state') stageProgress.value = TERMINAL.has(jobEvent.state) ? 1 : 0
  }
  if (jobEvent.event === 'progress' && jobEvent.progress !== null) {
    stageProgress.value = 1
    totalProgress.value = Math.max(totalProgress.value, jobEvent.progress)
  }
  if (jobEvent.message) appendLog(`[${jobEvent.sequence}] ${jobEvent.message}`)
  if (jobEvent.state && TERMINAL.has(jobEvent.state)) { totalProgress.value = jobEvent.state === 'succeeded' ? 1 : totalProgress.value; subscription = null }
}

async function startJob(customActions = actions.value, sectorAddresses?: number[]): Promise<void> {
  const orderedActions = canonicalActions(customActions)
  if (creatingJob.value || active.value || !probeId.value || !selectedTarget.value?.installed || !actionsAreValid(orderedActions) || (orderedActions.some(action => action === 'program' || action === 'verify') && !inspection.value)) return
  const resolvedSectors = sectorAddresses ?? (
    orderedActions.includes('erase') && inspection.value?.sector_operations_available
      ? inspection.value.sectors.map(sector => sector.address)
      : []
  )
  if (sectorAddresses === undefined && orderedActions.includes('erase') && !geometryReliable.value) return
  creatingJob.value = true
  try {
    logs.value = []; lastSequence.value = 0; stageProgress.value = 0; totalProgress.value = 0
    const result = await api.createJob({ actions: orderedActions, image_id: inspection.value?.image_id, probe_id: probeId.value, target_part: selectedTarget.value.part_number, frequency: frequency.value, connect_mode: connectMode.value, reset_mode: resetMode.value, base_address: isBin.value ? parsedBase.value : null, sector_addresses: resolvedSectors })
    if (disposed) return
    jobId.value = result.job_id; jobState.value = result.job.state
    appendLog(`[JOB] 已创建 ${result.job_id}`); subscribe(0)
  } catch (error) { appendLog(`[ERROR] ${message(error)}`) }
  finally { creatingJob.value = false }
}
async function stopJob(): Promise<void> {
  if (!jobId.value || stopping.value) return
  const previousState = jobState.value
  jobState.value = 'stopping'; appendLog('[JOB] STOPPING：等待探针安全停止')
  try {
    const snapshot = await api.stopJob(jobId.value)
    if ((!jobState.value || !TERMINAL.has(jobState.value)) && TERMINAL.has(snapshot.state)) {
      jobState.value = snapshot.state
    }
  }
  catch (error) {
    if (jobState.value === 'stopping') jobState.value = previousState
    appendLog(`[ERROR] 停止请求失败：${message(error)}`)
  }
}
function chipErase(): void { if (confirm('全片擦除将永久删除芯片中的全部闪存内容，确定继续？')) void startJob(['connect', 'erase', 'disconnect'], []) }
function selectedErase(): void { if (selectedSectorAddresses.value.length && confirm('确定擦除所选扇区？')) void startJob(['connect', 'erase', 'disconnect'], selectedSectorAddresses.value) }
function rangeErase(): void { if (inspection.value?.sectors.length && confirm('确定擦除镜像覆盖范围？')) void startJob(['connect', 'erase', 'disconnect'], inspection.value.sectors.map(sector => sector.address)) }
function toggleSector(address: number): void {
  selectedSectorAddresses.value = selectedSectorAddresses.value.includes(address)
    ? selectedSectorAddresses.value.filter(value => value !== address)
    : [...selectedSectorAddresses.value, address].sort((left, right) => left - right)
}

onMounted(() => { void Promise.all([refreshProbes(true), refreshPackStatus(), searchTargets(desiredPart.value)]) })
onBeforeUnmount(() => {
  disposed = true
  if (autoInspectTimer !== null) clearTimeout(autoInspectTimer)
  inspectionController?.abort()
  inspectionGeneration += 1
  viewportGeneration += 1
  targetSearchGeneration += 1
  targetSearchController?.abort()
  subscription?.close()
  preview.setSource(null)
})
</script>

<template>
  <div class="online-flash-grid">
    <aside class="workspace-zone settings-zone" data-zone="settings">
      <ProbeSettingsPanel :probes="probes" :selected-id="probeId" :frequency="frequency" :connect-mode="connectMode" :reset-mode="resetMode" :busy="probeBusy || active" :error="probeError" @refresh="refreshProbes" @update:selected-id="probeId = $event" @update:frequency="frequency = $event" @update:connect-mode="connectMode = $event" @update:reset-mode="resetMode = $event" />
      <TargetPackPanel :targets="targets" :selected-part="selectedTarget?.part_number || ''" :status="packStatus" :busy="packBusy" :cancel-pending="packCancelPending" :progress="packProgress" :error="packError" @search="searchTargets" @select="selectTarget" @update-index="updatePackIndex" @cancel="cancelPack" />
    </aside>
    <main class="workspace-zone firmware-zone" data-zone="firmware">
      <FirmwareWorkspace :file="firmware" :base-address="baseAddress" :base-error="baseError" :inspection="inspection" :rows="rows" :padding-top="paddingTop" :padding-bottom="paddingBottom" :loading="inspectBusy" :error="inspectError" @file="setFirmware" @base="setBase" @scroll="loadVisible" />
      <FlashActionBar :actions="actions" :can-start="canStart" :active="active" :stopping="stopping" :state="jobState" :stage-progress="stageProgress" :total-progress="totalProgress" @actions="setActions" @start="startJob()" @stop="stopJob" />
    </main>
    <aside class="workspace-zone flash-map-zone" data-zone="flash-map"><FlashMapPanel :segments="inspection?.segments || []" :sectors="inspection?.sectors || []" :selected-addresses="selectedSectorAddresses" :geometry-reliable="geometryReliable" :can-erase="canErase" @chip-erase="chipErase" @selected-erase="selectedErase" @range-erase="rangeErase" @select-all="selectedSectorAddresses = inspection?.sectors.map(sector => sector.address) || []" @clear-selection="selectedSectorAddresses = []" @toggle-sector="toggleSector" /></aside>
    <section class="workspace-zone logs-zone" data-zone="logs"><FlashLogPanel :lines="logs" :stream-disconnected="streamDisconnected" @clear="logs = []" @reconnect="subscribe(lastSequence)" /></section>
  </div>
</template>

<style scoped>
.online-flash-grid{--of-bg:#11151a;--of-surface:#1d2229;--of-input:#252b33;--of-border:#343c46;--of-text:#e6e9ed;--of-muted:#929ba7;--of-accent:#58a6d6;--of-danger:#f07178;--of-danger-bg:#3b2428;--of-ok:#65c18c;--of-ok-bg:#20372d;--of-warn:#d8ad62;--of-mono:var(--mono,ui-monospace,Consolas,monospace);box-sizing:border-box;height:calc(100dvh - 92px);min-height:0;display:grid;grid-template-columns:minmax(230px,.85fr) minmax(520px,1.9fr) minmax(240px,.9fr);grid-template-rows:minmax(0,1fr) minmax(130px,185px);gap:10px;padding:10px;border-radius:var(--radius,7px);background:var(--of-bg);color:var(--of-text);text-align:left;font-size:12px}.workspace-zone{min-width:0;min-height:0;overflow:hidden;border:1px solid var(--of-border);border-radius:7px;background:var(--of-surface)}.settings-zone,.flash-map-zone{overflow:auto}.firmware-zone{min-height:0;display:flex;flex-direction:column}.firmware-zone :deep(.hex-scroll){min-height:0;flex:1}.logs-zone{grid-column:1/-1;font-family:var(--of-mono)}@media(max-width:1050px){.online-flash-grid{height:auto;min-height:660px;grid-template-columns:minmax(220px,.8fr) minmax(500px,1.6fr);grid-template-rows:auto}.flash-map-zone{grid-column:1/-1}.logs-zone{grid-column:1/-1}}@media(max-width:760px){.online-flash-grid{grid-template-columns:1fr;grid-template-rows:none}.flash-map-zone,.logs-zone{grid-column:auto}.firmware-zone{min-height:560px}}
</style>
