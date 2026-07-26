<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import FlashActionBar from '../components/online-flash/FlashActionBar.vue'
import FlashLogPanel from '../components/online-flash/FlashLogPanel.vue'
import FlashMapPanel from '../components/online-flash/FlashMapPanel.vue'
import FirmwareWorkspace from '../components/online-flash/FirmwareWorkspace.vue'
import ProbeSettingsPanel from '../components/online-flash/ProbeSettingsPanel.vue'
import TargetPackPanel from '../components/online-flash/TargetPackPanel.vue'
import { HexPreviewModel, type FormattedHexRow } from '../lib/hexPreview'
import { OnlineFlashApiError, useOnlineFlashApi } from '../composables/useOnlineFlashApi'
import { listenForFirmwarePathDrops, pickFirmwareFiles } from '../lib/filePicker'
import type { CustomFlmRecord, ImageInspection, JobAction, JobEvent, JobState, JobStreamEvent, JobSubscription, PackStatus, ProbeRecord, TargetRecord } from '../types/onlineFlash'

const STORAGE_KEY = 'mklink.onlineFlash.settings'
const PROBE_DISCOVERY_ATTEMPTS = 6
const PROBE_DISCOVERY_DELAY_MS = 500
const AUTO_INSPECT_DELAY_MS = 150
const SOURCE_POLL_INTERVAL_MS = 1000
const ONLINE_FREQUENCIES = new Set([1_000_000, 2_000_000, 4_000_000, 8_000_000, 10_000_000])
const TERMINAL = new Set<JobState>(['succeeded', 'failed', 'stopped'])
const CANONICAL_ACTIONS: JobAction[] = ['connect', 'erase', 'program', 'verify', 'reset', 'disconnect']
const FLASH_ACTIONS = new Set<JobAction>(['erase', 'program', 'verify'])
const api = useOnlineFlashApi()

defineOptions({ name: 'OnlineFlashView' })

interface SavedSettings { targetPart?: string; frequency?: number; connectMode?: string; resetMode?: string; hpmBoard?: string; firmwarePath?: string; baseAddress?: string }
function savedSettings(): SavedSettings {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as SavedSettings } catch { return {} }
}
const saved = savedSettings()
function savedFrequency(value: number | undefined): number {
  return value !== undefined && ONLINE_FREQUENCIES.has(value) ? value : 1_000_000
}

const probes = ref<ProbeRecord[]>([])
const probeId = ref('')
const probeBusy = ref(false)
const probeError = ref('')
const frequency = ref(savedFrequency(saved.frequency))
const connectMode = ref(saved.connectMode ?? 'attach')
const resetMode = ref(saved.resetMode ?? 'default')
const hpmBoards = [
  'hpm5300evk', 'hpm5301evklite', 'hpm5e00evk', 'hpm6e00evk',
  'hpm6p00evk', 'hpm6200evk', 'hpm6300evk', 'hpm6750evk2',
  'hpm6750evkmini', 'hpm6800evk',
]
const hpmBoard = ref(saved.hpmBoard ?? '')
const targets = ref<TargetRecord[]>([])
const selectedTarget = ref<TargetRecord | null>(null)
const desiredPart = ref(saved.targetPart ?? '')
const packStatus = ref<PackStatus | null>(null)
const packBusy = ref(false)
const packCancelPending = ref(false)
const packProgress = ref(0)
const packPhase = ref('preparing')
const packError = ref('')
const customFlms = ref<CustomFlmRecord[]>([])
const customFlmBusy = ref(false)
const customFlmError = ref('')
const firmware = ref<File | null>(null)
const firmwarePath = ref(saved.firmwarePath ?? '')
const nativeDropActive = ref(false)
const baseAddress = ref(saved.baseAddress ?? '')
const binAddressOpen = ref(false)
const binAddressDraft = ref('')
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
let customFlmToken = 0
let autoInspectTimer: ReturnType<typeof setTimeout> | null = null
let sourcePollTimer: ReturnType<typeof setTimeout> | null = null
let sourcePollingEnabled = false
let sourceFingerprint = ''
let stopNativeDropListener: (() => void) | null = null
let disposed = false
let storageWarningReported = false

