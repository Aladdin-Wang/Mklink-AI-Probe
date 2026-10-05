<template>
  <main class="site-agent-page">
    <section class="page-heading">
      <div>
        <p class="eyebrow">MKLINK.REMOTE</p>
        <h2>{{ tr('远程服务', 'Remote Service') }}</h2>
        <p>{{ tr('为当前下载器启动远程连接入口，与本地 GUI 和 AI 共用后台。每台下载器使用独立端口和访问令牌。', 'Start remote access for this probe while sharing its backend with the local GUI and AI. Use a separate port and token for each probe.') }}</p>
      </div>
      <div :class="['runtime-badge', runtimeTone]" data-testid="site-agent-runtime">
        <span class="status-dot" />{{ runtimeLabel }}
      </div>
    </section>

    <section class="panel" data-testid="remote-roles">
      <h3>{{ tr('在本机提供服务，在远端接入', 'Host here, connect from another computer') }}</h3>
      <p>{{ tr('下载器接在本机：在下方启动服务，将地址和令牌交给远端使用者。', 'Probe attached here: start the service below and give its address and token to the remote user.') }}</p>
      <p>{{ tr('下载器接在另一台电脑：使用远程 Skill、CLI 或 MCP，连接那台电脑提供的服务地址。当前 GUI 的仪表盘仍操作本地下载器，不会切换到远端。', 'Probe attached to another computer: connect to its service using the remote Skill, CLI or MCP. This GUI dashboard continues to control the local probe; it does not switch to the remote target.') }}</p>
    </section>

    <div v-if="loading" class="panel loading-state">{{ tr('正在读取远程服务配置…', 'Loading remote service configuration…') }}</div>
    <template v-else>
      <section v-if="errorMessage" class="alert alert-error" role="alert">{{ errorMessage }}</section>

      <section class="overview-grid">
        <article class="metric-card">
          <span>{{ tr('远程入口', 'Remote endpoint') }}</span>
          <strong>{{ endpoint }}</strong>
          <small>{{ config.transport === 'lan-stcp' ? tr('由 STCP 私密隧道转发', 'Forwarded by a private STCP tunnel') : tr('WebSocket 直连', 'Direct WebSocket') }}</small>
        </article>
        <article class="metric-card">
          <span>{{ tr('探针', 'Probe') }}</span>
          <strong>{{ status?.probe_alias || probeId || tr('未选择下载器', 'No probe selected') }}</strong>
          <small>{{ status?.probe_connected ? tr('远程目标已连接', 'Remote target connected') : tr('远程目标未连接', 'Remote target not connected') }}</small>
          <small>{{ tr('与本地 GUI 共用当前下载器', 'Shares this probe with the local GUI') }}</small>
        </article>
        <article class="metric-card">
          <span>{{ tr('访问令牌', 'Access token') }}</span>
          <strong>{{ secrets.token_configured ? `•••• ${secrets.token_fingerprint ?? ''}` : tr('未配置', 'Not configured') }}</strong>
          <small>{{ IS_TAURI ? tr('按下载器使用 Windows DPAPI 加密保存', 'Encrypted with Windows DPAPI per probe') : tr('仅本次后台运行有效，不保存到浏览器', 'Valid for this backend run; not stored in the browser') }}</small>
        </article>
      </section>

      <section class="settings-layout">
        <article class="panel">
          <div class="panel-title">
            <div>
              <h3>{{ tr('服务设置', 'Service settings') }}</h3>
              <p>{{ tr('启动或停止只影响当前下载器的远程连接，不重启共享后台。更改设置会关闭已有远程连接。', 'Start and stop affect only this probe’s remote connections. The shared backend stays running. Applying settings closes existing remote connections.') }}</p>
            </div>
          </div>

          <div class="form-grid">
            <label>
              <span>{{ tr('连接模式', 'Transport') }}</span>
              <select v-model="config.transport" data-testid="site-agent-transport">
                <option value="direct">{{ tr('直连（局域网 / VPN）', 'Direct (LAN / VPN)') }}</option>
                <option value="lan-stcp">{{ tr('LAN STCP 私密隧道', 'LAN STCP private tunnel') }}</option>
              </select>
            </label>
            <label>
              <span>{{ tr('监听地址', 'Bind address') }}</span>
              <select v-model="config.bind_host" data-testid="site-agent-bind">
                <option v-for="address in bindAddresses" :key="address" :value="address">{{ address }}</option>
              </select>
            </label>
            <label>
              <span>{{ tr('监听端口', 'Port') }}</span>
              <input v-model.number="config.port" data-testid="site-agent-port" type="number" min="1" max="65535">
            </label>
            <label v-if="config.transport === 'direct'" class="check-field">
              <input v-model="config.allow_lan" type="checkbox">
              <span>{{ tr('明确允许非回环 LAN / VPN 连接', 'Explicitly allow non-loopback LAN / VPN access') }}</span>
            </label>
          </div>

          <div v-if="config.transport === 'lan-stcp'" class="stcp-grid">
            <label><span>FRP Server</span><input v-model.trim="config.stcp_server_addr" placeholder="192.168.1.20"></label>
            <label><span>{{ tr('服务端口', 'Server port') }}</span><input v-model.number="config.stcp_server_port" type="number" min="1" max="65535"></label>
            <label><span>User</span><input v-model.trim="config.stcp_user"></label>
            <label><span>Proxy Name</span><input v-model.trim="config.stcp_proxy_name"></label>
          </div>

          <div class="actions">
            <button class="btn btn-primary" data-testid="site-agent-save" :disabled="saving" @click="saveAndApply(true)">
              {{ saving ? tr('正在应用…', 'Applying…') : tr('启动 / 应用设置', 'Start / Apply settings') }}
            </button>
            <button class="btn" data-testid="remote-service-stop" :disabled="saving || !status?.running" @click="saveAndApply(false)">{{ tr('停止远程服务', 'Stop remote service') }}</button>
            <button class="btn" :disabled="refreshing" @click="refreshStatus">{{ tr('刷新状态', 'Refresh status') }}</button>
          </div>
        </article>

        <aside class="side-stack">
          <article class="panel credential-panel">
            <h3>{{ tr('凭据', 'Credentials') }}</h3>
            <p>{{ tr('访问令牌用于远程握手认证；不要粘贴到公开日志或聊天中。运行中请先停止服务再轮换令牌。', 'Tokens authenticate remote clients. Keep them out of public logs and chats. Stop the service before rotating a token.') }}</p>
            <button class="btn" data-testid="site-agent-token" :disabled="credentialBusy || !!status?.running" @click="generateToken">
              {{ secrets.token_configured ? tr('轮换访问令牌', 'Rotate access token') : tr('生成访问令牌', 'Generate access token') }}
            </button>

            <label v-if="generatedToken" class="secret-fields">{{ tr('请复制令牌并妥善保存；离开页面后不再显示。', 'Copy this token now; it will disappear when you leave this page.') }}<input :value="generatedToken" readonly data-testid="generated-token"></label>
            <div v-if="config.transport === 'lan-stcp'" class="secret-fields">
              <label><span>FRP Auth Token</span><input v-model="stcpAuth" type="password" autocomplete="new-password"></label>
              <label><span>STCP Secret</span><input v-model="stcpSecret" type="password" autocomplete="new-password"></label>
              <button class="btn" :disabled="credentialBusy || !stcpAuth || !stcpSecret" @click="saveStcpCredentials">{{ tr('保存 STCP 凭据', 'Save STCP credentials') }}</button>
            </div>
          </article>

          <article class="panel workflow-panel">
            <h3>{{ tr('工程师连接方式', 'Engineer workflow') }}</h3>
            <ol>
              <li>{{ tr('先在配置页选择下载器和工程；当前页面只控制这台下载器。', 'Select the probe and project in Config first. This page controls only that probe.') }}</li>
              <li>{{ tr('本机使用 127.0.0.1；局域网选择本机网卡地址并勾选允许 LAN。为每台下载器指定不同端口。', 'Use 127.0.0.1 locally. For LAN access, select this computer’s network address and allow LAN access. Assign a different port to each probe.') }}</li>
              <li>{{ tr('生成访问令牌，点击启动，确认状态显示运行中。把下方地址和令牌交给需要连接的客户端。', 'Generate a token, start the service, and confirm Running. Give the address below and token to the connecting client.') }}</li>
              <li>{{ tr('远程客户端使用 MKLink Skill、CLI 或 MCP：先握手认证，再连接目标并调用能力。此地址是 WebSocket 服务，不能直接作为网页打开。', 'Use MKLink Skill, CLI, or MCP: authenticate, connect the target, then call its capabilities. This WebSocket address is not a browser page.') }}</li>
              <li>{{ tr('停止服务会等待正在执行的请求结束，再断开远程客户端；本地 GUI、其他下载器和后台保持运行。局域网不通时检查网络与 Windows 防火墙，不要把地址改为 0.0.0.0。', 'Stopping waits for active requests, then disconnects remote clients. Local GUI, other probes, and the backend stay running. If LAN access fails, check the network and Windows Firewall.') }}</li>
            </ol>
            <p>{{ tr('远程 RTT / SystemView 与本地仪表盘共用采集。连接后先查询服务能力；数据可能因断线或缓冲溢出而丢失，请检查返回的丢失提示。', 'Remote RTT / SystemView shares capture with local dashboards. Query service capabilities after connecting. Disconnections or buffer overflow can lose data; check the returned loss indicators.') }}</p>
            <p v-if="config.transport === 'lan-stcp'">{{ tr('STCP 还需要工程师端配置配套访问端；本地监听地址不能直接用于跨机访问。', 'STCP also requires a matching visitor on the engineer computer. The local listener address is not a cross-machine endpoint.') }}</p>
            <code>{{ endpoint }}</code>
          </article>
        </aside>
      </section>
    </template>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { API_BASE, IS_TAURI } from '../lib/runtimeEndpoint'
