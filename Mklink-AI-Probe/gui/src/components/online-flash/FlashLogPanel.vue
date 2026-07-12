<script setup lang="ts">
import { computed, ref } from 'vue'
const props = defineProps<{ lines: string[]; streamDisconnected: boolean }>()
defineEmits<{ clear: []; reconnect: [] }>()
const ROW_HEIGHT = 18
const VIEWPORT_HEIGHT = 135
const OVERSCAN = 10
const scrollTop = ref(0)
const start = computed(() => Math.max(0, Math.floor(scrollTop.value / ROW_HEIGHT) - OVERSCAN))
const count = Math.ceil(VIEWPORT_HEIGHT / ROW_HEIGHT) + OVERSCAN * 2
const end = computed(() => Math.min(props.lines.length, start.value + count))
const visibleLines = computed(() => props.lines.slice(start.value, end.value))
const paddingTop = computed(() => start.value * ROW_HEIGHT)
const paddingBottom = computed(() => Math.max(0, (props.lines.length - end.value) * ROW_HEIGHT))
function scrolled(event: Event) { scrollTop.value = (event.currentTarget as HTMLElement).scrollTop }
async function copy() { await navigator.clipboard?.writeText(props.lines.join('\n')) }
function exportLog() { const url = URL.createObjectURL(new Blob([props.lines.join('\n')], {type:'text/plain'})); const link = document.createElement('a'); link.href=url; link.download='online-flash.log'; link.click(); URL.revokeObjectURL(url) }
</script>
<template>
  <header><h3>任务日志 <span>{{ lines.length }}/5000</span></h3><div><button v-if="streamDisconnected" data-testid="reconnect-stream" @click="$emit('reconnect')">从断点重连</button><button @click="copy">复制</button><button @click="exportLog">导出</button><button @click="$emit('clear')">清空</button></div></header>
  <div data-testid="log-viewport" class="log-window" @scroll="scrolled"><p v-if="!visibleLines.length">等待在线烧录任务</p><div :style="{height:`${paddingTop}px`}"/><div v-for="(line,index) in visibleLines" :key="start + index" data-testid="log-line">{{ line }}</div><div :style="{height:`${paddingBottom}px`}"/></div>
</template>
<style scoped>
header{display:flex;justify-content:space-between;align-items:center;padding:7px 10px;border-bottom:1px solid var(--of-border)}h3{margin:0;font-size:12px}h3 span{color:var(--of-muted);font-weight:400}button{margin-left:5px;padding:4px 7px;border:1px solid var(--of-border);border-radius:4px;background:var(--of-input);color:var(--of-text);font-size:10px}.log-window{height:135px;overflow:auto;padding:0 10px;text-align:left;background:#101318;color:#aeb8c4;font:10px/18px var(--of-mono)}.log-window p{color:var(--of-muted)}
</style>
