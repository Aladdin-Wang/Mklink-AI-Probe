import { afterEach, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import DashboardView from './DashboardView.vue'
vi.mock('../lib/runtimeEndpoint', () => ({ API_BASE: '/_runtime/remote-windows/fixed', IS_REMOTE: true, IS_TAURI: false, REMOTE_WINDOW_ID: 'fixed' }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }))
afterEach(() => vi.unstubAllGlobals())
it('reuses existing memory and RTT panels while blocking host-only controls', async () => {
  const fetch = vi.fn(async () => ({ ok: true, json: async () => ({}) }))
  vi.stubGlobal('fetch', fetch)
  const wrapper = shallowMount(DashboardView)
  expect(wrapper.findComponent({ name: 'RttViewTab' }).exists()).toBe(true)
  expect(wrapper.findComponent({ name: 'SerialMonitorTab' }).exists()).toBe(false)
  for (const label of ['串口助手', 'Modbus']) {
    const button = wrapper.findAll('.tab-btn').find(b => b.text() === label)!
    expect((button.element as HTMLButtonElement).disabled).toBe(true)
  }
  await wrapper.findAll('.tab-btn').find(b => b.text() === 'Memory')!.trigger('click')
  expect(wrapper.findComponent({ name: 'MemoryTab' }).exists()).toBe(true)
  expect(wrapper.find('[data-testid="vofa-page"]').exists()).toBe(false)
  expect(fetch.mock.calls.every(([url]) => String(url).startsWith('/_runtime/remote-windows/fixed/'))).toBe(true)
  wrapper.unmount()
})
it('retains the last remote snapshot on transport loss instead of clearing displayed data', async () => {
  const { useMklinkApi } = await import('../composables/useMklinkApi')
  const api = useMklinkApi()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ connected: true, mcu: 'remote-mcu', axf: { loaded: true } }) })))
  await api.refreshStatus()
  vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Disconnected') }))
  await api.refreshStatus()
  expect(api.deviceStatus.value.mcu).toBe('remote-mcu')
})
