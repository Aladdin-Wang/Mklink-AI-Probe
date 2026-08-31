<template>
  <div class="modbus-workbench">
    <SetupHint v-if="portsLoaded && !ports.length" kind="info"
      :message="tr('未检测到可用串口。Modbus 不依赖 MKLink 设备连接。', 'No serial ports detected. Modbus does not depend on the MKLink device connection.')"
      :primary-label="tr('刷新串口', 'Refresh Ports')" :busy="refreshingPorts" @primary="refreshPorts" />

    <section class="workbench-card">
      <div class="section-heading"><div><strong>{{ tr('连接', 'Connection') }}</strong><span class="section-note">Modbus RTU · CRC {{ tr('自动计算', 'automatic') }}</span></div><span class="state-pill" :class="{ online: running }">{{ running ? tr('已连接', 'Connected') : tr('未连接', 'Disconnected') }}</span></div>
      <div class="config-grid">
        <label><span>{{ tr('串口', 'Port') }}</span><select v-model="settings.port" class="form-input"><option v-for="p in ports" :key="p.device" :value="p.device">{{ p.device }} {{ p.description ? `· ${p.description}` : '' }}</option></select></label>
        <label><span>{{ tr('从站', 'Slave') }}</span><input v-model.number="settings.slave" type="number" class="form-input" min="1" max="247" /></label>
        <label><span>{{ tr('波特率', 'Baud') }}</span><input v-model.number="settings.baudrate" type="number" class="form-input" min="300" max="4000000" /></label>
        <label><span>{{ tr('数据位', 'Data bits') }}</span><select v-model.number="settings.bytesize" class="form-input"><option :value="8">8</option><option :value="7">7</option></select></label>
        <label><span>{{ tr('校验', 'Parity') }}</span><select v-model="settings.parity" class="form-input"><option value="N">None</option><option value="E">Even</option><option value="O">Odd</option></select></label>
        <label><span>{{ tr('停止位', 'Stop bits') }}</span><select v-model.number="settings.stopbits" class="form-input"><option :value="1">1</option><option :value="2">2</option></select></label>
        <label><span>{{ tr('超时(s)', 'Timeout (s)') }}</span><input v-model.number="settings.timeout" type="number" class="form-input" min="0.05" max="10" step="0.05" /></label>
        <label><span>{{ tr('重试', 'Retries') }}</span><input v-model.number="settings.retries" type="number" class="form-input" min="0" max="5" /></label>
        <label class="check-field"><input v-model="settings.localEcho" type="checkbox" />{{ tr('适配器本地回显', 'Adapter local echo') }}</label>
        <button v-if="!running" class="btn btn-primary connection-action" :disabled="!settings.port || connecting" @click="connect">{{ connecting ? tr('连接中…', 'Connecting…') : tr('连接', 'Connect') }}</button>
        <button v-else class="btn btn-danger connection-action" @click="disconnect">{{ tr('断开', 'Disconnect') }}</button>
      </div>
    </section>

    <div class="workbench-columns">
      <section class="workbench-card">
        <div class="section-heading"><strong>{{ tr('请求编辑器', 'Request Builder') }}</strong><span class="section-note">{{ tr('标准功能码', 'Standard function codes') }}</span></div>
        <div class="request-grid">
          <label class="wide"><span>{{ tr('功能码', 'Function') }}</span><select v-model.number="settings.fc" class="form-input"><option v-for="item in FUNCTION_OPTIONS" :key="item.fc" :value="item.fc">FC{{ String(item.fc).padStart(2, '0') }} · {{ tr(item.zh, item.en) }}</option></select></label>
          <label><span>{{ tr('起始地址', 'Start address') }}</span><input v-model="settings.start" class="form-input mono" placeholder="0 / 0x0000" /></label>
          <label v-if="isRead"><span>{{ tr('数量', 'Quantity') }}</span><input v-model.number="settings.quantity" type="number" class="form-input" min="1" :max="maxQuantity" /></label>
          <label v-else class="wide"><span>{{ tr('写入值', 'Write values') }}</span><textarea v-model="settings.values" class="form-input mono value-input" :placeholder="isBit ? '0, 1, ON, OFF' : '1, 2, 0x1234'" /></label>
        </div>
        <div class="request-actions">
          <button class="btn btn-primary" :disabled="!running || sending" @click="sendOnce">{{ sending ? tr('发送中…', 'Sending…') : tr('发送一次', 'Send Once') }}</button>
          <div class="loop-controls">
            <label><span>{{ tr('间隔(ms)', 'Interval (ms)') }}</span><input v-model.number="settings.loopIntervalMs" type="number" class="form-input" min="20" /></label>
            <label><span>{{ tr('次数 (0=连续)', 'Count (0=continuous)') }}</span><input v-model.number="settings.loopCount" type="number" class="form-input" min="0" max="100000" /></label>
            <button v-if="!loopRunning" class="btn" :disabled="!running" @click="startLoop">{{ tr('循环发送', 'Start Loop') }}</button>
            <button v-else class="btn btn-danger" @click="stopLoop">{{ tr('停止循环', 'Stop Loop') }}</button>
          </div>
        </div>
        <div v-if="loopStatus.completed || loopRunning" class="loop-summary">{{ tr('已执行', 'Completed') }} {{ loopStatus.completed || 0 }} · {{ tr('错误', 'Errors') }} {{ loopStatus.errors || 0 }}</div>
      </section>

      <section class="workbench-card">
        <div class="section-heading"><strong>{{ tr('响应解析', 'Response') }}</strong><span v-if="lastResult" class="section-note">{{ lastResult.duration_ms }} ms</span></div>
        <div v-if="lastResult" class="result-meta mono">ID {{ lastResult.id }} · FC{{ String(lastResult.fc).padStart(2, '0') }} · {{ tr('地址', 'address') }} {{ formatAddress(lastResult.start) }}</div>
        <div v-if="lastResult?.values?.length" class="result-table-wrap"><table class="result-table"><thead><tr><th>{{ tr('地址', 'Address') }}</th><th>HEX</th><th>DEC</th><th>{{ isResultBit ? tr('状态', 'State') : 'INT16' }}</th></tr></thead><tbody><tr v-for="(value, index) in lastResult.values" :key="index"><td>{{ formatAddress(lastResult.start + index) }}</td><td class="mono">{{ formatHex(value) }}</td><td>{{ formatDecimal(value) }}</td><td>{{ formatSigned(value) }}</td></tr></tbody></table></div>
        <div v-else class="empty-state">{{ tr('发送请求后在这里查看返回值。', 'Send a request to inspect returned values.') }}</div>
      </section>
    </div>

    <section class="workbench-card">
      <div class="section-heading"><div><strong>{{ tr('RTU 帧日志', 'RTU Frame Log') }}</strong><span class="section-note">{{ tr('实际串口收发帧', 'Actual serial traffic') }}</span></div><div class="log-actions"><button class="btn btn-sm" @click="logPaused = !logPaused">{{ logPaused ? tr('继续', 'Resume') : tr('暂停', 'Pause') }}</button><button class="btn btn-sm" @click="logs = []">{{ tr('清空', 'Clear') }}</button><button class="btn btn-sm" :disabled="!logs.length" @click="exportLogs">{{ tr('导出', 'Export') }}</button></div></div>
      <div ref="logPanel" class="frame-log"><div v-for="(entry, index) in logs" :key="`${entry.timestamp}-${index}`" class="frame-row" :class="entry.direction"><span class="frame-time">{{ formatTime(entry.timestamp) }}</span><span class="frame-direction">{{ (entry.direction || entry.event).toUpperCase() }}</span><span class="frame-body mono">{{ entry.hex || entry.message || summarizeEvent(entry) }}</span><span v-if="entry.crc_ok !== undefined && entry.crc_ok !== null" class="crc" :class="entry.crc_ok ? 'ok' : 'bad'">CRC {{ entry.crc_ok ? 'OK' : 'ERR' }}</span></div><div v-if="!logs.length" class="empty-state">{{ tr('连接后发送请求，TX/RX 原始帧会显示在这里。', 'Connect and send a request to view raw TX/RX frames.') }}</div></div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useMklinkApi } from '../../composables/useMklinkApi'
