<script setup lang="ts">
import { Download, FolderInput, FilePlus2, RotateCcw } from '@lucide/vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { CustomFlmRecord, FlashAlgorithmRecord, PackStatus, TargetRecord } from '../../types/onlineFlash'
import { tr } from '../../composables/useLanguage'

const props = defineProps<{ targets: TargetRecord[]; query: string; selectedPart: string; selectedInstalled: boolean; selectedAlgorithmId?: string; selectedAlgorithmIds?: string[]; algorithmPlan?: Array<FlashAlgorithmRecord & { ranges: Array<{ start: number; end: number }> }>; algorithmChoices?: FlashAlgorithmRecord[]; status: PackStatus | null; busy: boolean; cancelPending: boolean; progress: number; phase: string; error: string; algorithms: CustomFlmRecord[]; flashAlgorithms?: FlashAlgorithmRecord[]; algorithmBusy: boolean; algorithmError: string; canManageAlgorithms: boolean; algorithmNotRequired: boolean; selectionLocked?: boolean }>()
const emit = defineEmits<{ search: [value: string]; 'update:query': [value: string]; select: [target: TargetRecord]; selectAlgorithm: [algorithmId: string]; selectAlgorithms: [algorithmIds: string[]]; updateIndex: []; importPack: [file: File]; cancel: []; addAlgorithm: [file: File]; removeAlgorithm: [algorithmId: string] }>()
const query = ref(props.query)
const searchBox = ref<HTMLElement | null>(null)
const suggestionsOpen = ref(false)
const activeSuggestion = ref(-1)
let timer: ReturnType<typeof setTimeout> | undefined
let suppressNextSearch = false
watch(() => props.query, value => {
  if (value !== query.value) query.value = value
})
watch(query, value => {
  emit('update:query', value)
  clearTimeout(timer)
  if (suppressNextSearch) {
    suppressNextSearch = false
    return
  }
  timer = setTimeout(() => emit('search', value), 150)
})
watch(() => props.targets, targets => {
  activeSuggestion.value = targets.length ? 0 : -1
  if (searchBox.value?.contains(document.activeElement)) {
    suggestionsOpen.value = targets.length > 0
  }
})
onBeforeUnmount(() => clearTimeout(timer))
function addAlgorithm(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) emit('addAlgorithm', file)
}
function importPack(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) emit('importPack', file)
}
function selectTarget(target: TargetRecord): void {
  clearTimeout(timer)
  if (query.value !== target.part_number) {
    suppressNextSearch = true
    query.value = target.part_number
  }
  suggestionsOpen.value = false
  activeSuggestion.value = -1
  emit('select', target)
}
function onSearchInput(): void {
  suggestionsOpen.value = false
  activeSuggestion.value = -1
}
function onSearchFocus(): void {
  suggestionsOpen.value = props.targets.length > 0
}
function onSearchFocusOut(): void {
  setTimeout(() => {
    if (!searchBox.value?.contains(document.activeElement)) suggestionsOpen.value = false
  }, 0)
}
function onSearchKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    suggestionsOpen.value = false
    activeSuggestion.value = -1
    return
  }
  if (!props.targets.length) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    suggestionsOpen.value = true
    const delta = event.key === 'ArrowDown' ? 1 : -1
    const start = activeSuggestion.value < 0 ? (delta > 0 ? -1 : 0) : activeSuggestion.value
    activeSuggestion.value = (start + delta + props.targets.length) % props.targets.length
    return
  }
  if (event.key === 'Enter' && suggestionsOpen.value && activeSuggestion.value >= 0) {
    event.preventDefault()
    selectTarget(props.targets[activeSuggestion.value])
  }
}
function targetAvailability(target: TargetRecord): string {
  if (target.part_number.toLowerCase().startsWith('hpm')) return tr('内置 ROM API', 'Built-in ROM API')
  if (target.source === 'bundle' || target.source === 'builtin') return tr('内置可用', 'Built-in')
  if (target.installed) return tr('本地 Pack', 'Local Pack')
  return tr('可导入或联网下载', 'Import or download')
}
function hex(value: number): string { return `0x${value.toString(16).toUpperCase().padStart(8, '0')}` }
const visibleAlgorithms = computed<FlashAlgorithmRecord[]>(() => props.flashAlgorithms?.length ? props.flashAlgorithms : props.algorithms.map(algorithm => ({
  algorithm_id: algorithm.algorithm_id,
  target_part: algorithm.target_part,
  file_name: algorithm.file_name,
  flash_start: algorithm.flash_start,
  flash_size: algorithm.flash_size,
  default: false,
  source_kind: 'custom-flm',
  source_name: tr('用户 FLM', 'User FLM'),
})))
function algorithmSource(algorithm: FlashAlgorithmRecord): string {
  const kind = ({
    'installed-pack': tr('Pack FLM', 'Pack FLM'),
    'builtin-pack': tr('内置 Pack FLM', 'Built-in Pack FLM'),
    'daplink-builtin': tr('内置算法', 'Built-in algorithm'),
    'pyocd-builtin': tr('pyOCD 内置算法', 'pyOCD built-in algorithm'),
    'custom-flm': tr('自定义 FLM', 'Custom FLM'),
    'hpm-rom-api': 'HPM ROM API',
  } as Record<string, string>)[algorithm.source_kind] || algorithm.source_name
  return algorithm.source_name && algorithm.source_name !== kind && algorithm.source_kind !== 'hpm-rom-api'
    ? `${kind} · ${algorithm.source_name}`
    : kind
}
const chosenIds = computed(() => props.selectedAlgorithmIds?.length ? props.selectedAlgorithmIds : props.selectedAlgorithmId ? [props.selectedAlgorithmId] : [])
function toggleAlgorithm(algorithm: FlashAlgorithmRecord, checked: boolean): void {
  if (props.selectionLocked) return
  // Selecting an alternative for the same address replaces the previous one.
  const ids = chosenIds.value.filter(id => id !== algorithm.algorithm_id && (!checked || !visibleAlgorithms.value.some(other => other.algorithm_id === id && other.flash_start < algorithm.flash_start + algorithm.flash_size && algorithm.flash_start < other.flash_start + other.flash_size)))
  emit('selectAlgorithms', checked ? [...ids, algorithm.algorithm_id] : ids)
}
const phaseLabel = computed(() => ({
  preparing: tr('准备', 'Preparing'),
  downloading: tr('下载', 'Downloading'),
  refreshing: tr('安装并刷新', 'Installing and refreshing'),
}[props.phase] || tr('处理中', 'Processing')))
</script>

