<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { API_BASE } from '../../lib/runtimeEndpoint'
import { tr } from '../../composables/useLanguage'
import { useMklinkApi } from '../../composables/useMklinkApi'

interface Client { id: string; name: string; kind: string; streams: string[]; expires_in: number }
interface Runtime {
  jobs?: { job_id: string; request_id: string; action: string; state: string; error: string | null }[]
  probe_id: string; status: string; connected: boolean; busy: boolean; project_root: string
  probe: { alias: string; port: string } | null
  clients: Client[]; streams: { name: string; running: boolean; subscribers: number }[]
  operation: { path: string; client: string } | null
  last_operation: { path: string; http_status: number | null; duration_seconds: number } | null
}
const { refreshStatus: refreshDeviceStatus } = useMklinkApi()
const state = ref<Runtime | null>(null)
const error = ref('')
const acting = ref(false)
const stopped = ref(false)
const volume = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let disposed = false
let refreshing = false

function presenceLabel(status: string) {
  return ({ present: tr('设备在线', 'Present'), missing: tr('设备未连接', 'Missing'),
    port_changed: tr('端口已变化', 'Port changed'), unselected: tr('未选择设备', 'No probe selected') } as Record<string, string>)[status] || status
}

function jobLabel(state: string) {
  return ({ running: tr('执行中', 'Running'), succeeded: tr('成功', 'Succeeded'),
    failed: tr('失败', 'Failed'), unknown: tr('结果未知，请核对目标状态', 'Unknown: inspect target state') } as Record<string, string>)[state] || state
}

async function checkVolume() {
  acting.value = true
  volume.value = ''
  error.value = ''
  try {
    const response = await fetch(`${API_BASE}/api/runtime/control/volume`)
    const result = await response.json()
    if (!response.ok) throw new Error(String(result.detail))
    volume.value = `${result.drive} · ${tr('已核对 USB 身份', 'USB identity verified')}`
  } catch (e: any) { error.value = e.message }
  finally { acting.value = false }
}

async function refresh() {
  if (refreshing || stopped.value) return
  refreshing = true
  try {
    const response = await fetch(`${API_BASE}/api/runtime/control/status`)
    if (!response.ok) throw new Error(tr('读取后台状态失败', 'Could not read runtime status'))
    const value = await response.json()
    if (!disposed) state.value = value
  } catch (e: any) { if (!disposed) error.value = e.message }
  finally { refreshing = false }
}

