<script setup lang="ts">
import type { JobAction, JobState } from '../../types/onlineFlash'
const props = defineProps<{ actions: JobAction[]; canStart: boolean; active: boolean; stopping: boolean; state: JobState | null; stageProgress: number; totalProgress: number }>()
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
</script>
<template>
  <div class="action-bar"><div class="action-choices"><label v-for="choice in choices" :key="choice.value"><input type="checkbox" :checked="actions.includes(choice.value)" :disabled="active || mandatory.has(choice.value)" @change="toggle(choice.value, ($event.target as HTMLInputElement).checked)">{{ choice.label }}</label></div><div class="progresses"><span>当前阶段 <progress data-testid="stage-progress" :value="stageProgress" max="1"/></span><span>任务总进度 <progress data-testid="total-progress" :value="totalProgress" max="1"/></span></div><span data-testid="job-state" class="state">{{ stateLabel(state) }}</span><span v-if="stopping" class="waiting">等待探针安全停止</span><button data-testid="start-job" :disabled="!canStart" class="primary" @click="$emit('start')">开始烧录</button><button data-testid="stop-job" :disabled="!active || stopping" class="stop" @click="$emit('stop')">停止</button></div>
</template>
<style scoped>
.action-bar{display:flex;flex-wrap:wrap;max-width:100%;box-sizing:border-box;align-items:center;gap:12px;padding:9px 11px;border-top:1px solid var(--of-border);background:#1a1f25;font-size:10px}.action-choices{display:flex;flex-wrap:wrap;gap:6px}.action-choices label{color:var(--of-muted)}.progresses{display:grid;gap:3px;margin-left:auto}.progresses span{display:flex;gap:5px;align-items:center}.progresses progress{width:75px;height:5px}.state{min-width:58px;color:var(--of-accent);font-weight:700}.waiting{color:var(--of-warn)}button{padding:7px 10px;border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text)}button.primary{border-color:var(--of-accent);background:#263648}button.stop{color:var(--of-danger)}button:disabled{opacity:.4}
</style>