import { useToast } from '../../composables/useToast'
import type { PortInfo } from '../../types/mklink'
import { tr } from '../../composables/useLanguage'
import SetupHint from './SetupHint.vue'
import { API_BASE } from '../../lib/runtimeEndpoint'
import { BIT_FUNCTIONS, buildTransaction, DEFAULT_MODBUS_SETTINGS, FUNCTION_OPTIONS, loadModbusSettings, MODBUS_SETTINGS_KEY, READ_FUNCTIONS } from '../../lib/modbusWorkbench'

interface TransactionResult { id: number; fc: number; start: number; values: Array<number | boolean>; duration_ms: number }
interface LogEntry { event: string; timestamp: number; direction?: string; hex?: string; crc_ok?: boolean | null; message?: string; [key: string]: unknown }

const toast = useToast()
const { listPorts: fetchPorts } = useMklinkApi()
const stored = loadModbusSettings(typeof localStorage === 'undefined' ? null : localStorage)
const settings = reactive({ ...DEFAULT_MODBUS_SETTINGS, ...stored })
const ports = ref<PortInfo[]>([])
const portsLoaded = ref(false), refreshingPorts = ref(false), connecting = ref(false), sending = ref(false)
const running = ref(false), loopRunning = ref(false), logPaused = ref(false)
const loopStatus = ref<Record<string, number>>({ completed: 0, errors: 0 })
const lastResult = ref<TransactionResult | null>(null)
const logs = ref<LogEntry[]>([])
const logPanel = ref<HTMLElement | null>(null)
let es: EventSource | null = null