const preview = new HexPreviewModel((imageId, offset, length, signal) => api.previewImage(imageId, offset, length, signal))
const firmwareName = computed(() => firmware.value?.name || firmwarePath.value.split(/[\\/]/).pop() || '')
const isBin = computed(() => firmwareName.value.toLowerCase().endsWith('.bin'))
const parsedBase = computed(() => {
  if (!isBin.value) return null
  if (!/^0x[0-9a-f]+$/i.test(baseAddress.value)) return null
  const value = Number.parseInt(baseAddress.value.slice(2), 16)
  return Number.isSafeInteger(value) && value >= 0 && value <= 0xffff_ffff ? value : null
})
const baseError = computed(() => isBin.value && parsedBase.value === null ? 'BIN 基地址必须是有效的 0x 地址（0x00000000–0xFFFFFFFF）' : '')
const binAddressDraftValid = computed(() => /^0x[0-9a-f]+$/i.test(binAddressDraft.value) && Number.parseInt(binAddressDraft.value.slice(2), 16) <= 0xffff_ffff)
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
const canStart = computed(() => !!probeId.value && !!selectedTarget.value?.installed && !!inspection.value && !!firmwareName.value && !baseError.value && !active.value && !creatingJob.value && !packBusy.value && !inspectBusy.value && actionsAreValid(actions.value) && (!hpmMode.value || (!!hpmBoard.value && isBin.value)) && (!requiresSectorGeometry.value || geometryReliable.value || hpmMode.value))
const canErase = computed(() => !!probeId.value && !!selectedTarget.value?.installed && !hpmMode.value && !active.value && !creatingJob.value)
const hpmAlgorithmNotRequired = computed(() => (
  selectedTarget.value?.part_number.toLowerCase().startsWith('hpm') ?? false
))
function isHpmPart(partNumber: string): boolean {
  return partNumber.trim().toLowerCase().startsWith('hpm')
}
function defaultHpmBoard(partNumber: string): string {
  const part = partNumber.trim().toLowerCase()
  const match = [
    ['hpm5301', 'hpm5301evklite'], ['hpm5300', 'hpm5300evk'],
    ['hpm5e', 'hpm5e00evk'], ['hpm6e', 'hpm6e00evk'],
    ['hpm6p', 'hpm6p00evk'], ['hpm6200', 'hpm6200evk'],
    ['hpm6300', 'hpm6300evk'], ['hpm6750', 'hpm6750evk2'],
    ['hpm6800', 'hpm6800evk'],
  ].find(([prefix]) => part.startsWith(prefix))
  return match?.[1] ?? ''
}
const hpmMode = computed(() => isHpmPart(selectedTarget.value?.part_number ?? ''))

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
      hpmBoard: hpmBoard.value,
      firmwarePath: firmwarePath.value || undefined,
      baseAddress: baseAddress.value || undefined,
    }))
  } catch {
    if (!storageWarningReported) {
      storageWarningReported = true
      appendLog('[WARN] 本地设置未保存；当前交互仍可继续。')
    }
  }
}
watch([frequency, connectMode, resetMode, desiredPart, hpmBoard, baseAddress], persist)

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

function applyPackEvent(event: Awaited<ReturnType<typeof api.installPack>>['events'][number]): void {
  if (event.type === 'log') appendLog(`[PACK] ${event.message}`)
  else {
    if (event.phase) packPhase.value = event.phase
    if ('progress' in event && event.progress !== undefined) {
      packProgress.value = event.progress
    } else if ('total' in event && event.total) {
      packProgress.value = event.current / event.total
    } else {
      packProgress.value = 0
    }
  }
}

