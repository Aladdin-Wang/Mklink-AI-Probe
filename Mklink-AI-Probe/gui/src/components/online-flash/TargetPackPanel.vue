<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import type { CustomFlmRecord, PackStatus, TargetRecord } from '../../types/onlineFlash'

defineProps<{ targets: TargetRecord[]; selectedPart: string; status: PackStatus | null; busy: boolean; cancelPending: boolean; progress: number; error: string; algorithms: CustomFlmRecord[]; algorithmBusy: boolean; algorithmError: string; canManageAlgorithms: boolean }>()
const emit = defineEmits<{ search: [value: string]; select: [target: TargetRecord]; updateIndex: []; importPack: [file: File]; cancel: []; addAlgorithm: [file: File]; removeAlgorithm: [algorithmId: string] }>()
const query = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
watch(query, value => {
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
function targetAvailability(target: TargetRecord): string {
  if (target.source === 'bundle' || target.source === 'builtin') return '内置可用'
  if (target.installed) return '本地 Pack'
  return '可导入或联网下载'
}
function hex(value: number): string { return `0x${value.toString(16).toUpperCase().padStart(8, '0')}` }
</script>

<template>
  <section class="target-panel">
    <div class="title-row"><h3>器件选择</h3><span data-testid="pack-status" class="badge" :class="selectedPart && targets.find(t => t.part_number === selectedPart)?.installed ? 'ok' : ''">{{ selectedPart && targets.find(t => t.part_number === selectedPart)?.installed ? '已安装' : '未就绪' }}</span></div>
    <input v-model="query" data-testid="target-search" type="search" placeholder="搜索型号 / 厂商 / 系列" aria-label="搜索器件">
    <div class="target-list">
      <button v-for="target in targets" :key="target.part_number" :data-testid="`target-${target.part_number}`" :disabled="busy || algorithmBusy" :class="{ active: selectedPart === target.part_number }" @click="emit('select', target)">
        <strong>{{ target.part_number }}</strong><small>{{ target.vendor }} · {{ target.pack_id || '内置' }}</small><span>{{ targetAvailability(target) }}</span>
      </button>
    </div>
    <div v-if="busy" class="pack-progress"><progress :value="progress" max="1"/><span>{{ Math.round(progress * 100) }}%</span><button data-testid="pack-cancel" :disabled="cancelPending" @click="emit('cancel')">{{ cancelPending ? '取消中…' : '取消' }}</button></div>
    <p v-if="error" class="error">{{ error }}</p>
    <div class="pack-footer"><span>索引 {{ status?.index_available ? '可用' : '不可用' }} · {{ status?.target_count ?? 0 }} 型号</span><div class="pack-actions"><label class="file-button" :class="{ disabled: busy || algorithmBusy }">导入 Pack<input data-testid="pack-import-input" type="file" accept=".pack" :disabled="busy || algorithmBusy" @change="importPack"></label><button data-testid="pack-update-index" :disabled="busy || algorithmBusy" @click="emit('updateIndex')">联网更新</button></div></div>
    <div class="algorithm-heading"><span>自定义下载算法</span><label class="file-button" :class="{ disabled: !canManageAlgorithms || algorithmBusy }">添加 FLM<input data-testid="custom-flm-input" type="file" accept=".flm" :disabled="!canManageAlgorithms || algorithmBusy" @change="addAlgorithm"></label></div>
    <div v-if="algorithms.length" class="algorithm-list">
      <div v-for="algorithm in algorithms" :key="algorithm.algorithm_id" :data-testid="`custom-flm-${algorithm.algorithm_id}`" class="algorithm-row">
        <strong>{{ algorithm.file_name }}</strong><span>{{ hex(algorithm.flash_start) }} · {{ algorithm.flash_size }} B</span><button :disabled="algorithmBusy" @click="emit('removeAlgorithm', algorithm.algorithm_id)">移除</button>
      </div>
    </div>
    <p v-else class="algorithm-empty">当前器件未添加自定义 FLM</p>
    <p v-if="algorithmError" class="error">{{ algorithmError }}</p>
  </section>
</template>

<style scoped>
.target-panel{padding:14px}.title-row,.pack-footer,.pack-progress,.algorithm-heading,.pack-actions{display:flex;align-items:center;justify-content:space-between;gap:8px}h3{margin:0;font-size:13px}input{box-sizing:border-box;width:100%;margin:10px 0;padding:8px;border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text)}.badge{padding:2px 7px;border-radius:10px;background:var(--of-danger-bg);color:var(--of-danger);font-size:10px}.badge.ok{background:var(--of-ok-bg);color:var(--of-ok)}.target-list{max-height:175px;overflow:auto;display:grid;gap:5px}.target-list button{display:grid;grid-template-columns:1fr auto;text-align:left;padding:8px;border:1px solid transparent;border-radius:5px;background:var(--of-input);color:var(--of-text)}.target-list button.active{border-color:var(--of-accent)}small{grid-column:1 / -1;color:var(--of-muted)}.target-list span{font-size:10px;color:var(--of-muted)}button,.file-button{border:1px solid var(--of-border);border-radius:4px;background:var(--of-input);color:var(--of-text);padding:5px 8px}.pack-progress{margin-top:8px;font-size:10px}.pack-progress progress{flex:1}.pack-footer{margin-top:10px;color:var(--of-muted);font-size:10px}.pack-actions{justify-content:flex-end}.algorithm-heading{margin-top:14px;padding-top:12px;border-top:1px solid var(--of-border);font-size:11px}.file-button{position:relative;overflow:hidden;cursor:pointer}.file-button input{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer}.file-button.disabled{opacity:.45;cursor:not-allowed}.algorithm-list{display:grid;gap:5px;margin-top:7px}.algorithm-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 6px;padding:6px 0;border-bottom:1px solid var(--of-border);font-size:10px}.algorithm-row strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.algorithm-row span{color:var(--of-muted)}.algorithm-row button{grid-column:2;grid-row:1 / span 2}.algorithm-empty{margin:7px 0 0;color:var(--of-muted);font-size:10px}.error{color:var(--of-danger);font-size:11px}
</style>