import { tr } from '../composables/useLanguage'
import { useToast } from '../composables/useToast'

interface SiteAgentConfig {
  schema: string
  enabled: boolean
  transport: 'direct' | 'lan-stcp'
  bind_host: string
  port: number
  allow_lan: boolean
  stcp_server_addr: string
  stcp_server_port: number
  stcp_user: string
  stcp_proxy_name: string
}

interface SecretState {
  token_configured: boolean
  token_fingerprint: string | null
  stcp_credentials_configured: boolean
}

interface AgentStatus {
  probe_id?: string
  probe_alias?: string
  host?: string
  port?: number
  token_configured?: boolean
  token_fingerprint?: string
  stcp_credentials_configured?: boolean
  enabled: boolean
  running: boolean
  ready: boolean
  probe_connected: boolean
  transport_ready?: boolean
  last_error?: string | null
  configuration_error?: string | null
}

const toast = useToast()
const loading = ref(true)
const saving = ref(false)
const refreshing = ref(false)
const credentialBusy = ref(false)
const bindAddresses = ref<string[]>(['127.0.0.1'])
const status = ref<AgentStatus | null>(null)
const secrets = reactive<SecretState>({ token_configured: false, token_fingerprint: null, stcp_credentials_configured: false })
const config = reactive<SiteAgentConfig>({
  schema: 'mklink.site-agent.config.v1',
  enabled: false,
  transport: 'direct',
  bind_host: '127.0.0.1',
  port: 8766,
  allow_lan: false,
  stcp_server_addr: '',
  stcp_server_port: 7000,
  stcp_user: '',
  stcp_proxy_name: '',
})
const generatedToken = ref('')
const probeId = ref('')
const stcpAuth = ref('')
const stcpSecret = ref('')
let timer: ReturnType<typeof setInterval> | null = null

