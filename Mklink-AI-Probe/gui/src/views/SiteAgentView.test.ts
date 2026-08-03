import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SiteAgentView from './SiteAgentView.vue'
import { setLanguage } from '../composables/useLanguage'

const invokeMock = vi.hoisted(() => vi.fn())

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

const savedConfig = {
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
}

describe('SiteAgentView', () => {
  beforeEach(() => {
    setLanguage('en')
    invokeMock.mockReset()
    invokeMock.mockImplementation((command: string) => {
      if (command === 'site_agent_config_get') return Promise.resolve({ ...savedConfig })
      if (command === 'site_agent_secret_state') return Promise.resolve({
        token_configured: true,
        token_fingerprint: 'a1b2c3d4',
        stcp_credentials_configured: false,
      })
      if (command === 'site_agent_bind_addresses') return Promise.resolve(['127.0.0.1', '192.168.1.30'])
      return Promise.resolve(true)
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ enabled: false, running: false, ready: false, probe_connected: false }),
    }))
  })

  it('shows the shared-device workflow without exposing credential plaintext', async () => {
    const wrapper = mount(SiteAgentView)
    await flushPromises()

    expect(wrapper.text()).toContain('ws://127.0.0.1:8766')
    expect(wrapper.text()).toContain('Shared with the main GUI device instance')
    expect(wrapper.text()).toContain('a1b2c3d4')
    expect(wrapper.text()).not.toContain('site-secret')
    expect(invokeMock).toHaveBeenCalledWith('site_agent_config_get')
    wrapper.unmount()
  })

  it('persists configuration before restarting the unified sidecar', async () => {
    const wrapper = mount(SiteAgentView)
    await flushPromises()

    await wrapper.get('[data-testid="site-agent-enabled"]').setValue(true)
    await wrapper.get('[data-testid="site-agent-save"]').trigger('click')
    await flushPromises()

    expect(invokeMock).toHaveBeenCalledWith('site_agent_config_save', {
      config: expect.objectContaining({ enabled: true, port: 8766 }),
    })
    const saveIndex = invokeMock.mock.calls.findIndex(call => call[0] === 'site_agent_config_save')
    const restartIndex = invokeMock.mock.calls.findIndex(call => call[0] === 'restart_sidecar')
    expect(restartIndex).toBeGreaterThan(saveIndex)
    wrapper.unmount()
  })
})
