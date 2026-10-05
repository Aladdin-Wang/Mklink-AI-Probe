<template>
  <details class="serial-sequence" data-testid="serial-sequence">
    <summary>{{ tr('命令队列', 'Command sequence') }} · {{ port || '--' }} · {{ label(statuses[port]?.state || 'idle') }}</summary>
    <p class="hint">{{ tr('队列由后台执行。还有其他客户端时可继续；全部退出后后台自动关闭并取消剩余队列。停止串口或进入 YMODEM 也会取消对应队列。', 'The backend executes the sequence while clients remain. When all clients leave, automatic shutdown cancels the remaining queue. Closing serial or entering YMODEM also cancels it.') }}</p>
    <p class="hint">{{ tr('下方编辑本窗口的待发送草稿；各端口实际运行状态见表格。', 'Edit this window’s draft below; the table shows each port’s actual execution state.') }}</p>
    <div v-for="(command, index) in commands" :key="index" class="command-row">
      <span>{{ index + 1 }}</span>
      <select v-model="command.hex" :disabled="locked" :aria-label="tr(`命令 ${index + 1} 格式`, `Command ${index + 1} format`)"><option :value="false">UTF-8</option><option :value="true">HEX</option></select>
      <textarea v-model="command.data" data-testid="sequence-command" :disabled="locked" rows="1" maxlength="16384" :aria-label="tr(`命令 ${index + 1}`, `Command ${index + 1}`)" />
      <button type="button" :disabled="locked || commands.length === 1" @click="commands.splice(index, 1)">{{ tr('删除', 'Remove') }}</button>
    </div>
    <div class="actions">
      <button type="button" data-testid="sequence-add" :disabled="locked || commands.length >= 64" @click="commands.push({data: '', hex: false})">{{ tr('添加命令', 'Add command') }}</button>
      <label>{{ tr('间隔（ms）', 'Interval (ms)') }}<input v-model.number="interval" type="number" min="20" max="3600000" step="1" :disabled="locked" data-testid="sequence-interval"></label>
      <label>{{ tr('循环次数（0 为持续）', 'Cycles (0 continues)') }}<input v-model.number="repeat" type="number" min="0" max="1000000" step="1" :disabled="locked" data-testid="sequence-repeat"></label>
      <button type="button" data-testid="sequence-start" :disabled="locked || !running || !port" @click="start">{{ tr('开始队列', 'Start sequence') }} · {{ port || '--' }}</button>
    </div>
    <p v-if="localError || error" role="alert">{{ localError || error }}</p>
    <table v-if="Object.keys(statuses).length" data-testid="sequence-status">
      <thead><tr><th>{{ tr('端口', 'Port') }}</th><th>{{ tr('状态', 'State') }}</th><th>{{ tr('已发送命令数', 'Commands sent') }}</th><th>{{ tr('操作', 'Action') }}</th></tr></thead>
      <tbody><tr v-for="(status, name) in statuses" :key="name" :data-port="name">
        <td>{{ name }}</td><td>{{ label(status.state) }}<span v-if="status.error" class="error"> · {{ status.error }}</span></td><td>{{ status.sent || 0 }}</td>
        <td><button type="button" :disabled="busy || !status.active" @click="emit('stop', String(name))">{{ tr('停止队列', 'Stop sequence') }}</button></td>
      </tr></tbody>
    </table>
  </details>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { tr } from '../../composables/useLanguage'
export interface SerialSequenceStatus { state: string; active: boolean; sent?: number; error?: string }
export interface SerialSequenceRequest { port: string; commands: Array<{data: string; hex: boolean}>; interval_ms: number; repeat: number }
const props = defineProps<{ statuses: Record<string, SerialSequenceStatus>; port: string; running: boolean; busy: boolean; error: string }>()
const emit = defineEmits<{ start: [request: SerialSequenceRequest]; stop: [port: string] }>()
const commands = ref([{ data: '', hex: false }]), interval = ref(1000), repeat = ref(1), localError = ref('')
const locked = computed(() => props.busy || props.statuses[props.port]?.active === true)
function label(state: string) { return ({ idle: tr('未启动', 'Idle'), running: tr('执行中', 'Running'), completed: tr('已完成', 'Completed'), cancelled: tr('已取消', 'Cancelled'), failed: tr('失败', 'Failed') })[state] || state }
function start() {
  if (locked.value || !props.running || !props.port) return
  localError.value = ''
  if (!Number.isInteger(interval.value) || interval.value < 20 || interval.value > 3600000 || !Number.isInteger(repeat.value) || repeat.value < 0 || repeat.value > 1000000) {
    localError.value = tr('间隔须为 20..3600000 ms，循环须为 0..1000000 的整数。', 'Use an integer interval of 20..3600000 ms and cycles of 0..1000000.'); return
  }
  const request = { port: props.port, commands: commands.value.map(command => ({ ...command })), interval_ms: interval.value, repeat: repeat.value }
  if (commands.value.some(command => !command.data) || new TextEncoder().encode(JSON.stringify(request)).length > 16384) {
    localError.value = tr('命令不能为空，队列配置最多 16 KiB。', 'Commands cannot be empty; configuration is limited to 16 KiB.'); return
  }
  emit('start', request)
}
</script>

<style scoped>
.serial-sequence { border: 1px solid var(--border); border-radius: 5px; padding: 8px 10px; font-size: 12px; margin-bottom: 8px; max-height: 35vh; overflow: auto; flex-shrink: 0; }
summary { cursor: pointer; }.hint { color: var(--muted); }
.command-row, .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 8px 0; }
textarea { flex: 1 1 180px; resize: vertical; } input { width: 110px; }
input, select, button, textarea { background: var(--surface); color: inherit; border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px; }
:disabled { opacity: .45; } [role=alert], .error { color: #f87171; }
table { width: 100%; border-collapse: collapse; } th, td { text-align: left; border-bottom: 1px solid var(--border); padding: 4px; overflow-wrap: anywhere; }
</style>