const isRead = computed(() => READ_FUNCTIONS.has(Number(settings.fc)))
const isBit = computed(() => BIT_FUNCTIONS.has(Number(settings.fc)))
const isResultBit = computed(() => lastResult.value ? BIT_FUNCTIONS.has(Number(lastResult.value.fc)) : false)
const maxQuantity = computed(() => [1, 2].includes(Number(settings.fc)) ? 2000 : 125)

watch(settings, value => { if (typeof localStorage !== 'undefined') localStorage.setItem(MODBUS_SETTINGS_KEY, JSON.stringify(value)) }, { deep: true })

async function api(path: string, body?: unknown) {
  const response = await fetch(`${API_BASE}${path}`, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const payload = await response.json().catch(() => null)
  if (!response.ok) { const detail = payload?.detail; throw new Error(typeof detail === 'string' ? detail : detail?.conflict || response.statusText) }
  return payload
}
async function refreshPorts() { refreshingPorts.value = true; try { ports.value = await fetchPorts(); if (!ports.value.some(item => item.device === settings.port)) settings.port = ports.value[0]?.device || '' } catch (error) { toast.error(String(error)) } finally { refreshingPorts.value = false; portsLoaded.value = true } }
async function restoreStatus() { try { const status = await api('/api/dash/modbus/status'); running.value = Boolean(status.running); loopRunning.value = Boolean(status.loop?.running); loopStatus.value = running.value ? (status.loop || loopStatus.value) : { completed: 0, errors: 0 }; if (running.value) connectSSE() } catch { /* backend may still be starting */ } }
async function connect() { connecting.value = true; try { await api('/api/dash/modbus/start', { port: settings.port, slave: settings.slave, baudrate: settings.baudrate, bytesize: settings.bytesize, parity: settings.parity, stopbits: settings.stopbits, timeout: settings.timeout, retries: settings.retries, local_echo: settings.localEcho, registers: [], interval: Math.max(0.02, settings.loopIntervalMs / 1000) }); running.value = true; connectSSE(); toast.success(tr('Modbus 已连接', 'Modbus connected')) } catch (error) { toast.error(tr('连接失败: ', 'Connection failed: ') + String(error)) } finally { connecting.value = false } }
async function disconnect() { stopEventSource(); try { await api('/api/dash/modbus/stop', {}) } catch { /* already stopped */ } running.value = false; loopRunning.value = false; loopStatus.value = { completed: 0, errors: 0 }; toast.info(tr('Modbus 已断开', 'Modbus disconnected')) }
function requestPayload() { return buildTransaction(settings) }
async function sendOnce() { sending.value = true; try { lastResult.value = await api('/api/dash/modbus/transaction', requestPayload()) } catch (error) { toast.error(tr('请求失败: ', 'Request failed: ') + String(error)) } finally { sending.value = false } }
async function startLoop() { try { loopStatus.value = await api('/api/dash/modbus/loop/start', { ...requestPayload(), interval: settings.loopIntervalMs / 1000, count: settings.loopCount }); loopRunning.value = true } catch (error) { toast.error(tr('循环启动失败: ', 'Loop start failed: ') + String(error)) } }
async function stopLoop() { try { loopStatus.value = await api('/api/dash/modbus/loop/stop', {}) } catch { /* session stopped */ } loopRunning.value = false }
function connectSSE() { stopEventSource(); es = new EventSource(`${API_BASE}/api/dash/modbus/stream`); es.onmessage = event => { try { const value = JSON.parse(event.data); if (value.event === 'transaction') lastResult.value = value; if (value.event === 'loop') { loopRunning.value = Boolean(value.running); loopStatus.value = value }; if (value.event === 'stopped') { running.value = false; loopRunning.value = false }; if (value.event === 'error') toast.error(value.message); if (value.event === 'history') { if (!logPaused.value) logs.value = [...logs.value, ...(value.points || []).filter((item: LogEntry) => ['frame', 'error'].includes(item.event))].slice(-500) } else if (!logPaused.value && ['frame', 'error'].includes(value.event)) logs.value = [...logs.value, value].slice(-500); nextTick(() => { if (logPanel.value) logPanel.value.scrollTop = logPanel.value.scrollHeight }) } catch { /* malformed event */ } } }
function stopEventSource() { if (es) { es.close(); es = null } }
function formatAddress(value: number) { return `${value} / 0x${value.toString(16).toUpperCase().padStart(4, '0')}` }
function formatHex(value: number | boolean) { const n = typeof value === 'boolean' ? Number(value) : value; return `0x${n.toString(16).toUpperCase().padStart(4, '0')}` }
function formatDecimal(value: number | boolean) { return typeof value === 'boolean' ? (value ? '1' : '0') : String(value) }
function formatSigned(value: number | boolean) { if (typeof value === 'boolean') return value ? 'ON' : 'OFF'; return String(value >= 0x8000 ? value - 0x10000 : value) }
function formatTime(timestamp: number) { const date = new Date(timestamp * 1000); return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}.${String(date.getMilliseconds()).padStart(3, '0')}` }
function summarizeEvent(entry: LogEntry) { return entry.event === 'error' ? entry.message || '' : JSON.stringify(entry) }
function exportLogs() { const content = logs.value.map(entry => `${formatTime(entry.timestamp)} ${(entry.direction || entry.event).toUpperCase()} ${entry.hex || entry.message || summarizeEvent(entry)}`).join('\n'); const url = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = `mklink-modbus-${Date.now()}.log`; link.click(); URL.revokeObjectURL(url) }
onMounted(async () => { await refreshPorts(); await restoreStatus() })
onUnmounted(stopEventSource)
</script>

<style scoped>
.modbus-workbench{display:grid;gap:12px}.workbench-card{border:1px solid var(--border);border-radius:var(--radius);background:var(--surface);padding:12px;min-width:0}.section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}.section-heading>div{display:flex;align-items:center;gap:10px}.section-note{color:var(--muted);font-size:12px;font-weight:400}.state-pill{color:var(--muted);border:1px solid var(--border);border-radius:999px;padding:2px 9px;font-size:12px}.state-pill.online{color:var(--success);border-color:color-mix(in srgb,var(--success) 45%,transparent);background:color-mix(in srgb,var(--success) 9%,transparent)}.config-grid{display:grid;grid-template-columns:minmax(170px,1.5fr) repeat(7,minmax(76px,.7fr)) auto;gap:8px;align-items:end}label{display:grid;gap:4px;color:var(--muted);font-size:12px}.check-field{display:flex;align-items:center;white-space:nowrap;height:34px}.connection-action{height:34px;white-space:nowrap}.workbench-columns{display:grid;grid-template-columns:minmax(380px,.95fr) minmax(380px,1.05fr);gap:12px}.request-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.wide{grid-column:1/-1}.mono{font-family:var(--font-mono)}.value-input{min-height:64px;resize:vertical}.request-actions{display:flex;align-items:end;justify-content:space-between;gap:12px;margin-top:10px;flex-wrap:wrap}.loop-controls{display:flex;align-items:end;gap:8px;flex-wrap:wrap}.loop-controls label{width:118px}.loop-summary,.result-meta{color:var(--muted);font-size:12px;margin-top:8px}.result-table-wrap{overflow:auto;max-height:300px;margin-top:8px}.result-table{border-collapse:collapse;width:100%;font-size:12px}.result-table th,.result-table td{border-bottom:1px solid var(--border-subtle);text-align:left;padding:6px 8px}.result-table th{position:sticky;top:0;background:var(--surface);color:var(--muted)}.empty-state{color:var(--muted);font-size:13px;padding:22px 8px;text-align:center}.log-actions{display:flex;gap:6px}.frame-log{min-height:150px;max-height:270px;overflow:auto;background:var(--bg);border:1px solid var(--border-subtle);border-radius:4px}.frame-row{display:grid;grid-template-columns:92px 36px minmax(0,1fr) 68px;gap:8px;padding:4px 8px;border-bottom:1px solid var(--border-subtle);font-size:12px;align-items:center}.frame-time{color:var(--muted)}.frame-direction{font-weight:700}.frame-row.tx .frame-direction{color:var(--info)}.frame-row.rx .frame-direction{color:var(--success)}.frame-body{overflow-wrap:anywhere}.crc{font-size:10px}.crc.ok{color:var(--success)}.crc.bad{color:var(--danger)}.btn-sm{font-size:11px;padding:3px 8px}@media(max-width:1200px){.config-grid{grid-template-columns:repeat(4,minmax(100px,1fr))}.workbench-columns{grid-template-columns:1fr}}@media(max-width:700px){.config-grid{grid-template-columns:repeat(2,minmax(110px,1fr))}.request-grid{grid-template-columns:1fr}.wide{grid-column:auto}.frame-row{grid-template-columns:80px 32px minmax(0,1fr)}.crc{display:none}}
</style>
