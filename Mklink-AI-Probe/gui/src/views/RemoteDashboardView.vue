<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { API_BASE } from '../lib/runtimeEndpoint'
import { tr } from '../composables/useLanguage'
const id = String(useRoute().params.windowId)
const base = `${API_BASE}/_runtime/remote-windows/${encodeURIComponent(id)}`
const session = ref<any>(null)
const online = ref(false)
const busy = ref(false)
const error = ref('')
const result = ref('')
const address = ref('0x20000000')
const size = ref(16)
const bytes = ref('')
const rttAddress = ref('')
const rttRunning = ref(false)
const rttText = ref('')
const rttInput = ref('')
const loss = ref('')
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
const supports = (name: string) => online.value && session.value?.capabilities.includes(name)
async function call(method: string, params: Record<string, unknown> = {}) {
  if (disposed || busy.value || !online.value) return
  busy.value = true
  error.value = ''
  try {
    const response = await fetch(`${base}/call`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ method, params }) })
    const value = await response.json()
    if (!response.ok) {
      if (([404, 410].includes(response.status) || response.status >= 500)) online.value = false
      throw new Error(String(value.detail))
    }
    if (disposed) return
    return value
  } catch (e: any) {
    if (!disposed) {
      error.value = e.message
      if (e instanceof TypeError) online.value = false
    }
    throw e
  } finally { busy.value = false }
}
async function action(method: string, params: Record<string, unknown> = {}) {
  try {
    const value = await call(method, params)
    if (value !== undefined) {
      const encoded = value.__bytes__
      result.value = method === 'memory.read' && encoded
        ? Array.from(atob(encoded), ch => ch.charCodeAt(0).toString(16).padStart(2, '0')).join(' ')
        : JSON.stringify(value, null, 2)
    }
  } catch { /* Visible error; never replay. */ }
}
function memoryAddress() {
  const value = Number(address.value)
  if (!Number.isSafeInteger(value) || value < 0 || value > 0xffffffff) throw new Error(tr('请输入有效的内存地址', 'Enter a valid memory address'))
  return value
}
async function readMemory() {
  try { await action('memory.read', { address: memoryAddress(), size: Number(size.value) }) }
  catch (e: any) { error.value = e.message }
}
async function writeMemory() {
  try {
    const hex = bytes.value.replace(/\s/g, '')
    if (!/^(?:[0-9a-fA-F]{2}){1,4096}$/.test(hex)) throw new Error(tr('请输入完整 HEX 字节，最多4096字节', 'Enter whole HEX bytes, up to 4096 bytes'))
    const target = memoryAddress()
    if (!window.confirm(tr('确认写入当前远端下载器的内存？', 'Write memory on the displayed remote probe?'))) return
    const data = hex.match(/../g)!.map(v => String.fromCharCode(parseInt(v, 16))).join('')
    await action('memory.write', { address: target, data_b64: btoa(data), confirm: true })
  } catch (e: any) { error.value = e.message }
}
async function startRtt() {
  try {
    const value = await call('rtt.start', rttAddress.value.trim() ? { addr: rttAddress.value.trim() } : {})
    if (value !== undefined) rttRunning.value = true
  } catch { /* Do not retry a failed start. */ }
}
async function stopRtt() {
  try {
    const value = await call('rtt.stop')
    if (value !== undefined) rttRunning.value = false
  } catch { rttRunning.value = false }
}
async function poll() {
  if (disposed || !online.value) return
  if (!busy.value) {
    try {
      const value = await call(rttRunning.value ? 'rtt.read' : 'probe.info', rttRunning.value ? { timeout: 0 } : {})
      if (value && rttRunning.value) {
        rttText.value = (rttText.value + (value.text || '')).slice(-65536)
        loss.value = JSON.stringify({ dropped_bytes: value.dropped_bytes, missing_batches: value.missing_batches, upstream: value.upstream })
        if (value.error || value.capture?.running === false) { rttRunning.value = false; error.value = value.error || tr('远端采集已停止', 'Remote capture stopped') }
      }
    } catch { rttRunning.value = false }
  }
  if (!disposed && online.value) timer = setTimeout(poll, 1000)
}
function close() {
  online.value = false
  rttRunning.value = false
  if (timer) clearTimeout(timer)
  void fetch(`${base}/close`, { method: 'POST', keepalive: true }).catch(() => {})
}
onMounted(async () => {
  window.addEventListener('pagehide', close)
  try {
    const response = await fetch(base)
    const value = await response.json()
    if (!response.ok) throw new Error(String(value.detail))
    if (disposed) return
    session.value = value
    online.value = value.connected
    await poll()
  } catch (e: any) { error.value = e.message }
})
onUnmounted(() => { disposed = true; window.removeEventListener('pagehide', close); close() })
</script>
<template>
  <main class="remote-dashboard" data-testid="remote-dashboard">
    <header class="card">
      <h2>{{ tr('远程仪表盘', 'Remote dashboard') }}</h2>
      <p>{{ session?.endpoint }} · {{ session?.identity.probe_id }}</p>
      <p>{{ tr('目标 ID', 'Target ID') }}: {{ session?.identity.idcode != null ? '0x' + Number(session.identity.idcode).toString(16) : '—' }} · {{ session?.identity.mcu_name }}</p>
      <strong>{{ online ? tr('远程会话已连接', 'Remote session connected') : tr('远程会话已断开，请从远程服务重新连接', 'Disconnected; reconnect from Remote Service') }}</strong>
      <p>{{ tr('此窗口只操作上述远端下载器，断线不会切换到本地或重放命令。', 'This window controls only the remote probe above. Connection loss never switches to local hardware or replays commands.') }}</p>
      <button class="btn" :disabled="!online" @click="close">{{ tr('断开远程会话', 'Disconnect remote session') }}</button>
    </header>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <section class="card">
      <h3>{{ tr('调试控制', 'Debug controls') }}</h3>
      <fieldset :disabled="busy || rttRunning || !supports('target.debug')">
        <button class="btn" @click="action('target.halt')">{{ tr('暂停 MCU', 'Halt MCU') }}</button>
        <button class="btn" @click="action('target.resume')">{{ tr('运行 MCU', 'Resume MCU') }}</button>
        <button class="btn" @click="action('target.step')">{{ tr('单步', 'Step') }}</button>
        <button class="btn" @click="action('registers.core')">{{ tr('读取寄存器（先暂停）', 'Read registers (halt first)') }}</button>
      </fieldset>
    </section>
    <section class="card">
      <h3>{{ tr('内存', 'Memory') }}</h3>
      <fieldset :disabled="busy || rttRunning || !supports('target.memory')">
        <label>{{ tr('地址', 'Address') }}<input v-model="address" data-testid="remote-memory-address" /></label>
        <label>{{ tr('字节数', 'Bytes') }}<input v-model.number="size" type="number" min="1" max="4096" /></label>
        <button class="btn" data-testid="remote-memory-read" @click="readMemory">{{ tr('读取内存', 'Read memory') }}</button>
        <label>HEX<input v-model="bytes" data-testid="remote-memory-bytes" placeholder="01 02 03 04" /></label>
        <button class="btn" data-testid="remote-memory-write" @click="writeMemory">{{ tr('写入并校验', 'Write and verify') }}</button>
      </fieldset>
      <pre>{{ result }}</pre>
    </section>
    <section class="card">
      <h3>RTT</h3>
      <fieldset :disabled="busy || !supports('stream.rtt')">
        <label>{{ tr('控制块地址（可选）', 'Control block address (optional)') }}<input v-model="rttAddress" :disabled="rttRunning" placeholder="0x20000000" /></label>
        <button class="btn" :disabled="rttRunning" @click="startRtt">{{ tr('开始 / 订阅', 'Start / Subscribe') }}</button>
        <button class="btn" :disabled="!rttRunning" @click="stopRtt">{{ tr('停止 / 退订', 'Stop / Unsubscribe') }}</button>
        <input v-model="rttInput" :placeholder="tr('发送文本', 'Send text')" />
        <button class="btn" :disabled="!rttRunning" @click="action('rtt.write', { data: rttInput })">{{ tr('发送', 'Send') }}</button>
      </fieldset>
      <pre data-testid="remote-rtt-output">{{ rttText }}</pre>
      <small>{{ tr('界面保留最近64K字符；丢失计数：', 'Last 64K characters retained; loss counters: ') }}{{ loss }}</small>
    </section>
    <p>{{ tr('本阶段未接入烧录、SuperWatch、VOFA 和文件上传。关闭窗口释放本远程会话；共享采集能否停止由远端所有权规则决定。', 'Flashing, SuperWatch, VOFA and file upload are not connected in this phase. Closing this window releases its remote session; remote ownership rules govern shared capture cleanup.') }}</p>
  </main>
</template>
<style scoped>
.remote-dashboard { padding: 20px; display: grid; gap: 16px; max-width: 1200px; margin: auto; }
.card { display: grid; gap: 10px; padding: 18px; }
fieldset { border: 0; display: flex; flex-wrap: wrap; align-items: end; gap: 10px; }
label { display: grid; gap: 4px; }
input { padding: 8px; color: var(--fg); background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); }
pre { max-height: 300px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--font-mono); }
p, small { overflow-wrap: anywhere; color: var(--muted); }
.error { color: var(--danger); }
</style>
