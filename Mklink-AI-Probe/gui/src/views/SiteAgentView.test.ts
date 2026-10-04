import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SiteAgentView from './SiteAgentView.vue'
import { setLanguage } from '../composables/useLanguage'
const mocks = vi.hoisted(() => ({ invoke: vi.fn(), native: false, fetch: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }))
vi.mock('../lib/runtimeEndpoint', () => ({ API_BASE: 'http://127.0.0.1:8765', get IS_TAURI() { return mocks.native } }))
const probeId = 'usb-' + 'a'.repeat(24)
const config = { schema: 'mklink.site-agent.config.v1', enabled: false, transport: 'direct', bind_host: '127.0.0.1', port: 8766, allow_lan: false, stcp_server_addr: '', stcp_server_port: 7000, stcp_user: '', stcp_proxy_name: '' }
let running = false

describe('Remote service', () => {
  beforeEach(() => {
    setLanguage('en'); running = false; mocks.native = false
    mocks.invoke.mockReset(); mocks.fetch.mockReset()
    mocks.invoke.mockImplementation(async (command: string) => {
      if (command === 'site_agent_config_get') return { ...config }
      if (command === 'site_agent_secret_state') return { token_configured: true, token_fingerprint: 'abcd', stcp_credentials_configured: false }
      if (command === 'site_agent_bind_addresses') return ['127.0.0.1', '192.168.1.20']
      if (command === 'site_agent_runtime_settings') return { enabled: true, host: '127.0.0.1', port: 8766, token: 'private-token' }
      return true
    })
    mocks.fetch.mockImplementation(async (url: string, options?: RequestInit) => {
      let result: unknown
      if (url.endsWith('/addresses')) result = ['127.0.0.1', '192.168.1.20']
      else if (url.endsWith('/token')) result = { token: 'one-time-token', fingerprint: 'abcd' }
      else {
        if (options?.method === 'POST') running = !url.endsWith('/stop')
        result = { ...config, host: '127.0.0.1', running, ready: running, probe_connected: false, probe_id: probeId, token_configured: true, token_fingerprint: 'abcd' }
      }
      return { ok: true, json: async () => result }
    })
    vi.stubGlobal('fetch', mocks.fetch)
  })

  it('explains local and LAN operation without claiming a browser endpoint', async () => {
    const wrapper = mount(SiteAgentView); await flushPromises()
    expect(wrapper.text()).toContain('Remote Service')
    expect(wrapper.text()).toContain('WebSocket address is not a browser page')
    expect(wrapper.text()).toContain('Windows Firewall')
    expect(wrapper.text()).toContain('not stored in the browser')
    expect(mocks.invoke).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('starts and stops only the remote listener', async () => {
    const wrapper = mount(SiteAgentView); await flushPromises()
    await wrapper.get('[data-testid="site-agent-bind"]').setValue('192.168.1.20')
    await wrapper.get('[data-testid="site-agent-port"]').setValue(8877)
    await wrapper.get('[data-testid="site-agent-save"]').trigger('click'); await flushPromises()
    const call = mocks.fetch.mock.calls.find(([, options]) => options?.method === 'POST')!
    expect(JSON.parse(call[1].body)).toMatchObject({ host: '192.168.1.20', port: 8877, enabled: true })
    expect(JSON.parse(call[1].body)).not.toHaveProperty('schema')
    await wrapper.get('[data-testid="remote-service-stop"]').trigger('click'); await flushPromises()
    expect(mocks.fetch.mock.calls.some(([url]) => url.endsWith('/remote-service/stop'))).toBe(true)
    expect(mocks.invoke).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows a browser token only after explicit generation', async () => {
    const wrapper = mount(SiteAgentView); await flushPromises()
    expect(wrapper.find('[data-testid="generated-token"]').exists()).toBe(false)
    await wrapper.get('[data-testid="site-agent-token"]').trigger('click'); await flushPromises()
    expect((wrapper.get('[data-testid="generated-token"]').element as HTMLInputElement).value).toBe('one-time-token')
    wrapper.unmount()
  })

  it('scopes desktop credentials to the probe and applies without restarting the backend', async () => {
    mocks.native = true
    const wrapper = mount(SiteAgentView); await flushPromises()
    expect(mocks.invoke).toHaveBeenCalledWith('site_agent_config_get', { probeId })
    await wrapper.get('[data-testid="site-agent-save"]').trigger('click'); await flushPromises()
    expect(mocks.invoke).toHaveBeenCalledWith('site_agent_config_save', { probeId, config: expect.objectContaining({ enabled: true }) })
    expect(mocks.invoke).toHaveBeenCalledWith('site_agent_runtime_settings', { probeId })
    expect(mocks.invoke.mock.calls.some(([command]) => command === 'restart_sidecar')).toBe(false)
    expect(wrapper.text()).not.toContain('private-token')
    wrapper.unmount()
  })
})
