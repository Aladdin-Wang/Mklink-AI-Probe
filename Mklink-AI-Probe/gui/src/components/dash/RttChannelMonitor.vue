<template>
  <section class="channel-monitor" :data-channel="channel">
    <header>
      <h3>RTT {{ channel }}</h3>
      <label><input v-model="hex" type="checkbox"> HEX</label>
      <button type="button" @click="collapsed = !collapsed">{{ collapsed ? tr('展开', 'Expand') : tr('收起', 'Collapse') }}</button>
      <button type="button" @click="clear">{{ tr('清空', 'Clear') }}</button>
    </header>
    <small>{{ tr('接收丢失', 'Receive loss') }} {{ lost }} B · {{ tr('历史淘汰', 'History evicted') }} {{ evicted }} B · {{ tr('保留最近 64 KiB', 'Retains latest 64 KiB') }}</small>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-show="!collapsed" class="channel-body">
      <pre ref="outputElement" data-testid="rtt-channel-output">{{ output }}</pre>
      <RttTransmitBar :enabled="sendEnabled" :settings="localSettings" :send="send"
        :id-prefix="`rtt-channel-${channel}`" @settings-change="localSettings = $event" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { API_BASE } from '../../lib/runtimeEndpoint'
import { tr } from '../../composables/useLanguage'
import type { DesktopSettings } from '../../lib/desktopSettings'
import RttTransmitBar from './RttTransmitBar.vue'

const props = defineProps<{
  channel: number, running: boolean, paused: boolean, sendEnabled: boolean,
  settings: DesktopSettings, send: (payload: Uint8Array) => Promise<void>
}>()
const localSettings = ref({ ...props.settings, sendHistory: [...props.settings.sendHistory] })
const hex = ref(true)
const collapsed = ref(false)
const bytes = ref<number[]>([])
const lost = ref(0)
const evicted = ref(0)
const error = ref('')
const outputElement = ref<HTMLElement | null>(null)
const output = computed(() => hex.value
  ? bytes.value.map((b, i) => b.toString(16).padStart(2, '0') + ((i + 1) % 16 ? ' ' : '\n')).join('')
  : new TextDecoder().decode(new Uint8Array(bytes.value)))
let cursor = 0
let session: string | undefined
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined
function clear() { bytes.value = []; evicted.value = 0 }
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
onMounted(poll)
onUnmounted(() => { disposed = true; controller?.abort(); if (timer) clearTimeout(timer) })
</script>

<style scoped>
.channel-monitor { display: flex; flex-direction: column; min-width: 0; height: 520px; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius); }
header { display: flex; align-items: center; gap: 12px; }
h3 { font-size: 14px; margin: 0; flex: 1; }
small { color: var(--text-secondary); margin: 8px 0; }
.channel-body { display: flex; flex: 1; flex-direction: column; min-height: 0; }
pre { flex: 1; min-height: 150px; overflow: auto; white-space: pre-wrap; word-break: break-all; font-size: 12px; font-family: monospace; background: var(--bg-primary); padding: 8px; }
button { color: var(--text-primary); background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 4px; cursor: pointer; }
</style>
