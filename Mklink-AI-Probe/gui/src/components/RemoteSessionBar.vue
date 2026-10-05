<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { API_BASE } from '../lib/runtimeEndpoint'
import { tr } from '../composables/useLanguage'
const endpoint = ref('')
const probe = ref('')
const connected = ref(false)
let timer: ReturnType<typeof setInterval> | undefined
async function refresh() {
  try {
    const response = await fetch(API_BASE)
    if (!response.ok) throw new Error('Unavailable')
    const value = await response.json()
    endpoint.value = value.endpoint
    probe.value = value.identity.probe_id
    connected.value = value.connected
  } catch { connected.value = false }
}
function close() {
  void fetch(`${API_BASE}/close`, { method: 'POST', keepalive: true }).catch(() => {})
}
function local() {
  const url = new URL(window.location.href)
  url.searchParams.delete('remote')
  url.hash = '/remote-service'
  window.location.assign(url.toString())
}
onMounted(() => { void refresh(); timer = setInterval(refresh, 3000); window.addEventListener('pagehide', close) })
onUnmounted(() => { clearInterval(timer); window.removeEventListener('pagehide', close); close() })
</script>
<template>
  <div class="remote-session-bar" data-testid="remote-session-bar">
    <strong>{{ tr('远程设备', 'Remote device') }}</strong>
    <span>{{ endpoint }} · {{ probe }}</span>
    <span>{{ connected ? tr('已连接', 'Connected') : tr('已断开，请重新连接；不会切换到本地', 'Disconnected; reconnect explicitly. No local fallback.') }}</span>
    <small>{{ tr('远端符号由目标电脑加载；烧录、串口/Modbus、文件和主机管理尚未开放。', 'Load symbols on the remote computer. Flashing, Serial/Modbus, files and host management are unavailable.') }}</small>
    <button class="btn" @click="local">{{ tr('返回本地 / 更换设备', 'Local / Change device') }}</button>
  </div>
</template>
<style scoped>
.remote-session-bar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 8px 20px; background: var(--surface); border-bottom: 2px solid var(--accent); }
span { overflow-wrap: anywhere; }
button { margin-left: auto; }
</style>