<template>
  <section class="target-panel">
    <div class="title-row"><h3>{{ tr('器件选择', 'Target Selection') }}</h3><span data-testid="pack-status" class="badge" :class="selectedPart && selectedInstalled ? 'ok' : ''">{{ selectedPart && selectedInstalled ? tr('已安装', 'Installed') : tr('未就绪', 'Not ready') }}</span></div>
    <div ref="searchBox" class="target-combobox" @focusout="onSearchFocusOut">
      <input v-model="query" data-testid="target-search" :disabled="selectionLocked" type="search" role="combobox" aria-autocomplete="list" aria-controls="target-suggestions" :aria-expanded="suggestionsOpen" :aria-activedescendant="suggestionsOpen && activeSuggestion >= 0 ? `target-option-${activeSuggestion}` : undefined" :placeholder="tr('搜索型号 / 厂商 / 系列', 'Search model / vendor / family / series')" :aria-label="tr('搜索器件', 'Search targets')" @input="onSearchInput" @focus="onSearchFocus" @keydown="onSearchKeydown">
      <div v-show="suggestionsOpen && targets.length" id="target-suggestions" class="target-list" role="listbox">
        <button v-for="(target, index) in targets" :id="`target-option-${index}`" :key="target.part_number" :data-testid="`target-${target.part_number}`" type="button" role="option" :aria-selected="selectedPart === target.part_number" :disabled="busy || algorithmBusy" :class="{ active: index === activeSuggestion || selectedPart === target.part_number }" @mouseenter="activeSuggestion = index" @click="selectTarget(target)">
          <strong>{{ target.part_number }}</strong><small>{{ target.vendor }} · {{ target.pack_id || tr('内置', 'Built-in') }}</small><span>{{ targetAvailability(target) }}</span>
        </button>
      </div>
    </div>
    <div v-if="busy" class="pack-progress"><progress :value="progress" max="1"/><span data-testid="pack-progress-label">{{ phaseLabel }} {{ Math.round(progress * 100) }}%</span><button data-testid="pack-cancel" :disabled="cancelPending" @click="emit('cancel')">{{ cancelPending ? tr('取消中…', 'Canceling…') : tr('取消', 'Cancel') }}</button></div>
    <p v-if="error" class="error">{{ error }}</p>
    <div class="pack-actions">
      <label class="file-button" :class="{ disabled: busy || algorithmBusy || selectionLocked }"><FolderInput :size="14"/>{{ tr('导入 Pack', 'Import Pack') }}<input data-testid="pack-import-input" type="file" accept=".pack" :disabled="busy || algorithmBusy || selectionLocked" @change="importPack"></label>
      <button :title="tr('下载器件索引；选择未安装型号可下载 Pack', 'Download the device index; select an uninstalled target to download its Pack')" data-testid="pack-update-index" :disabled="busy || algorithmBusy || selectionLocked" @click="emit('updateIndex')"><Download :size="14"/>{{ tr('联网下载', 'Download Online') }}</button>
      <label v-if="!algorithmNotRequired" class="file-button" :class="{ disabled: !canManageAlgorithms || algorithmBusy }"><FilePlus2 :size="14"/>{{ tr('添加 FLM', 'Add FLM') }}<input data-testid="custom-flm-input" type="file" accept=".flm" :disabled="!canManageAlgorithms || algorithmBusy" @change="addAlgorithm"></label>
    </div>
    <div class="algorithm-heading"><strong>{{ tr('烧录算法', 'Flash Algorithms') }}</strong><button v-if="!algorithmNotRequired" :disabled="selectionLocked || !chosenIds.length" data-testid="algorithm-auto" @click="emit('selectAlgorithms', [])"><RotateCcw :size="13"/>{{ chosenIds.length ? tr('恢复自动', 'Use auto') : tr('自动匹配', 'Automatic') }}</button></div>
    <details class="algorithm-plan" data-testid="algorithm-plan">
      <summary>{{ tr('镜像算法映射', 'Image algorithm map') }}<span>{{ algorithmPlan?.length ? tr(`${algorithmPlan.length} 套`, `${algorithmPlan.length} algorithms`) : tr('待检查', 'Not inspected') }}</span></summary>
      <div v-for="item in algorithmPlan" :key="item.algorithm_id" class="plan-row"><span>{{ item.file_name }}</span><small>{{ algorithmSource(item) }}</small><code v-for="range in item.ranges" :key="range.start">{{ hex(range.start) }}–{{ hex(range.end) }}</code></div>
      <p v-if="!algorithmPlan?.length">{{ algorithmNotRequired ? tr('HPM ROM API · 无需 FLM', 'HPM ROM API · No FLM required') : tr('检查镜像后显示每段地址使用的算法', 'Inspect an image to see its address-to-algorithm mapping') }}</p>
    </details>
    <details v-if="!algorithmNotRequired && visibleAlgorithms.length" class="algorithm-catalog" open>
      <summary>{{ chosenIds.length ? tr(`手动组合 · ${chosenIds.length} 个算法`, `Manual set · ${chosenIds.length} algorithms`) : tr(`可用算法 · ${visibleAlgorithms.length}`, `Available algorithms · ${visibleAlgorithms.length}`) }}</summary>
      <p class="algorithm-hint">{{ tr('同一地址选一套算法；内部与外部 Flash 可组合选择。', 'Choose one algorithm per address range; combine internal and external Flash.') }}</p>
      <div class="algorithm-list" data-testid="flash-algorithm-list">
        <div v-for="algorithm in visibleAlgorithms" :key="algorithm.algorithm_id" :data-testid="algorithm.source_kind === 'custom-flm' ? `custom-flm-${algorithm.algorithm_id}` : `flash-algorithm-${algorithm.algorithm_id}`" class="algorithm-row" :class="{ chosen: chosenIds.includes(algorithm.algorithm_id) }">
          <label class="algorithm-pick"><input type="checkbox" :aria-label="algorithm.file_name + ' · ' + algorithmSource(algorithm)" :checked="chosenIds.includes(algorithm.algorithm_id)" :disabled="selectionLocked || algorithmBusy" @change="toggleAlgorithm(algorithm, ($event.target as HTMLInputElement).checked)"><span><strong>{{ algorithm.file_name }}<em v-if="algorithmPlan?.some(item => item.algorithm_id === algorithm.algorithm_id)">{{ tr('镜像使用', 'In image') }}</em></strong><small>{{ algorithmSource(algorithm) }}</small><code>{{ hex(algorithm.flash_start) }}–{{ hex(algorithm.flash_start + algorithm.flash_size) }}</code></span></label>
          <button v-if="algorithm.source_kind === 'custom-flm'" :disabled="algorithmBusy || selectionLocked" @click="emit('removeAlgorithm', algorithm.algorithm_id)">{{ tr('移除', 'Remove') }}</button>
        </div>
      </div>
    </details>
    <label v-if="algorithmChoices?.length" class="algorithm-choice-label" for="flash-algorithm-choice">{{ tr('选择扇区布局对应的 FLM', 'Select the FLM matching the sector layout') }}</label>
    <select v-if="algorithmChoices?.length" id="flash-algorithm-choice" data-testid="flash-algorithm-choice" :value="selectedAlgorithmId || ''" :disabled="selectionLocked" @change="emit('selectAlgorithm', ($event.target as HTMLSelectElement).value)">
      <option value="">{{ tr('请选择实际 Bank 模式/算法', 'Select the actual bank mode / algorithm') }}</option>
      <option v-for="algorithm in algorithmChoices" :key="algorithm.algorithm_id" :value="algorithm.algorithm_id">{{ algorithm.file_name }}</option>
    </select>
    <p v-if="!algorithmNotRequired && !visibleAlgorithms.length" class="algorithm-empty">{{ algorithmBusy ? tr('正在读取烧录算法…', 'Loading flash algorithms…') : tr('当前器件未找到可用烧录算法', 'No flash algorithm found for this target') }}</p>
    <p v-if="algorithmError" class="error">{{ algorithmError }}</p>
  </section>
