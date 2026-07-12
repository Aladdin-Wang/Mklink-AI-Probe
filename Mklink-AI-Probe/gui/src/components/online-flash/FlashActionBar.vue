<script setup lang="ts">
import type { JobAction, JobState } from '../../types/onlineFlash'
const props = defineProps<{ actions: JobAction[]; canStart: boolean; active: boolean; stopping: boolean; state: JobState | null; stageProgress: number; totalProgress: number }>()
const emit = defineEmits<{ actions: [actions: JobAction[]]; start: []; stop: [] }>()
const choices: Array<{ value: JobAction; label: string }> = [{value:'connect',label:'连接'},{value:'erase',label:'擦除'},{value:'program',label:'烧录'},{value:'verify',label:'校验'},{value:'reset',label:'复位'},{value:'disconnect',label:'断开'}]
function toggle(action: JobAction, checked: boolean) { emit('actions', checked ? [...props.actions, action] : props.actions.filter(value => value !== action)) }
const stateLabel = (state: JobState | null) => state === 'stopping' ? 'STOPPING' : state === 'stopped' ? '已停止' : state?.toUpperCase() || '待命'
</script>
<template>
  <div class="action-bar"><div class="action-choices"><label v-for="choice in choices" :key="choice.value"><input type="checkbox" :checked="actions.includes(choice.value)" :disabled="active" @change="toggle(choice.value, ($event.target as HTMLInputElement).checked)">{{ choice.label }}</label></div><div class="progresses"><span>阶段 <progress :value="stageProgress" max="1"/></span><span>总进度 <progress :value="totalProgress" max="1"/></span></div><span data-testid="job-state" class="state">{{ stateLabel(state) }}</span><span v-if="stopping" class="waiting">等待探针安全停止</span><button data-testid="start-job" :disabled="!canStart" class="primary" @click="$emit('start')">开始烧录</button><button data-testid="stop-job" :disabled="!active || stopping" class="stop" @click="$emit('stop')">停止</button></div>
</template>
<style scoped>
.action-bar{display:flex;align-items:center;gap:12px;padding:9px 11px;border-top:1px solid var(--of-border);background:#1a1f25;font-size:10px}.action-choices{display:flex;gap:6px}.action-choices label{color:var(--of-muted)}.progresses{display:grid;gap:3px;margin-left:auto}.progresses span{display:flex;gap:5px;align-items:center}.progresses progress{width:75px;height:5px}.state{min-width:58px;color:var(--of-accent);font-weight:700}.waiting{color:var(--of-warn)}button{padding:7px 10px;border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text)}button.primary{border-color:var(--of-accent);background:#263648}button.stop{color:var(--of-danger)}button:disabled{opacity:.4}
</style>