async function act(action: string, parameters: Record<string, string> = {}) {
  const prompts: Record<string, string> = {
    'detach-client': tr('结束此 AI/CLI/SDK 会话？采集和设备连接将保留。', 'End this AI/CLI/SDK session? Acquisition and device connection will remain.'),
    'stop-acquisition': tr('停止选定采集？有其他订阅者时会拒绝。', 'Stop this capture? Other subscribers will prevent it.'),
    'release-device': tr('释放此下载器的物理连接？其他设备不受影响。', 'Release this probe connection? Other devices are unaffected.'),
    'stop-backend': tr('退出此下载器后台？本窗口随后将离线。', 'Exit this probe backend? This window will go offline.'),
  }
  if (!window.confirm(prompts[action])) return
  acting.value = true
  error.value = ''
  try {
    const response = await fetch(`${API_BASE}/api/runtime/control/${action}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...parameters, confirm: true }),
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail))
    if (action === 'stop-backend') stopped.value = true
    else {
      if (action === 'release-device') await refreshDeviceStatus()
      await refresh()
    }
  } catch (e: any) { error.value = e.message }
  finally { acting.value = false }
}

onMounted(() => { void refresh(); timer = setInterval(refresh, 2000) })
onUnmounted(() => { disposed = true; if (timer) clearInterval(timer) })
</script>

<template>
  <section class="card runtime-panel" data-testid="runtime-panel">
    <header class="runtime-heading">
      <div><h2>{{ tr('共享后台', 'Shared backend') }}</h2><p>{{ tr('同一下载器共享连接，不同下载器独立运行。', 'Clients share one probe connection; different probes run independently.') }}</p></div>
      <button class="btn btn-sm" @click="refresh">{{ tr('刷新', 'Refresh') }}</button>
    </header>
    <p v-if="error" role="alert" class="runtime-error">{{ error }}</p>
    <p v-if="stopped" role="status">{{ tr('后台已退出。重新打开设备窗口可再次启动。', 'Backend exited. Open a device window to start it again.') }}</p>
    <template v-else-if="state">
      <dl class="runtime-details">
        <dt>{{ tr('下载器', 'Probe') }}</dt><dd>{{ state.probe?.alias || state.probe_id }} <span v-if="state.probe">· {{ state.probe.port }}</span></dd>
        <dt>{{ tr('连接状态', 'Connection') }}</dt><dd data-testid="runtime-presence">{{ presenceLabel(state.status) }} · {{ state.connected ? tr('已连接', 'Connected') : tr('已释放', 'Released') }}</dd>
        <dt>{{ tr('工程', 'Project') }}</dt><dd>{{ state.project_root }}</dd>
        <dt>{{ tr('当前操作', 'Current operation') }}</dt><dd data-testid="runtime-operation">{{ state.operation ? `${state.operation.client} · ${state.operation.path}` : tr('空闲', 'Idle') }}</dd>
      </dl>
      <p v-if="state.status !== 'present'" class="runtime-error">{{ tr('原设备未就绪。请结束旧会话、停止采集并释放连接，然后按原设备身份重新连接。不会自动选择其他下载器。', 'Bound probe is not ready. End old sessions, stop capture, release the connection, then reconnect the same identity.') }}</p>
      <h3>{{ tr('客户端', 'Clients') }} · {{ state.clients.length }}</h3>
      <p v-if="!state.clients.length">{{ tr('暂无客户端', 'No clients') }}</p>
      <div v-for="client in state.clients" :key="client.id" class="runtime-row" data-testid="runtime-client">
        <div><strong>{{ client.name }}</strong> <span class="runtime-muted">{{ client.kind }} · {{ client.id.slice(0, 8) }}</span><p>{{ client.streams.join(', ') || tr('无采集订阅', 'No capture subscriptions') }}</p></div>
        <button v-if="client.kind !== 'gui'" class="btn btn-sm" :disabled="acting || state.busy" @click="act('detach-client', { client_id: client.id })">{{ tr('结束会话', 'End session') }}</button>
        <span v-else class="runtime-muted">{{ tr('关闭窗口即可退出', 'Close window to leave') }}</span>
      </div>
      <h3>{{ tr('运行中的采集', 'Active captures') }}</h3>
      <p v-if="!state.streams.some(s => s.running)">{{ tr('暂无采集', 'No active capture') }}</p>
      <div v-for="stream in state.streams.filter(s => s.running)" :key="stream.name" class="runtime-row">
        <span>{{ stream.name }} · {{ stream.subscribers }} {{ tr('个 AI/CLI/SDK 订阅', 'AI/CLI/SDK subscribers') }}</span>
        <button v-if="['rtt', 'superwatch', 'systemview'].includes(stream.name)" class="btn btn-sm" :disabled="acting || state.busy || stream.subscribers > 0" @click="act('stop-acquisition', { stream: stream.name })">{{ tr('停止采集', 'Stop capture') }}</button>
      </div>
      <div class="runtime-actions">
        <button class="btn" :disabled="acting" @click="checkVolume">{{ tr('核对下载器磁盘', 'Check probe volume') }}</button><span>{{ volume }}</span>
        <button class="btn" :disabled="acting || state.busy" data-testid="runtime-release" @click="act('release-device')">{{ tr('释放下载器', 'Release probe') }}</button>
        <button class="btn" :disabled="acting || state.busy" @click="act('stop-backend')">{{ tr('退出后台', 'Exit backend') }}</button>
      </div>
      <template v-if="state.jobs?.length">
        <h3>{{ tr('最近独占任务', 'Recent exclusive jobs') }}</h3>
        <div v-for="job in state.jobs.slice(0, 8)" :key="job.job_id" class="runtime-row" data-testid="runtime-job">
          <div><strong>{{ job.action }} · {{ jobLabel(job.state) }}</strong><p>{{ job.job_id }}</p><p v-if="job.error">{{ job.error }}</p></div>
        </div>
        <p class="runtime-muted">{{ tr('关闭客户端不会取消任务。结果未知时请先核对目标，不要重新提交。后台最多保留 64 个任务。', 'Closing a client does not cancel its job. Inspect the target before submitting again after an unknown result. Up to 64 jobs are retained.') }}</p>
      </template>
      <p class="runtime-muted">{{ tr('结束会话不会停止采集。释放设备前，请先结束 AI/CLI/SDK 会话并停止采集。GUI 窗口意外退出后，最多 45 秒从列表移除。', 'Ending a session keeps capture running. End AI/CLI/SDK sessions and stop capture before releasing the probe. Lost GUI windows expire after 45 seconds.') }}</p>
    </template>
  </section>
</template>

<style scoped>
.runtime-panel { display: flex; flex-direction: column; gap: 16px; }
.runtime-heading, .runtime-row, .runtime-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.runtime-heading h2, h3, p { margin: 0; }
.runtime-heading p, .runtime-row p { margin-top: 6px; }
.runtime-muted, .runtime-heading p { color: var(--muted); font-size: 12px; }
.runtime-details { display: grid; grid-template-columns: 100px 1fr; gap: 10px; margin: 0; }
.runtime-details dt { color: var(--muted); }
.runtime-details dd { margin: 0; overflow-wrap: anywhere; }
.runtime-row { border: 1px solid var(--border); border-radius: var(--radius); padding: 12px; }
.runtime-actions { justify-content: flex-start; }
.runtime-error { color: var(--accent); overflow-wrap: anywhere; }
</style>
