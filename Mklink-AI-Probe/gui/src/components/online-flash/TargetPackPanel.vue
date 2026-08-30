<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { CustomFlmRecord, PackStatus, TargetRecord } from '../../types/onlineFlash'
import { tr } from '../../composables/useLanguage'

const props = defineProps<{ targets: TargetRecord[]; query: string; selectedPart: string; selectedInstalled: boolean; status: PackStatus | null; busy: boolean; cancelPending: boolean; progress: number; phase: string; error: string; algorithms: CustomFlmRecord[]; algorithmBusy: boolean; algorithmError: string; canManageAlgorithms: boolean; algorithmNotRequired: boolean }>()
const emit = defineEmits<{ search: [value: string]; 'update:query': [value: string]; select: [target: TargetRecord]; updateIndex: []; importPack: [file: File]; cancel: []; addAlgorithm: [file: File]; removeAlgorithm: [algorithmId: string] }>()
const query = ref(props.query)
let timer: ReturnType<typeof setTimeout> | undefined
watch(() => props.query, value => {
  if (value !== query.value) query.value = value
})
watch(query, value => {
  emit('update:query', value)
  clearTimeout(timer)
  timer = setTimeout(() => emit('search', value), 300)
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
  query.value = target.part_number
  emit('select', target)
}
function targetAvailability(target: TargetRecord): string {
  if (target.part_number.toLowerCase().startsWith('hpm')) return tr('内置 ROM API', 'Built-in ROM API')
  if (target.source === 'bundle' || target.source === 'builtin') return tr('内置可用', 'Built-in')
  if (target.installed) return tr('本地 Pack', 'Local Pack')
  return tr('可导入或联网下载', 'Import or download')
}
function hex(value: number): string { return `0x${value.toString(16).toUpperCase().padStart(8, '0')}` }
const phaseLabel = computed(() => ({
  preparing: tr('准备', 'Preparing'),
  downloading: tr('下载', 'Downloading'),
  refreshing: tr('安装并刷新', 'Installing and refreshing'),
}[props.phase] || tr('处理中', 'Processing')))
</script>

<template>
  <section class="target-panel">
    <div class="title-row"><h3>{{ tr('器件选择', 'Target Selection') }}</h3><span data-testid="pack-status" class="badge" :class="selectedPart && selectedInstalled ? 'ok' : ''">{{ selectedPart && selectedInstalled ? tr('已安装', 'Installed') : tr('未就绪', 'Not ready') }}</span></div>
    <input v-model="query" data-testid="target-search" type="search" :placeholder="tr('搜索型号 / 厂商 / 系列', 'Search model / vendor / family')" :aria-label="tr('搜索器件', 'Search targets')">
    <div class="target-list">
      <button v-for="target in targets" :key="target.part_number" :data-testid="`target-${target.part_number}`" :disabled="busy || algorithmBusy" :class="{ active: selectedPart === target.part_number }" @click="selectTarget(target)">
        <strong>{{ target.part_number }}</strong><small>{{ target.vendor }} · {{ target.pack_id || tr('内置', 'Built-in') }}</small><span>{{ targetAvailability(target) }}</span>
      </button>
    </div>
    <div v-if="busy" class="pack-progress"><progress :value="progress" max="1"/><span data-testid="pack-progress-label">{{ phaseLabel }} {{ Math.round(progress * 100) }}%</span><button data-testid="pack-cancel" :disabled="cancelPending" @click="emit('cancel')">{{ cancelPending ? tr('取消中…', 'Canceling…') : tr('取消', 'Cancel') }}</button></div>
    <p v-if="error" class="error">{{ error }}</p>
    <div class="pack-footer"><span>{{ tr('索引', 'Index') }} {{ status?.index_available ? tr('可用', 'available') : tr('不可用', 'unavailable') }} · {{ status?.target_count ?? 0 }} {{ tr('型号', 'targets') }}</span><div class="pack-actions"><label class="file-button" :class="{ disabled: busy || algorithmBusy }">{{ tr('导入 Pack', 'Import Pack') }}<input data-testid="pack-import-input" type="file" accept=".pack" :disabled="busy || algorithmBusy" @change="importPack"></label><button data-testid="pack-update-index" :disabled="busy || algorithmBusy" @click="emit('updateIndex')">{{ tr('联网更新', 'Update Online') }}</button></div></div>
    <div v-if="algorithmNotRequired" class="algorithm-not-required"><strong>HPM ROM API</strong><span>{{ tr('无需 FLM', 'No FLM required') }}</span></div>
    <div v-else class="algorithm-heading"><span>{{ tr('自定义下载算法', 'Custom Flash Algorithms') }}</span><label class="file-button" :class="{ disabled: !canManageAlgorithms || algorithmBusy }">{{ tr('添加 FLM', 'Add FLM') }}<input data-testid="custom-flm-input" type="file" accept=".flm" :disabled="!canManageAlgorithms || algorithmBusy" @change="addAlgorithm"></label></div>
    <div v-if="!algorithmNotRequired && algorithms.length" class="algorithm-list">
      <div v-for="algorithm in algorithms" :key="algorithm.algorithm_id" :data-testid="`custom-flm-${algorithm.algorithm_id}`" class="algorithm-row">
        <strong>{{ algorithm.file_name }}</strong><span>{{ hex(algorithm.flash_start) }} · {{ algorithm.flash_size }} B</span><button :disabled="algorithmBusy" @click="emit('removeAlgorithm', algorithm.algorithm_id)">{{ tr('移除', 'Remove') }}</button>
      </div>
    </div>
    <p v-else-if="!algorithmNotRequired" class="algorithm-empty">{{ tr('当前器件未添加自定义 FLM', 'No custom FLM added for this target') }}</p>
    <p v-if="algorithmError" class="error">{{ algorithmError }}</p>
  </section>
</template>

<style scoped>
.target-panel{padding:14px}.title-row,.pack-footer,.pack-progress,.algorithm-heading,.pack-actions{display:flex;align-items:center;justify-content:space-between;gap:8px}h3{margin:0;font-size:13px}input{box-sizing:border-box;width:100%;margin:10px 0;padding:8px;border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text)}.badge{padding:2px 7px;border-radius:10px;background:var(--of-danger-bg);color:var(--of-danger);font-size:10px}.badge.ok{background:var(--of-ok-bg);color:var(--of-ok)}.target-list{max-height:175px;overflow:auto;display:grid;gap:5px}.target-list button{display:grid;grid-template-columns:1fr auto;text-align:left;padding:8px;border:1px solid transparent;border-radius:5px;background:var(--of-input);color:var(--of-text)}.target-list button.active{border-color:var(--of-accent)}small{grid-column:1 / -1;color:var(--of-muted)}.target-list span{font-size:10px;color:var(--of-muted)}button,.file-button{border:1px solid var(--of-border);border-radius:4px;background:var(--of-input);color:var(--of-text);padding:5px 8px}.pack-progress{margin-top:8px;font-size:10px}.pack-progress progress{flex:1}.pack-footer{margin-top:10px;color:var(--of-muted);font-size:10px}.pack-actions{justify-content:flex-end}.algorithm-heading{margin-top:14px;padding-top:12px;border-top:1px solid var(--of-border);font-size:11px}.algorithm-not-required{display:flex;align-items:center;justify-content:space-between;margin-top:14px;padding-top:12px;border-top:1px solid var(--of-border);color:var(--of-ok);font-size:11px}.file-button{position:relative;overflow:hidden;cursor:pointer}.file-button input{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer}.file-button.disabled{opacity:.45;cursor:not-allowed}.algorithm-list{display:grid;gap:5px;margin-top:7px}.algorithm-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 6px;padding:6px 0;border-bottom:1px solid var(--of-border);font-size:10px}.algorithm-row strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.algorithm-row span{color:var(--of-muted)}.algorithm-row button{grid-column:2;grid-row:1 / span 2}.algorithm-empty{margin:7px 0 0;color:var(--of-muted);font-size:10px}.error{color:var(--of-danger);font-size:11px}
</style>