const endpoint = computed(() => `ws://${config.bind_host.includes(':') ? `[${config.bind_host}]` : config.bind_host}:${config.port}`)
const runtimeTone = computed(() => status.value?.ready ? 'ready' : errorMessage.value ? 'failed' : 'stopped')
const runtimeLabel = computed(() => {
  if (status.value?.ready) return tr('运行中', 'Running')
  if (status.value?.last_error) return tr('需要处理', 'Needs attention')
  return tr('已停止', 'Stopped')
})
const errorMessage = computed(() => status.value?.last_error || status.value?.configuration_error || '')

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

async function serviceRequest<T>(path = '', body?: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${API_BASE}/_runtime/remote-service${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const value = await response.json()
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : `HTTP ${response.status}`)
  return value as T
}

async function loadNativeState() {
  const current = await serviceRequest<AgentStatus & Record<string, unknown>>()
  status.value = current
  probeId.value = current.probe_id || ''
  for (const key of ['enabled', 'transport', 'port', 'allow_lan', 'stcp_server_addr', 'stcp_server_port', 'stcp_user', 'stcp_proxy_name']) {
    if (current[key] !== undefined) Object.assign(config, { [key]: current[key] })
  }
  config.bind_host = current.host || '127.0.0.1'
  if (IS_TAURI) {
    const [saved, secretState, addresses] = await Promise.all([
      invoke<SiteAgentConfig>('site_agent_config_get', { probeId: probeId.value }),
      invoke<SecretState>('site_agent_secret_state', { probeId: probeId.value }),
      invoke<string[]>('site_agent_bind_addresses'),
    ])
    if (!current.running) Object.assign(config, saved)
    Object.assign(secrets, secretState)
    bindAddresses.value = addresses
  } else {
    Object.assign(secrets, { token_configured: !!current.token_configured, token_fingerprint: current.token_fingerprint || null, stcp_credentials_configured: !!current.stcp_credentials_configured })
    bindAddresses.value = await serviceRequest<string[]>('/addresses')
  }
  if (!bindAddresses.value.includes(config.bind_host)) bindAddresses.value.unshift(config.bind_host)
}

