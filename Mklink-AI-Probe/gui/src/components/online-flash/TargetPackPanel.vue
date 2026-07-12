<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import type { PackStatus, TargetRecord } from '../../types/onlineFlash'

defineProps<{ targets: TargetRecord[]; selectedPart: string; status: PackStatus | null; busy: boolean; cancelPending: boolean; progress: number; error: string }>()
const emit = defineEmits<{ search: [value: string]; select: [target: TargetRecord]; updateIndex: []; cancel: [] }>()
const query = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
watch(query, value => {
  clearTimeout(timer)
  timer = setTimeout(() => emit('search', value), 300)
})
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <section class="target-panel">
    <div class="title-row"><h3>器件选择</h3><span data-testid="pack-status" class="badge" :class="selectedPart && targets.find(t => t.part_number === selectedPart)?.installed ? 'ok' : ''">{{ selectedPart && targets.find(t => t.part_number === selectedPart)?.installed ? '已安装' : '未就绪' }}</span></div>
    <input v-model="query" type="search" placeholder="搜索型号 / 厂商 / 系列" aria-label="搜索器件">
    <div class="target-list">
      <button v-for="target in targets" :key="target.part_number" :data-testid="`target-${target.part_number}`" :disabled="busy" :class="{ active: selectedPart === target.part_number }" @click="emit('select', target)">
        <strong>{{ target.part_number }}</strong><small>{{ target.vendor }} · {{ target.pack_id || '内置' }}</small><span>{{ target.installed ? '已安装' : '需下载 Pack' }}</span>
      </button>
    </div>
    <div v-if="busy" class="pack-progress"><progress :value="progress" max="1"/><span>{{ Math.round(progress * 100) }}%</span><button data-testid="pack-cancel" :disabled="cancelPending" @click="emit('cancel')">{{ cancelPending ? '取消中…' : '取消' }}</button></div>
    <p v-if="error" class="error">{{ error }}</p>
    <div class="pack-footer"><span>索引 {{ status?.index_available ? '可用' : '不可用' }} · {{ status?.target_count ?? 0 }} 型号</span><button :disabled="busy" @click="emit('updateIndex')">更新索引</button></div>
  </section>
</template>

<style scoped>
.target-panel{padding:14px}.title-row,.pack-footer,.pack-progress{display:flex;align-items:center;justify-content:space-between;gap:8px}h3{margin:0;font-size:13px}input{box-sizing:border-box;width:100%;margin:10px 0;padding:8px;border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text)}.badge{padding:2px 7px;border-radius:10px;background:var(--of-danger-bg);color:var(--of-danger);font-size:10px}.badge.ok{background:var(--of-ok-bg);color:var(--of-ok)}.target-list{max-height:175px;overflow:auto;display:grid;gap:5px}.target-list button{display:grid;grid-template-columns:1fr auto;text-align:left;padding:8px;border:1px solid transparent;border-radius:5px;background:var(--of-input);color:var(--of-text)}.target-list button.active{border-color:var(--of-accent)}small{grid-column:1 / -1;color:var(--of-muted)}.target-list span{font-size:10px;color:var(--of-muted)}button{border:1px solid var(--of-border);border-radius:4px;background:var(--of-input);color:var(--of-text);padding:5px 8px}.pack-progress{margin-top:8px;font-size:10px}.pack-progress progress{flex:1}.pack-footer{margin-top:10px;color:var(--of-muted);font-size:10px}.error{color:var(--of-danger);font-size:11px}
</style>