</template>

<style scoped>
.algorithm-choice-label{display:block;margin-top:10px;color:var(--of-muted);font-size:11px}#flash-algorithm-choice{width:100%;margin-top:5px;padding:7px;border:1px solid var(--of-border);border-radius:4px;background:var(--of-input);color:var(--of-text)}
.target-panel{padding:14px}.title-row,.pack-footer,.pack-progress,.algorithm-heading,.pack-actions{display:flex;align-items:center;justify-content:space-between;gap:8px}h3{margin:0;font-size:13px}input{box-sizing:border-box;width:100%;margin:10px 0;padding:8px;border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text)}.badge{padding:2px 7px;border-radius:10px;background:var(--of-danger-bg);color:var(--of-danger);font-size:10px}.badge.ok{background:var(--of-ok-bg);color:var(--of-ok)}.target-combobox{position:relative}.target-list{position:absolute;z-index:20;top:calc(100% - 8px);left:0;right:0;max-height:240px;overflow:auto;display:grid;gap:2px;padding:4px;border:1px solid var(--of-accent);border-radius:5px;background:var(--of-surface);box-shadow:0 8px 20px rgba(0,0,0,.3)}.target-list button{display:grid;grid-template-columns:1fr auto;text-align:left;padding:8px;border:1px solid transparent;border-radius:4px;background:var(--of-input);color:var(--of-text)}.target-list button.active{border-color:var(--of-accent);background:rgba(88,166,214,.16)}small{grid-column:1 / -1;color:var(--of-muted)}.target-list span{font-size:10px;color:var(--of-muted)}button,.file-button{border:1px solid var(--of-border);border-radius:4px;background:var(--of-input);color:var(--of-text);padding:5px 8px}.pack-progress{margin-top:8px;font-size:10px}.pack-progress progress{flex:1}.pack-footer{margin-top:10px;color:var(--of-muted);font-size:10px}.pack-actions{justify-content:flex-end}.algorithm-heading{margin-top:14px;padding-top:12px;border-top:1px solid var(--of-border);font-size:11px}.algorithm-not-required{display:flex;justify-content:space-between;color:var(--of-ok);font-size:10px}.file-button{position:relative;overflow:hidden;cursor:pointer}.file-button input{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer}.file-button.disabled{opacity:.45;cursor:not-allowed}.algorithm-list{display:grid;gap:5px;margin-top:7px}.algorithm-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 6px;padding:6px 0;border-bottom:1px solid var(--of-border);font-size:10px}.algorithm-row strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.algorithm-row span{grid-column:1;color:var(--of-muted)}.algorithm-row button{grid-column:2;grid-row:1 / span 2}.algorithm-empty{margin:7px 0 0;color:var(--of-muted);font-size:10px}.error{color:var(--of-danger);font-size:11px}