async function refreshStatus() {
  refreshing.value = true
  try {
    status.value = await serviceRequest<AgentStatus>()
  } catch (error) {
    status.value = { enabled: config.enabled, running: false, ready: false, probe_connected: false, last_error: message(error) }
  } finally { refreshing.value = false }
}

async function saveAndApply(enabled: boolean) {
  saving.value = true
  try {
    config.enabled = enabled
    if (!enabled) {
      status.value = await serviceRequest<AgentStatus>('/stop', {})
      if (IS_TAURI) await invoke('site_agent_config_save', { probeId: probeId.value, config: { ...config } })
    } else {
      let payload: Record<string, unknown>
      if (IS_TAURI) {
        await invoke('site_agent_config_save', { probeId: probeId.value, config: { ...config } })
        payload = await invoke('site_agent_runtime_settings', { probeId: probeId.value })
      } else {
        const { schema: _schema, bind_host, ...settings } = config
        payload = { ...settings, host: bind_host }
        if (stcpAuth.value) payload.stcp_auth_token = stcpAuth.value
        if (stcpSecret.value) payload.stcp_secret = stcpSecret.value
      }
      status.value = await serviceRequest<AgentStatus>('', payload)
    }
    toast.success(enabled ? tr('远程服务已启动', 'Remote service started') : tr('远程服务已停止', 'Remote service stopped'))
  } catch (error) {
    toast.error(tr('应用远程服务设置失败：', 'Failed to apply remote service settings: ') + message(error))
    await refreshStatus()
  } finally { saving.value = false }
}

async function generateToken() {
  credentialBusy.value = true
  try {
    await refreshStatus()
    if (status.value?.running) throw new Error(tr('请先停止远程服务', 'Stop remote service first'))
    if (IS_TAURI) {
      await invoke('site_agent_generate_token_and_copy', { probeId: probeId.value })
      Object.assign(secrets, await invoke<SecretState>('site_agent_secret_state', { probeId: probeId.value }))
      toast.success(tr('令牌已复制并加密保存', 'Token copied and encrypted'))
    } else {
      const result = await serviceRequest<{ token: string; fingerprint: string }>('/token', { confirm: true })
      generatedToken.value = result.token
      secrets.token_configured = true
      secrets.token_fingerprint = result.fingerprint
    }
  } catch (error) { toast.error(message(error)) }
  finally { credentialBusy.value = false }
}

