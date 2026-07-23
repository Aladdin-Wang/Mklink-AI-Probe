<script setup lang="ts">
import { computed } from 'vue'
import { Play, Square } from '@lucide/vue'
import type { JobAction, JobState } from '../../types/onlineFlash'
const props = defineProps<{ actions: JobAction[]; canStart: boolean; active: boolean; stopping: boolean; state: JobState | null; totalProgress: number }>()
const emit = defineEmits<{ actions: [actions: JobAction[]]; start: []; stop: [] }>()
const choices: Array<{ value: JobAction; label: string }> = [{value:'connect',label:'连接'},{value:'erase',label:'擦除'},{value:'program',label:'烧录'},{value:'verify',label:'校验'},{value:'reset',label:'复位'},{value:'disconnect',label:'断开'}]
const mandatory = new Set<JobAction>(['connect', 'disconnect'])
function toggle(action: JobAction, checked: boolean) {
  if (mandatory.has(action)) return
  const selected = new Set(props.actions)
  if (checked) selected.add(action)
  else selected.delete(action)
  emit('actions', choices.map(choice => choice.value).filter(value => mandatory.has(value) || selected.has(value)))
}
const stateLabel = (state: JobState | null) => state === 'stopping' ? 'STOPPING' : state === 'stopped' ? '已停止' : state?.toUpperCase() || '待命'
const totalPercent = computed(() => Math.round(Math.min(1, Math.max(0, props.totalProgress)) * 100))
</script>
<template>
  <div class="action-bar">
    <div class="action-choices">
      <label v-for="choice in choices" :key="choice.value">
        <input type="checkbox" :checked="actions.includes(choice.value)" :disabled="active || mandatory.has(choice.value)" @change="toggle(choice.value, ($event.target as HTMLInputElement).checked)">
        {{ choice.label }}
      </label>
    </div>
    <div class="progress-block">
      <div class="progress-meta">
        <span class="progress-title">烧录总进度</span>
        <span data-testid="job-state" class="state">{{ stateLabel(state) }}</span>
        <strong data-testid="total-progress-label">{{ totalPercent }}%</strong>
      </div>
      <progress data-testid="total-progress" :value="totalProgress" max="1" aria-label="烧录总进度" />
    </div>
    <span v-if="stopping" class="waiting">等待探针安全停止</span>
    <div class="job-actions">
      <button data-testid="start-job" :disabled="!canStart" class="primary" @click="$emit('start')">
        <Play :size="14" aria-hidden="true" />
        开始烧录
      </button>
      <button data-testid="stop-job" :disabled="!active || stopping" class="stop" @click="$emit('stop')">
        <Square :size="13" aria-hidden="true" />
        停止
      </button>
    </div>
  </div>
</template>
<style scoped>
.action-bar{display:flex;flex-wrap:wrap;max-width:100%;box-sizing:border-box;align-items:center;gap:12px;padding:10px 12px;border-top:1px solid var(--of-border);background:#1a1f25;font-size:10px}.action-choices{display:flex;flex-wrap:wrap;gap:7px}.action-choices label{display:flex;align-items:center;gap:3px;color:var(--of-muted)}.progress-block{display:grid;flex:1 1 220px;min-width:180px;max-width:360px;gap:5px;margin-left:auto}.progress-meta{display:grid;grid-template-columns:auto minmax(58px,1fr) auto;align-items:center;gap:8px}.progress-title{color:var(--of-muted)}.progress-meta strong{color:var(--of-text);font-variant-numeric:tabular-nums}.progress-block progress{width:100%;height:7px;accent-color:var(--of-accent)}.progress-block progress::-webkit-progress-bar{border-radius:3px;background:#0f1317}.progress-block progress::-webkit-progress-value{border-radius:3px;background:var(--of-accent)}.state{overflow:hidden;color:var(--of-accent);font-weight:700;text-overflow:ellipsis;white-space:nowrap}.waiting{flex-basis:100%;color:var(--of-warn);text-align:right}.job-actions{display:flex;gap:7px}.job-actions button{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:32px;padding:7px 10px;border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text)}button.primary{border-color:var(--of-accent);background:#263648}button.stop{color:var(--of-danger)}button:disabled{opacity:.4}@media(max-width:720px){.progress-block{order:3;max-width:none;margin-left:0}.job-actions{margin-left:auto}}
</style>
