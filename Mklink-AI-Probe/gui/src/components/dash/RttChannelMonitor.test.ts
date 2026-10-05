import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import RttChannelMonitor from './RttChannelMonitor.vue'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

it('keeps a channel cursor and resets it on a local channel change', async () => {
  vi.useFakeTimers()
  const fetcher = vi.fn(async (url: string) => {
    const query = new URL(url, 'http://localhost').searchParams
    const ch = Number(query.get('channel'))
    return { ok: true, json: async () => ({ session: 'capture', cursor: 4,
      reset: false, lost_bytes: 2, data_hex: ch ? '00ff' : '6162' }) }
  })
  vi.stubGlobal('fetch', fetcher)
  const wrapper = mount(RttChannelMonitor, { props: { channels: [0, 1], running: true } })
  await flushPromises()
  expect(wrapper.get('[data-testid=rtt-channel-output]').text()).toContain('61 62')
  await vi.advanceTimersByTimeAsync(200)
  expect(fetcher.mock.calls[1]![0]).toContain('cursor=4')
  await wrapper.get('select').setValue('1')
  await vi.advanceTimersByTimeAsync(200)
  expect(fetcher.mock.calls[2]![0]).toContain('channel=1&cursor=0')
  expect(wrapper.get('[data-testid=rtt-channel-output]').text()).toBe('00 ff')
  wrapper.unmount()
})

it('discards an in-flight response after changing channels', async () => {
  vi.useFakeTimers()
  let complete!: (value: unknown) => void
  vi.stubGlobal('fetch', () => new Promise(resolve => { complete = resolve }))
  const wrapper = mount(RttChannelMonitor, { props: { channels: [0, 1], running: true } })
  await wrapper.get('select').setValue('1')
  complete({ ok: true, json: async () => ({ session: 'old', cursor: 2, data_hex: 'abcd', lost_bytes: 0 }) })
  await flushPromises()
  expect(wrapper.get('[data-testid=rtt-channel-output]').text()).toBe('')
  wrapper.unmount()
})
