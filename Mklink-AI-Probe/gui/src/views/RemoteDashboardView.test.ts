import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import RemoteDashboardView from './RemoteDashboardView.vue'
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { windowId: 'window-a' } }) }))
vi.mock('../lib/runtimeEndpoint', () => ({ API_BASE: '' }))
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
it('sends only window-scoped requests and disables controls after connection loss', async () => {
  const fetch = vi.fn(async (url, options) => {
    if (!options) return { ok: true, json: async () => ({ connected: true, endpoint: 'ws://remote', identity: { probe_id: 'remote-a' }, capabilities: ['target.memory'] }) }
    if (String(url).endsWith('/close')) return { ok: true, json: async () => ({}) }
    const method = JSON.parse(options.body).method
    if (method === 'memory.read') return { ok: false, status: 410, json: async () => ({ detail: 'Remote connection lost' }) }
    return { ok: true, json: async () => ({ probe_id: 'remote-a' }) }
  })
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(RemoteDashboardView)
  await flushPromises()
  await wrapper.get('[data-testid="remote-memory-read"]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('Remote connection lost')
  expect(wrapper.get('[data-testid="remote-memory-read"]').element.closest('fieldset')!.disabled).toBe(true)
  expect(fetch.mock.calls.every(([url]) => String(url).startsWith('/_runtime/remote-windows/window-a'))).toBe(true)
  expect(fetch.mock.calls.filter(([,options]) => options?.body && JSON.parse(options.body).method === 'memory.read')).toHaveLength(1)
  wrapper.unmount()
})
it('writes only after confirmation and supplies the remote protocol confirmation', async () => {
  const fetch = vi.fn(async (_url, options) => ({ ok: true, json: async () => options ? {} : { connected: true, endpoint: 'ws://remote', identity: { probe_id: 'remote-a' }, capabilities: ['target.memory'] } }))
  const confirm = vi.fn(() => false)
  vi.stubGlobal('fetch', fetch)
  vi.stubGlobal('confirm', confirm)
  const wrapper = mount(RemoteDashboardView)
  await flushPromises()
  await wrapper.get('[data-testid="remote-memory-bytes"]').setValue('01 02')
  const writes = () => fetch.mock.calls.filter(([,options]) => options?.body && JSON.parse(options.body).method === 'memory.write')
  await wrapper.get('[data-testid="remote-memory-write"]').trigger('click')
  await flushPromises()
  expect(writes()).toHaveLength(0)
  confirm.mockReturnValue(true)
  await wrapper.get('[data-testid="remote-memory-write"]').trigger('click')
  await flushPromises()
  expect(writes()).toHaveLength(1)
  expect(JSON.parse(writes()[0][1].body).params).toEqual({ address: 0x20000000, data_b64: 'AQI=', confirm: true })
  wrapper.unmount()
})
