<template>
  <section class="channel-monitor">
    <label>{{ tr('查看通道', 'View channel') }}
      <select v-model.number="selected" data-testid="rtt-view-channel">
        <option v-for="ch in channels" :key="ch" :value="ch">RTT {{ ch }}</option>
      </select>
    </label>
    <label><input v-model="hex" type="checkbox">HEX</label>
    <span>{{ tr('本窗口独立读取', 'Independent client cursor') }} · {{ lost }} {{ tr('字节丢失', 'bytes lost') }}</span>
    <p v-if="error" role="alert">{{ error }}</p>
    <pre data-testid="rtt-channel-output">{{ output }}</pre>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { API_BASE } from '../../lib/runtimeEndpoint'
import { tr } from '../../composables/useLanguage'

const props = defineProps<{ channels: number[], running: boolean }>()
const selected = ref(props.channels[0] ?? 0)
const hex = ref(true)
const bytes = ref<number[]>([])
const lost = ref(0)
const error = ref('')
const output = computed(() => hex.value
  ? bytes.value.map((b, i) => b.toString(16).padStart(2, '0') + ((i + 1) % 16 ? ' ' : '\n')).join('')
  : new TextDecoder().decode(new Uint8Array(bytes.value)))
let cursor = 0
let session: string | undefined
let generation = 0
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
function reset() { generation++; cursor = 0; session = undefined; bytes.value = []; lost.value = 0; error.value = '' }
watch(selected, reset)
watch(() => props.channels, channels => {
  if (!channels.includes(selected.value)) selected.value = channels[0] ?? 0
})
async function poll() {
  const current = generation
  try {
    if (props.running && props.channels.includes(selected.value)) {
      const query = new URLSearchParams({ channel: String(selected.value), cursor: String(cursor) })
      if (session) query.set('session', session)
      const response = await fetch(`${API_BASE}/api/dash/rtt/channels/read?${query}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'RTT read failed')
      if (!disposed && current === generation) {
        if (data.reset) { bytes.value = []; lost.value = 0 }
        cursor = data.cursor; session = data.session
        lost.value += data.lost_bytes
        const added: number[] = []
        for (let i = 0; i < data.data_hex.length; i += 2) added.push(parseInt(data.data_hex.slice(i, i + 2), 16))
        bytes.value = [...bytes.value, ...added].slice(-8192)
        error.value = ''
      }
    }
  } catch (exc) { if (!disposed && current === generation) error.value = String(exc) }
  if (!disposed) timer = setTimeout(poll, 200)
}
onMounted(poll)
onUnmounted(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>

<style scoped>
.channel-monitor { padding: 8px; border: 1px solid var(--border-color, #444); border-radius: 6px; }
label, span { margin-right: 12px; }
pre { height: 150px; overflow: auto; white-space: pre-wrap; word-break: break-all; font-size: 12px; }
</style>