.target-panel{padding:10px 12px}.pack-actions{justify-content:flex-start;flex-wrap:wrap;gap:6px}.pack-actions button,.file-button,.algorithm-heading button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:28px;padding:4px 7px;font-size:11px;cursor:pointer;white-space:nowrap}.pack-actions button:hover:not(:disabled),.file-button:hover:not(.disabled),.algorithm-heading button:hover:not(:disabled){border-color:var(--of-accent);color:var(--of-accent)}button:disabled,.file-button.disabled{opacity:.5;cursor:default}.algorithm-heading{margin-top:10px;padding-top:10px}.algorithm-plan{margin-top:8px;padding:8px;border:1px solid var(--of-border);border-radius:6px;font-size:11px;background:var(--of-input)}.algorithm-plan>strong{font-size:10px;color:var(--of-muted)}.algorithm-plan p,.algorithm-hint{font-size:10px;color:var(--of-muted);line-height:1.5;margin:5px 0}.plan-row{display:grid;gap:2px;margin-top:6px}.plan-row code{font-size:10px;color:var(--of-muted)}.algorithm-catalog{margin-top:10px}.algorithm-catalog summary{cursor:pointer;font-size:11px}.algorithm-list{max-height:260px;overflow:auto}.algorithm-row{display:flex;align-items:center;padding:6px;gap:6px;border-radius:5px}.algorithm-row.chosen{background:color-mix(in srgb,var(--of-accent) 12%,transparent)}.algorithm-pick{display:flex;align-items:flex-start;gap:7px;min-width:0;flex:1;cursor:pointer}.algorithm-pick input{width:14px;height:14px;margin:2px 0;flex-shrink:0;accent-color:var(--of-accent)}.algorithm-pick span{display:grid;gap:3px;min-width:0}.algorithm-pick strong{font-size:11px}.algorithm-pick small,.algorithm-pick code{font-size:10px;overflow-wrap:anywhere}.algorithm-row button{font-size:10px;flex-shrink:0}

.algorithm-plan summary{display:flex;align-items:center;justify-content:space-between;gap:8px;cursor:pointer;font-size:11px}.algorithm-plan summary:before{content:'▸';color:var(--of-muted)}.algorithm-plan[open] summary:before{content:'▾'}.algorithm-plan summary span{margin-left:auto;color:var(--of-accent)}.algorithm-pick strong{display:flex;align-items:center;gap:6px}.algorithm-pick em{font-size:9px;font-style:normal;color:var(--of-ok);flex-shrink:0}.algorithm-catalog{margin-top:8px}
</style>
