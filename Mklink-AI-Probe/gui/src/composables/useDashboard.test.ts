import { afterEach, expect, it, vi } from 'vitest'
import { useDashboard, useDeviceApi } from './useDashboard'

afterEach(() => vi.unstubAllGlobals())

it('explains shared capture conflicts instead of displaying only Conflict', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false, statusText: 'Conflict', json: async () => ({ detail: { busy: ['rtt'], hint: 'Stop acquisition' } }),
  }))
  await expect(useDeviceApi().readMemory('0x20000000', 4)).rejects.toThrow('RTT View 正在采集')
})

it('keeps running state when another shared client prevents stop', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false, statusText: 'Conflict', json: async () => ({ detail: 'Other clients subscribe to this acquisition' }),
  }))
  const dash = useDashboard('rtt')
  dash.syncState(true)
  expect(await dash.stop()).toBe(false)
  expect(dash.state.value).toBe('running')
  expect(dash.error.value).toContain('Other clients subscribe')
})
