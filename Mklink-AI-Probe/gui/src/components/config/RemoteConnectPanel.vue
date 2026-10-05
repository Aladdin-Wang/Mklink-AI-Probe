<script setup lang="ts">
import { ref } from 'vue'
import { API_BASE } from '../../lib/runtimeEndpoint'
import { tr } from '../../composables/useLanguage'
const url = ref('ws://')
const token = ref('')
const busy = ref(false)
const error = ref('')
const windowId = ref('')
async function connect() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const response = await fetch(`${API_BASE}/_runtime/remote-windows`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url.value.trim(), token: token.value }),
    })
    const value = await response.json()
    if (!response.ok) throw new Error(String(value.detail))
    windowId.value = value.id
    token.value = ''
    try { await openWindow() }
    catch (e) {
      void fetch(`${API_BASE}/_runtime/remote-windows/${windowId.value}/close`, { method: 'POST' }).catch(() => {})
      windowId.value = ''
      throw e
    }
  } catch (e: any) { error.value = e.message }
  finally { busy.value = false }
}
async function openWindow() {
  const response = await fetch(`${API_BASE}/_runtime/remote-windows/${windowId.value}/open`, { method: 'POST' })
  if (!response.ok) throw new Error(tr('打开窗口失败，请重新连接。', 'Could not open the window; reconnect explicitly.'))
}
</script>
<template>
  <section class="remote-connect panel" data-testid="remote-connect-panel">
    <h3>{{ tr('连接远端下载器', 'Connect to a remote probe') }}</h3>
    <p>{{ tr('输入另一台电脑提供的服务地址和令牌，打开独立远程仪表盘。每个窗口固定绑定远端下载器，不改变本地仪表盘。', 'Enter the service address and token from the other computer. A separate dashboard stays bound to that remote probe; the local dashboard is unchanged.') }}</p>
    <form @submit.prevent="connect">
      <label>{{ tr('服务地址', 'Service address') }}<input v-model="url" data-testid="remote-connect-url" placeholder="ws://192.168.1.20:8766" required :disabled="busy" /></label>
      <label>{{ tr('访问令牌', 'Access token') }}<input v-model="token" data-testid="remote-connect-token" type="password" autocomplete="off" required :disabled="busy" /></label>
      <button class="btn btn-primary" :disabled="busy">{{ busy ? tr('正在连接…', 'Connecting…') : tr('连接并打开远程仪表盘', 'Connect and open remote dashboard') }}</button>
    </form>
    <p v-if="windowId" role="status">{{ tr('远程仪表盘已在独立窗口打开。新连接会创建独立会话。', 'Remote dashboard opened in a separate window. Each new connection creates its own session.') }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p>{{ tr('第一阶段支持内存、调试和 RTT。需要新版远程服务；令牌不保存在浏览器。', 'Phase one supports memory, debugging and RTT. An updated remote service is required. Tokens are not stored in the browser.') }}</p>
  </section>
</template>
<style scoped>
.remote-connect { display: grid; gap: 12px; }
form { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }
label { display: grid; gap: 6px; flex: 1; min-width: 220px; }
input { padding: 8px; background: var(--bg); color: var(--fg); border: 1px solid var(--border); border-radius: var(--radius); }
p { color: var(--muted); }
[role=alert] { color: var(--danger); }
</style>
