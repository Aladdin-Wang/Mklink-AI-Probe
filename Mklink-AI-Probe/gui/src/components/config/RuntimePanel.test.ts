import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import RuntimePanel from './RuntimePanel.vue'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('shows client ownership, blocks subscribed capture stop and ends only the chosen session', async () => {
  const payload = {
    probe_id: 'test-probe', status: 'present', connected: true, busy: false, project_root: 'test-project',
    probe: { alias: '测试板', port: 'COM10' }, operation: { path: '/api/device/read-memory', client: 'AI test' },
    clients: [{ id: 'public-handle', name: 'AI test', kind: 'mcp', streams: ['rtt'], expires_in: 100 }],
    streams: [{ name: 'rtt', running: true, subscribers: 1 }], last_operation: null,
  }
  const fetch = vi.fn().mockImplementation(async () => ({ ok: true, json: async () => payload }))
  vi.stubGlobal('fetch', fetch)
  vi.stubGlobal('confirm', vi.fn(() => true))
  const wrapper = mount(RuntimePanel)
  await flushPromises()
  expect(wrapper.text()).toContain('测试板')
  expect(wrapper.get('[data-testid=runtime-operation]').text()).toContain('AI test')
  const stop = wrapper.findAll('button').find(button => button.text().includes('停止采集'))!
  expect(stop.attributes('disabled')).toBeDefined()
  const detach = wrapper.findAll('button').find(button => button.text().includes('结束会话'))!
  await detach.trigger('click')
  await flushPromises()
  const mutation = fetch.mock.calls.find(([url]) => String(url).endsWith('/detach-client'))!
  expect(JSON.parse(mutation[1].body)).toEqual({ client_id: 'public-handle', confirm: true })
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/release-device'))).toBe(false)
  wrapper.unmount()
})

it('surfaces backend refusal without claiming that a release succeeded', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url) => ({
    ok: !String(url).endsWith('/release-device'),
    json: async () => String(url).endsWith('/release-device') ? { detail: 'Other clients are attached' } : {
      probe_id: 'test', status: 'present', connected: true, busy: false, clients: [], streams: [],
      project_root: '.', operation: null, probe: null,
    },
  })))
  vi.stubGlobal('confirm', vi.fn(() => true))
  const wrapper = mount(RuntimePanel)
  await flushPromises()
  await wrapper.get('[data-testid=runtime-release]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role=alert]').text()).toContain('Other clients')
  wrapper.unmount()
})
