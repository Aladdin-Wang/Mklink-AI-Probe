<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ lines: string[]; streamDisconnected: boolean }>()
const emit = defineEmits<{ clear: []; reconnect: [] }>()
const visibleLines = computed(() => props.lines.slice(-200))
async function copy() { await navigator.clipboard?.writeText(props.lines.join('\n')) }
function exportLog() { const url = URL.createObjectURL(new Blob([props.lines.join('\n')], {type:'text/plain'})); const link = document.createElement('a'); link.href=url; link.download='online-flash.log'; link.click(); URL.revokeObjectURL(url) }
</script>
<template>
  <header><h3>任务日志 <span>{{ lines.length }}/5000</span></h3><div><button v-if="streamDisconnected" data-testid="reconnect-stream" @click="$emit('reconnect')">从断点重连</button><button @click="copy">复制</button><button @click="exportLog">导出</button><button @click="$emit('clear')">清空</button></div></header><div class="log-window"><p v-if="!visibleLines.length">等待在线烧录任务</p><div v-for="(line,index) in visibleLines" :key="`${index}-${line}`" data-testid="log-line">{{ line }}</div></div>
</template>
<style scoped>
header{display:flex;justify-content:space-between;align-items:center;padding:7px 10px;border-bottom:1px solid var(--of-border)}h3{margin:0;font-size:12px}h3 span{color:var(--of-muted);font-weight:400}button{margin-left:5px;padding:4px 7px;border:1px solid var(--of-border);border-radius:4px;background:var(--of-input);color:var(--of-text);font-size:10px}.log-window{height:135px;overflow:auto;padding:7px 10px;text-align:left;background:#101318;color:#aeb8c4;font:10px/18px var(--of-mono)}.log-window p{color:var(--of-muted)}
</style>
