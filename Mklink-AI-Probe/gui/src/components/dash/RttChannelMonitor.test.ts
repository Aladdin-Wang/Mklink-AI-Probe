import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { loadDesktopSettings } from '../../lib/desktopSettings'
import RttChannelMonitor from './RttChannelMonitor.vue'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
const props = (channel: number) => ({ channel, running: true, paused: false, sendEnabled: true,
  settings: loadDesktopSettings(localStorage), send: vi.fn(async () => {}) })
it('reads all mounted channels independently and keeps collecting while collapsed', async () => {
  vi.useFakeTimers()
  const fetcher = vi.fn(async (url: string) => {
    const q = new URL(url, 'http://localhost').searchParams
    return { ok: true, json: async () => ({ session: 'capture', cursor: Number(q.get('cursor')) + 2,
      reset: false, lost_bytes: 0, data_hex: q.get('channel') === '1' ? '6162' : '00ff' }) }
  })
  vi.stubGlobal('fetch', fetcher)
  const a = mount(RttChannelMonitor, { props: props(1) })
  const b = mount(RttChannelMonitor, { props: props(2) })
  await flushPromises()
  await a.findAll('button')[0]!.trigger('click')
  await vi.advanceTimersByTimeAsync(200)
  expect(fetcher.mock.calls.some(([url]) => url.includes('channel=1&cursor=2&session=capture'))).toBe(true)
  expect(fetcher.mock.calls.some(([url]) => url.includes('channel=2&cursor=2&session=capture'))).toBe(true)
  await a.findAll('button')[0]!.trigger('click')
  expect(a.get('pre').text()).toBe('61 62 61 62')
  await a.get('input[type=checkbox]').setValue(false)
  expect(a.get('pre').text()).toBe('abab')
  expect(b.get('pre').text()).toBe('00 ff 00 ff')
  a.unmount(); b.unmount()
})
it('bounds history, reports eviction separately and retains history after stopping', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ session: 'capture', cursor: 65538,
    reset: false, lost_bytes: 7, data_hex: '61'.repeat(65538) }) })))
  const a = mount(RttChannelMonitor, { props: props(1) })
  await flushPromises()
  expect(a.text()).toContain('7 B')
  expect(a.text()).toContain('2 B')
  await a.get('input[type=checkbox]').setValue(false)
  expect(a.get('pre').text().length).toBe(65536)
  await a.setProps({ running: false })
  await vi.advanceTimersByTimeAsync(400)
  expect(a.get('pre').text().length).toBe(65536)
  a.unmount()
})
it('ignores responses after unmount and aborts its outstanding read', async () => {
  let finish!: (data: unknown) => void
  let signal!: AbortSignal
  vi.stubGlobal('fetch', (_url: string, init: RequestInit) => { signal = init.signal as AbortSignal; return new Promise(r => { finish = r }) })
  const a = mount(RttChannelMonitor, { props: props(1) })
  a.unmount()
  expect(signal.aborted).toBe(true)
  finish({ ok: true, json: async () => ({ cursor: 2, session: 'old', data_hex: 'abcd', lost_bytes: 0 }) })
  await flushPromises()
})