async function selectTarget(target: TargetRecord): Promise<void> {
  if (active.value || packBusy.value) return
  desiredPart.value = target.part_number
  hpmBoard.value = isHpmPart(target.part_number)
    ? (defaultHpmBoard(target.part_number) || hpmBoard.value)
    : ''
  resetInspection()
  selectedTarget.value = null
  if (isHpmPart(target.part_number) && !target.installed) {
    packError.value = `${target.part_number} 应由内置 HPM ROM API 提供，当前版本未发现该目标`
    return
  }
  if (!target.installed) {
    if (!confirm(`器件 ${target.part_number} 本机尚无下载算法。可先导入本地 Pack；是否现在联网下载对应 Pack？`)) return
    const operation = ++packOperationToken
    packBusy.value = true; packProgress.value = 0; packPhase.value = 'preparing'; packError.value = ''
    try {
      const response = await api.installPack(target.part_number, applyPackEvent)
      const result = response.result
      if (result.status === 'installed') {
        const installedPack = 'part_number' in result ? result.part_number : `${result.pack_id}@${result.version}`
        appendLog(`[PACK] 已安装 ${installedPack}`)
      }
      const [, refreshedTargets] = await Promise.all([refreshPackStatus(), searchTargets(target.part_number, false)])
      packProgress.value = 1
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

async function loadCustomFlms(partNumber = selectedTarget.value?.part_number || ''): Promise<void> {
  const token = ++customFlmToken
  customFlmError.value = ''
  if (!partNumber || isHpmPart(partNumber)) {
    customFlms.value = []
    customFlmBusy.value = false
    return
  }
  customFlmBusy.value = true
  try {
    const records = await api.listCustomFlms(partNumber)
    if (token === customFlmToken && !disposed) customFlms.value = records
  } catch (error) {
    if (token === customFlmToken) {
      customFlms.value = []
      customFlmError.value = message(error)
    }
  } finally {
    if (token === customFlmToken) customFlmBusy.value = false
  }
}

watch(() => selectedTarget.value?.part_number || '', partNumber => {
  void loadCustomFlms(partNumber)
})

async function addCustomFlm(file: File): Promise<void> {
  const partNumber = selectedTarget.value?.installed ? selectedTarget.value.part_number : ''
  if (!partNumber || customFlmBusy.value || active.value) return
  customFlmBusy.value = true
  customFlmError.value = ''
  try {
    await api.addCustomFlm(file, partNumber)
    await loadCustomFlms(partNumber)
    resetInspection()
    scheduleAutoInspection()
  } catch (error) {
    customFlmError.value = message(error)
  } finally {
    customFlmBusy.value = false
  }
}

async function removeCustomFlm(algorithmId: string): Promise<void> {
  const partNumber = selectedTarget.value?.installed ? selectedTarget.value.part_number : ''
  if (!partNumber || customFlmBusy.value || active.value) return
  if (!confirm('移除此自定义 FLM？已有固件检查结果将失效。')) return
  customFlmBusy.value = true
  customFlmError.value = ''
  try {
    await api.removeCustomFlm(algorithmId, partNumber)
    await loadCustomFlms(partNumber)
    resetInspection()
    scheduleAutoInspection()
  } catch (error) {
    customFlmError.value = message(error)
  } finally {
    customFlmBusy.value = false
  }
}

async function refreshPackStatus(): Promise<void> {
  try { packStatus.value = await api.getPackStatus() } catch (error) { packError.value = message(error) }
}
async function updatePackIndex(): Promise<void> {
  if (packBusy.value) return
  const operation = ++packOperationToken
  packBusy.value = true; packProgress.value = 0; packPhase.value = 'preparing'; packError.value = ''
  try { await api.updatePackIndex(applyPackEvent); await Promise.all([refreshPackStatus(), searchTargets('')]); packProgress.value = 1 }
  catch (error) { packError.value = message(error) } finally {
    if (operation === packOperationToken) { packBusy.value = false; packCancelPending.value = false }
  }
}
async function importPack(file: File): Promise<void> {
  if (packBusy.value || active.value) return
  const operation = ++packOperationToken
  packBusy.value = true; packProgress.value = 0; packPhase.value = 'preparing'; packError.value = ''
  try {
    const response = await api.importPack(file, applyPackEvent)
    const importedPack = 'pack_id' in response.result
      ? `${response.result.pack_id}@${response.result.version}`
      : 'part_number' in response.result ? response.result.part_number : 'Pack'
    appendLog(`[PACK] 已导入 ${importedPack}`)
    await Promise.all([refreshPackStatus(), searchTargets(desiredPart.value)])
    packProgress.value = 1
  } catch (error) { packError.value = message(error) } finally {
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
function setFirmware(file: File | null): void {
  firmware.value = file
  firmwarePath.value = ''
  sourceFingerprint = ''
  resetInspection()
  persist()
  promptForBinAddress(file?.name ?? '')
}

function setFirmwarePath(path: string): void {
  const suffix = path.split('.').pop()?.toLowerCase()
  if (suffix !== 'bin' && suffix !== 'hex') {
    inspectError.value = '固件只支持 BIN 或 HEX'
    return
  }
  firmware.value = null
  firmwarePath.value = path
  sourceFingerprint = ''
  resetInspection()
  persist()
  void pollFirmwareSource(true)
  promptForBinAddress(path)
}

function promptForBinAddress(source: string): void {
  if (!source.toLowerCase().endsWith('.bin')) {
    binAddressOpen.value = false
    return
  }
  binAddressDraft.value = baseAddress.value
  binAddressOpen.value = true
}

function confirmBinAddress(): void {
  if (!binAddressDraftValid.value) return
  setBase(binAddressDraft.value)
  binAddressOpen.value = false
  scheduleAutoInspection()
}

function cancelBinAddress(): void {
  binAddressOpen.value = false
  setBase('')
}

function acceptFirmwareSources(sources: Array<string | File>): void {
  const source = sources[0]
  if (typeof source === 'string') setFirmwarePath(source)
  else if (source instanceof File) setFirmware(source)
}

async function browseFirmware(): Promise<void> {
  acceptFirmwareSources(await pickFirmwareFiles(false))
}

async function startNativeDropListener(): Promise<void> {
  if (stopNativeDropListener) return
  stopNativeDropListener = await listenForFirmwarePathDrops(
    paths => acceptFirmwareSources(paths),
    active => { nativeDropActive.value = active },
  )
}

function stopNativeDrops(): void {
  stopNativeDropListener?.()
  stopNativeDropListener = null
  nativeDropActive.value = false
}

async function pollFirmwareSource(initial = false): Promise<void> {
  const path = firmwarePath.value
  if (!path || disposed) return
  try {
    const status = await api.getImageSourceStatus(path)
    if (path !== firmwarePath.value || disposed) return
    const fingerprint = `${status.size}:${status.mtime_ns}`
    if (!sourceFingerprint) {
      sourceFingerprint = fingerprint
    } else if (fingerprint !== sourceFingerprint) {
      sourceFingerprint = fingerprint
      resetInspection()
      appendLog(`[FILE] 已自动加载重新编译的 ${status.file_name}`)
      scheduleAutoInspection()
    }
  } catch (error) {
    if (initial) inspectError.value = `固件路径不可用：${message(error)}`
  }
}

function startSourcePolling(): void {
  if (sourcePollingEnabled) return
  sourcePollingEnabled = true
  const run = async () => {
    await pollFirmwareSource()
    if (!disposed && sourcePollingEnabled) sourcePollTimer = setTimeout(run, SOURCE_POLL_INTERVAL_MS)
  }
  void run()
}

function stopSourcePolling(): void {
  sourcePollingEnabled = false
  if (sourcePollTimer !== null) clearTimeout(sourcePollTimer)
  sourcePollTimer = null
}
function setBase(value: string): void {
  if (value !== baseAddress.value) {
    baseAddress.value = value
    resetInspection()
  }
  if (/^0x[0-9a-f]+$/i.test(value) && Number.parseInt(value.slice(2), 16) <= 0xffff_ffff) {
    binAddressOpen.value = false
  }
}

function scheduleAutoInspection(): void {
  if (autoInspectTimer !== null) clearTimeout(autoInspectTimer)
  autoInspectTimer = null
  if (!firmwareName.value || !selectedTarget.value?.installed || baseError.value || binAddressOpen.value) return
  autoInspectTimer = setTimeout(() => {
    autoInspectTimer = null
    void inspectImage()
  }, AUTO_INSPECT_DELAY_MS)
}

watch([firmware, firmwarePath, () => selectedTarget.value?.part_number, baseAddress], scheduleAutoInspection)

async function inspectImage(): Promise<void> {
  if (!firmwareName.value || !selectedTarget.value?.installed || baseError.value) {
    inspectError.value = !selectedTarget.value?.installed ? '请先选择已安装的精确器件型号' : baseError.value || '请选择固件'
    return
  }
  resetInspection(); inspectBusy.value = true; inspectError.value = ''
  const generation = ++inspectionGeneration
  const controller = new AbortController()
  inspectionController = controller
  try {
    const result = firmwarePath.value
      ? await api.inspectImagePath(firmwarePath.value, selectedTarget.value.part_number, isBin.value ? parsedBase.value : null, controller.signal)
      : await api.inspectImage(firmware.value!, selectedTarget.value.part_number, isBin.value ? parsedBase.value : null, controller.signal)
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
  }
  if (jobEvent.event === 'progress' && jobEvent.progress !== null) {
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
  if (sectorAddresses === undefined && orderedActions.includes('erase') && !geometryReliable.value && !hpmMode.value) return
  creatingJob.value = true
  try {
    logs.value = []; lastSequence.value = 0; totalProgress.value = 0
    const result = await api.createJob({ actions: orderedActions, image_id: inspection.value?.image_id, probe_id: probeId.value, target_part: selectedTarget.value.part_number, frequency: frequency.value, connect_mode: connectMode.value, reset_mode: resetMode.value, base_address: isBin.value ? parsedBase.value : null, sector_addresses: hpmMode.value ? [] : resolvedSectors, board: hpmMode.value ? hpmBoard.value : null })
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
onActivated(() => {
  disposed = false
  startSourcePolling()
  void startNativeDropListener()
})
onDeactivated(() => {
  stopSourcePolling()
  stopNativeDrops()
})
onBeforeUnmount(() => {
  disposed = true
  stopSourcePolling()
  stopNativeDrops()
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
      <TargetPackPanel :targets="targets" :selected-part="selectedTarget?.part_number || ''" :status="packStatus" :busy="packBusy" :cancel-pending="packCancelPending" :progress="packProgress" :phase="packPhase" :error="packError" :algorithms="customFlms" :algorithm-busy="customFlmBusy" :algorithm-error="customFlmError" :can-manage-algorithms="!!selectedTarget?.installed && !active && !hpmAlgorithmNotRequired" :algorithm-not-required="hpmAlgorithmNotRequired" @search="searchTargets" @select="selectTarget" @update-index="updatePackIndex" @import-pack="importPack" @cancel="cancelPack" @add-algorithm="addCustomFlm" @remove-algorithm="removeCustomFlm" />
      <label v-if="hpmMode" class="hpm-setting"><span>HPM 板卡</span><select v-model="hpmBoard" data-testid="hpm-board"><option v-for="item in hpmBoards" :key="item" :value="item">{{ item }}</option></select></label>
    </aside>
    <main class="workspace-zone firmware-zone" data-zone="firmware">
      <FirmwareWorkspace :file="firmware" :source-path="firmwarePath" :native-drop-active="nativeDropActive" :base-address="baseAddress" :base-error="baseError" :inspection="inspection" :rows="rows" :padding-top="paddingTop" :padding-bottom="paddingBottom" :loading="inspectBusy" :error="inspectError" @file="setFirmware" @browse="browseFirmware" @drop-files="acceptFirmwareSources" @base="setBase" @scroll="loadVisible" />
      <FlashActionBar :actions="actions" :can-start="canStart" :active="active" :stopping="stopping" :state="jobState" :total-progress="totalProgress" @actions="setActions" @start="startJob()" @stop="stopJob" />
    </main>
    <aside class="workspace-zone flash-map-zone" data-zone="flash-map"><FlashMapPanel :segments="inspection?.segments || []" :sectors="inspection?.sectors || []" :selected-addresses="selectedSectorAddresses" :inspection-ready="!!inspection" :geometry-reliable="geometryReliable" :can-erase="canErase" @chip-erase="chipErase" @selected-erase="selectedErase" @range-erase="rangeErase" @select-all="selectedSectorAddresses = inspection?.sectors.map(sector => sector.address) || []" @clear-selection="selectedSectorAddresses = []" @toggle-sector="toggleSector" /></aside>
    <section class="workspace-zone logs-zone" data-zone="logs"><FlashLogPanel :lines="logs" :stream-disconnected="streamDisconnected" @clear="logs = []" @reconnect="subscribe(lastSequence)" /></section>
    <div v-if="binAddressOpen" class="bin-address-backdrop" data-testid="bin-address-dialog" @click.self="cancelBinAddress">
      <section class="bin-address-dialog" role="dialog" aria-modal="true" aria-labelledby="bin-address-title">
        <h2 id="bin-address-title">设置 BIN 下载地址</h2>
        <p>请输入 {{ firmwareName }} 在目标 Flash 中的起始地址。</p>
        <label>
          <span>下载地址</span>
          <input v-model.trim="binAddressDraft" data-testid="bin-address-dialog-input" autofocus placeholder="如 0x08005000" @keydown.enter.prevent="confirmBinAddress" />
        </label>
        <p v-if="binAddressDraft && !binAddressDraftValid" class="bin-address-error">请输入 0x00000000–0xFFFFFFFF 范围内的十六进制地址。</p>
        <footer>
          <button type="button" class="bin-address-cancel" @click="cancelBinAddress">取消</button>
          <button type="button" class="bin-address-confirm" data-testid="confirm-bin-address" :disabled="!binAddressDraftValid" @click="confirmBinAddress">确认</button>
        </footer>
      </section>
    </div>
  </div>
</template>

<style scoped>
.online-flash-grid{--of-bg:#11151a;--of-surface:#1d2229;--of-input:#252b33;--of-border:#343c46;--of-text:#e6e9ed;--of-muted:#929ba7;--of-accent:#58a6d6;--of-danger:#f07178;--of-danger-bg:#3b2428;--of-ok:#65c18c;--of-ok-bg:#20372d;--of-warn:#d8ad62;--of-mono:var(--mono,ui-monospace,Consolas,monospace);box-sizing:border-box;height:calc(100dvh - 92px);min-height:0;display:grid;grid-template-columns:minmax(230px,.85fr) minmax(520px,1.9fr) minmax(240px,.9fr);grid-template-rows:minmax(0,1fr) minmax(130px,185px);gap:10px;padding:10px;border-radius:var(--radius,7px);background:var(--of-bg);color:var(--of-text);text-align:left;font-size:12px}.workspace-zone{min-width:0;min-height:0;overflow:hidden;border:1px solid var(--of-border);border-radius:7px;background:var(--of-surface)}.settings-zone,.flash-map-zone{overflow:auto}.firmware-zone{min-height:0;display:flex;flex-direction:column}.firmware-zone :deep(.hex-scroll){min-height:0;flex:1}.logs-zone{grid-column:1/-1;font-family:var(--of-mono)}@media(max-width:1050px){.online-flash-grid{height:auto;min-height:660px;grid-template-columns:minmax(220px,.8fr) minmax(500px,1.6fr);grid-template-rows:auto}.flash-map-zone{grid-column:1/-1}.logs-zone{grid-column:1/-1}}@media(max-width:760px){.online-flash-grid{grid-template-columns:1fr;grid-template-rows:none}.flash-map-zone,.logs-zone{grid-column:auto}.firmware-zone{min-height:560px}}
.hpm-setting{display:grid;gap:5px;padding:10px;border-top:1px solid var(--of-border);color:var(--of-muted)}.hpm-setting select{min-width:0;width:100%;height:30px;border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text);padding:0 8px}
.bin-address-backdrop{position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(0,0,0,.58)}.bin-address-dialog{width:min(420px,100%);padding:20px;border:1px solid var(--of-border);border-radius:7px;background:var(--of-surface);box-shadow:0 18px 50px rgba(0,0,0,.35)}.bin-address-dialog h2{margin:0 0 8px;font-size:17px;letter-spacing:0}.bin-address-dialog>p{margin:0 0 16px;color:var(--of-muted);line-height:1.5}.bin-address-dialog label{display:grid;gap:6px;color:var(--of-muted)}.bin-address-dialog input{height:36px;padding:0 10px;border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text);font-family:var(--of-mono);font-size:14px}.bin-address-dialog input:focus{outline:2px solid var(--of-accent);outline-offset:1px}.bin-address-dialog .bin-address-error{margin:8px 0 0;color:var(--of-danger);font-size:11px}.bin-address-dialog footer{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}.bin-address-dialog button{min-width:72px;height:32px;border:1px solid var(--of-border);border-radius:5px;cursor:pointer}.bin-address-cancel{background:var(--of-input);color:var(--of-text)}.bin-address-confirm{border-color:var(--of-accent)!important;background:var(--of-accent);color:#0d1720}.bin-address-confirm:disabled{cursor:not-allowed;opacity:.45}
</style>
