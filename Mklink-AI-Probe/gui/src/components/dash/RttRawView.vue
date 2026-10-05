<template>
  <div class="rtt-raw-view">
    <small>{{ tr('接收丢失', 'Receive loss') }} {{ lost }} B · {{ tr('历史淘汰', 'History evicted') }} {{ evicted }} B · 64 KiB</small>
    <p v-if="error" role="alert">{{ error }}</p>
    <pre ref="outputElement" data-testid="rtt-channel-output">{{ output }}</pre>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { API_BASE } from '../../lib/runtimeEndpoint'
import { tr } from '../../composables/useLanguage'

const props = defineProps<{ channel: number, running: boolean, paused: boolean }>()
const bytes = ref<number[]>([])
const lost = ref(0)
const evicted = ref(0)
const error = ref('')
const outputElement = ref<HTMLElement | null>(null)
const output = computed(() => bytes.value.map((b, i) => b.toString(16).padStart(2, '0') + ((i + 1) % 16 ? ' ' : '\n')).join(''))
let cursor = 0
let session: string | undefined
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined
async function poll() {
  try {
    if (props.running && !props.paused) {
      const query = new URLSearchParams({ channel: String(props.channel), cursor: String(cursor) })
      if (session) query.set('session', session)
      controller = new AbortController()
      const response = await fetch(`${API_BASE}/api/dash/rtt/channels/read?${query}`, { signal: controller.signal })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'RTT read failed')
      if (!disposed) {
        if (data.reset) { bytes.value = []; lost.value = 0; evicted.value = 0 }
        cursor = data.cursor; session = data.session
        lost.value += data.lost_bytes
        const added: number[] = []
        for (let i = 0; i < data.data_hex.length; i += 2) added.push(parseInt(data.data_hex.slice(i, i + 2), 16))
        const element = outputElement.value
        const follow = !element || element.scrollHeight - element.scrollTop - element.clientHeight < 32
        const combined = [...bytes.value, ...added]
        evicted.value += Math.max(0, combined.length - 65536)
        bytes.value = combined.slice(-65536)
        error.value = ''
        if (follow) { await nextTick(); if (outputElement.value) outputElement.value.scrollTop = outputElement.value.scrollHeight }
      }
    }
  } catch (exc) { if (!disposed) error.value = String(exc) }
  if (!disposed) timer = setTimeout(poll, 200)
}
defineExpose({ clear: () => { bytes.value = []; lost.value = 0; evicted.value = 0 } })
onMounted(poll)
onUnmounted(() => { disposed = true; controller?.abort(); if (timer) clearTimeout(timer) })
</script>

<style scoped>
.rtt-raw-view { display: flex; flex: 1; flex-direction: column; min-height: 150px; overflow: hidden; }
pre { flex: 1; overflow: auto; white-space: pre-wrap; word-break: break-all; font: 12px monospace; }
small { color: var(--muted); }
</style>
