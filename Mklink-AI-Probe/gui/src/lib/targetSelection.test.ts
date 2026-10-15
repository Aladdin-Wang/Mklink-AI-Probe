import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { consumerTarget, publishOnlineTarget, saveConsumerTarget } from './targetSelection'

beforeEach(() => {
  const values = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  })
})
afterEach(() => vi.unstubAllGlobals())

it('shares the online target, preserves independent overrides, and adopts a new online selection', () => {
  publishOnlineTarget('STM32F103RC')
  expect(consumerTarget('offline')).toBe('STM32F103RC')
  expect(consumerTarget('peripheral')).toBe('STM32F103RC')
  saveConsumerTarget('offline', 'HPM5301')
  saveConsumerTarget('peripheral', 'STM32F103RE')
  expect(consumerTarget('offline')).toBe('HPM5301')
  expect(consumerTarget('peripheral')).toBe('STM32F103RE')
  publishOnlineTarget('STM32F407VG')
  expect(consumerTarget('offline')).toBe('STM32F407VG')
  expect(consumerTarget('peripheral')).toBe('STM32F407VG')
})