async function saveStcpCredentials() {
  credentialBusy.value = true
  try {
    if (IS_TAURI) {
      await invoke('site_agent_stcp_credentials_configure', { probeId: probeId.value, authToken: stcpAuth.value, secretKey: stcpSecret.value })
      stcpAuth.value = ''; stcpSecret.value = ''
      Object.assign(secrets, await invoke<SecretState>('site_agent_secret_state', { probeId: probeId.value }))
    }
    toast.success(tr('凭据将在下次启动时应用', 'Credentials will apply on the next start'))
  } catch (error) { toast.error(message(error)) }
  finally { credentialBusy.value = false }
}

onMounted(async () => {
  try {
    await loadNativeState()
    await refreshStatus()
    timer = window.setInterval(() => void refreshStatus(), 3000)
  } catch (error) {
    status.value = { enabled: false, running: false, ready: false, probe_connected: false, last_error: tr('请先选择下载器并打开共享后台。', 'Select a probe and open its shared backend first.') + ' ' + message(error) }
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<style scoped>
.site-agent-page{display:flex;flex-direction:column;gap:16px;max-width:1280px;margin:0 auto;padding:18px 20px 28px}.page-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.page-heading h2{font-size:22px;margin:2px 0 5px}.page-heading p{max-width:760px;color:var(--muted);font-size:13px}.eyebrow{font:700 10px/1 var(--font-mono);letter-spacing:.16em;color:var(--accent)!important}.runtime-badge{display:flex;align-items:center;gap:7px;padding:7px 11px;border:1px solid var(--border);border-radius:999px;background:var(--surface);font-size:12px;white-space:nowrap}.status-dot{width:8px;height:8px;border-radius:50%;background:var(--dim)}.runtime-badge.ready{color:var(--success)}.runtime-badge.ready .status-dot{background:var(--success);box-shadow:0 0 0 4px rgb(45 106 79 / 12%)}.runtime-badge.failed{color:var(--danger)}.runtime-badge.failed .status-dot{background:var(--danger)}.panel,.metric-card{border:1px solid var(--border);border-radius:8px;background:var(--surface)}.loading-state{padding:40px;text-align:center;color:var(--muted)}.overview-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.metric-card{display:grid;gap:4px;padding:14px 16px}.metric-card span,.metric-card small{font-size:11px;color:var(--muted)}.metric-card strong{overflow:hidden;text-overflow:ellipsis;font:600 14px/1.45 var(--font-mono)}.settings-layout{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(300px,.75fr);gap:14px}.panel{padding:17px}.panel-title{display:flex;justify-content:space-between;gap:18px;padding-bottom:14px;border-bottom:1px solid var(--border-subtle)}.panel h3{font-size:15px;margin:0 0 5px}.panel p{font-size:12px;color:var(--muted)}.switch-row{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:600;white-space:nowrap}.form-grid,.stcp-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}.form-grid label,.stcp-grid label,.secret-fields label{display:grid;gap:5px}.form-grid label>span,.stcp-grid label>span,.secret-fields label>span{font-size:11px;color:var(--muted)}input,select{width:100%;height:34px;padding:0 9px;border:1px solid var(--border);border-radius:5px;background: var(--input-bg, #fff);color:var(--fg);font:12px var(--font-body)}.check-field{display:flex!important;grid-column:1/-1;align-items:center;grid-template-columns:auto 1fr!important}.check-field input,.switch-row input{width:16px;height:16px}.actions{display:flex;gap:8px;margin-top:18px}.side-stack{display:grid;gap:14px;align-content:start}.credential-panel>.btn{margin-top:14px}.secret-fields{display:grid;gap:10px;margin-top:15px;padding-top:15px;border-top:1px solid var(--border-subtle)}.workflow-panel ol{display:grid;gap:9px;margin:13px 0 14px;padding-left:20px;color:var(--muted);font-size:12px}.workflow-panel code{display:block;overflow:auto;padding:9px;border-radius:5px;background:var(--bg);font:11px var(--font-mono)}@media(max-width:900px){.overview-grid{grid-template-columns:1fr}.settings-layout{grid-template-columns:1fr}}@media(max-width:620px){.page-heading,.panel-title{flex-direction:column}.form-grid,.stcp-grid{grid-template-columns:1fr}.site-agent-page{padding:14px 12px}}
</style>
