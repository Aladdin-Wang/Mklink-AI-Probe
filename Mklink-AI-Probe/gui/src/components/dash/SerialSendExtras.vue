<template>
  <details class="send-extras" data-testid="serial-send-extras">
    <summary>{{ tr('广播与原始文件', 'Broadcast and raw files') }}</summary>
    <p>{{ tr('广播目标：', 'Broadcast targets: ') }}{{ ports.join(', ') || '--' }}</p>
    <div class="row">
      <select v-model="hex" :disabled="busy" :aria-label="tr('广播格式', 'Broadcast format')"><option :value="false">UTF-8</option><option :value="true">HEX</option></select>
      <input v-model="data" data-testid="broadcast-data" :disabled="busy" maxlength="16384" :aria-label="tr('广播内容', 'Broadcast content')">
      <button type="button" data-testid="broadcast-send" :disabled="busy || !running || !data || !ports.length" @click="emit('broadcast', {data, hex})">{{ tr('广播一次', 'Broadcast once') }}</button>
    </div>
    <div class="row">
      <input type="file" data-testid="raw-file" :disabled="busy || fileActive" @change="selectFile">
      <label><input v-model="fileHex" type="checkbox" :disabled="busy || fileActive">{{ tr('文件内容是 HEX 文本', 'File contains HEX text') }}</label>
      <button type="button" data-testid="raw-file-send" :disabled="busy || fileActive || !running || !port || !file" @click="sendFile">{{ tr('发送文件到', 'Send file to') }} {{ port || '--' }}</button>
    </div>
    <p class="hint">{{ tr('原始数据最多 64 KiB，HEX 文本文件最多 256 KiB。文件分段提交到上方命令队列，可在那里查看和停止；不会自动重试，也不代表目标已确认接收。', 'Raw payload: up to 64 KiB; HEX text file: up to 256 KiB. Files use the command sequence above for progress and stop. No automatic retry or target acknowledgement.') }}</p>
    <p v-if="notice" data-testid="send-extras-notice">{{ notice }}</p>
    <p v-if="localError || error" role="alert">{{ localError || error }}</p>
    <ul v-if="results" data-testid="broadcast-results"><li v-for="(result, name) in results" :key="name">{{ name }}: {{ result.ok ? tr('写入完成', 'Written') : result.error }}</li></ul>
  </details>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { tr } from '../../composables/useLanguage'
export interface BroadcastResult { ok: boolean; error?: string; bytes?: number }
const props = defineProps<{port: string; ports: string[]; running: boolean; fileActive: boolean; busy: boolean; error: string; notice: string; results: Record<string, BroadcastResult> | null}>()
const emit = defineEmits<{broadcast: [request: {data: string; hex: boolean}]; file: [file: File, hex: boolean, port: string]}>()
const data = ref(''), hex = ref(false), fileHex = ref(false), file = ref<File | null>(null), localError = ref('')
function selectFile(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] || null; localError.value = '' }
function sendFile() {
  if (props.busy || props.fileActive || !props.running || !props.port || !file.value) return
  localError.value = ''
  if (!file.value.size || file.value.size > (fileHex.value ? 262144 : 65536)) {
    localError.value = tr('文件为空或超过大小上限。', 'File is empty or exceeds the size limit.'); return
  }
  emit('file', file.value, fileHex.value, props.port)
}
</script>
<style scoped>
.send-extras { border: 1px solid var(--border); border-radius: 5px; padding: 8px 10px; font-size: 12px; margin-bottom: 8px; flex-shrink: 0; max-height: 35vh; overflow: auto; }
summary { cursor: pointer; }.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 8px 0; }
input:not([type=file]):not([type=checkbox]) { flex: 1; min-width: 150px; } input[type=file] { max-width: 280px; }
input, select, button { background: var(--surface); color: inherit; border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px; }
.hint { color: var(--muted); } :disabled { opacity: .45; } [role=alert] { color: #f87171; } li { overflow-wrap: anywhere; }
</style>
