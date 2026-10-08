import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import RemoteConnectPanel from './RemoteConnectPanel.vue'
vi.mock('../../lib/runtimeEndpoint', () => ({ API_BASE: '' }))
afterEach(() => vi.unstubAllGlobals())
it('creates a distinct remote session and clears the token before opening its window', async () => {
  const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ id: 'new-window' }) }))
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(RemoteConnectPanel)
  await wrapper.get('[data-testid="remote-connect-url"]').setValue('ws://remote:8766')
  await wrapper.get('[data-testid="remote-connect-token"]').setValue('test-secret')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(fetch.mock.calls[0][0]).toBe('/_runtime/remote-windows')
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ url: 'ws://remote:8766', token: 'test-secret' })
  expect(fetch.mock.calls[1][0]).toBe('/_runtime/remote-windows/new-window/open')
  expect((wrapper.get('[data-testid="remote-connect-token"]').element as HTMLInputElement).value).toBe('')
  wrapper.unmount()
})
