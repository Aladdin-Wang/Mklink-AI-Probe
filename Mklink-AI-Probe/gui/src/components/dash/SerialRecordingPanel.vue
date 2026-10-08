<template>
  <details class="serial-recording" data-testid="serial-recording">
    <summary>{{ tr('持续保存文件', 'Continuous file recording') }} · {{ stateLabel }}</summary>
    <p>{{ tr('文件保存在后台所在电脑。关闭页面或断开 AI 不会停止记录；关闭串口会排空并结束记录。', 'Files are saved on the backend computer. Closing the page or disconnecting AI keeps recording; closing serial drains and ends it.') }}</p>
    <div class="recording-fields">
      <label>{{ tr('新文件路径', 'New file path') }}<input v-model="path" data-testid="recording-path" :disabled="locked" maxlength="4096" :placeholder="tr('输入后台电脑的完整路径', 'Enter a full path on the backend computer')"></label>
      <label>{{ tr('格式', 'Format') }}<select v-model="format" :disabled="locked"><option value="txt">TXT</option><option value="csv">CSV</option></select></label>
      <label>{{ tr('端口', 'Ports') }}<select v-model="scope" :disabled="locked"><option value="all">{{ tr('全部已配置端口', 'All configured ports') }}</option><option value="current">{{ tr('当前端口', 'Current port') }} · {{ port }}</option></select></label>
      <label>{{ tr('轮转大小（MiB，0 不轮转）', 'Rotate at (MiB, 0 disables)') }}<input v-model.number="size" type="number" min="0" max="1048576" step="1" :disabled="locked" data-testid="recording-size"></label>
      <button type="button" data-testid="recording-start" :disabled="locked || !running || !path.trim() || !validSize || (scope === 'current' && !port)" @click="start">{{ tr('开始记录', 'Start recording') }}</button>
      <button type="button" data-testid="recording-stop" :disabled="busy || !status.active" @click="emit('stop')">{{ tr('停止并保存', 'Stop and save') }}</button>
    </div>
    <p v-if="status.path" data-testid="recording-result">{{ status.path }} · {{ status.format?.toUpperCase() }} · {{ status.ports?.join(', ') }}</p>
    <p v-if="error || status.error" role="alert">{{ error || status.error }}</p>
    <p class="hint">{{ tr('已有文件不会被覆盖。磁盘过慢或历史溢出会标记记录不完整；不包含 YMODEM 传输。', 'Existing files are never overwritten. Slow disks or history overflow can make recording incomplete. YMODEM traffic is excluded.') }}</p>
  </details>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { tr } from '../../composables/useLanguage'
export interface SerialRecordingStatus {
  state: string; active: boolean; path?: string; format?: string; ports?: string[]; error?: string; session?: string
}
export interface SerialRecordingRequest { path: string; format: string; max_size: number; ports?: string[] }
const props = defineProps<{ status: SerialRecordingStatus; running: boolean; port: string; busy: boolean; error: string }>()
const emit = defineEmits<{ start: [request: SerialRecordingRequest]; stop: [] }>()
const path = ref(''), format = ref('txt'), scope = ref('all'), size = ref(0)
const locked = computed(() => props.busy || props.status.active)
const validSize = computed(() => Number.isInteger(size.value) && size.value >= 0 && size.value <= 1048576)
const stateLabel = computed(() => ({ idle: tr('未记录', 'Idle'), starting: tr('正在打开文件', 'Opening file'), running: tr('记录中', 'Recording'), stopping: tr('正在排空', 'Draining'), completed: tr('已保存', 'Saved'), failed: tr('记录失败', 'Failed') }[props.status.state] || props.status.state))
function start() {
  if (locked.value || !props.running || !path.value.trim() || !validSize.value || (scope.value === 'current' && !props.port)) return
  emit('start', { path: path.value.trim(), format: format.value, max_size: size.value * 1048576, ...(scope.value === 'current' ? { ports: [props.port] } : {}) })
}
</script>

<style scoped>
.serial-recording { border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
summary { cursor: pointer; }
p { margin: 8px 0; overflow-wrap: anywhere; font-size: 12px; }
.recording-fields { display: flex; flex-wrap: wrap; align-items: end; gap: 8px; }
label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
label:first-child { flex: 1 1 300px; }
input, select, button { min-height: 30px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: inherit; padding: 4px 8px; }
input[type=number] { width: 160px; }
:disabled { opacity: .5; }
[role=alert] { color: var(--danger, #ff8080); }
.hint { color: var(--muted); }
</style>
