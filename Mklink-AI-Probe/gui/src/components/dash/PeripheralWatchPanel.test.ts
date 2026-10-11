import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import PeripheralWatchPanel from './PeripheralWatchPanel.vue'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

it('shows an unavailable saved selection without blocking chip selection and clears it after repair', async () => {
  const target = { id: 'stable', target: 'STM32F103RE', pack: 'Keil.DFP@1', svd: 'SVD/F103.svd' }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const data = url.includes('/targets') ? { targets: [target] }
      : url.endsWith('/select') ? { selection: target, items: [], restore_error: null }
      : url.endsWith('/peripherals') ? { selection: null, items: [], restore_error: 'Unavailable saved Pack' }
      : { items: [] }
    return { ok: true, json: async () => data }
  }))
  const wrapper = mount(PeripheralWatchPanel, { props: { deviceConnected: true, latestValues: {} } })
  try {
    await flushPromises()
    expect(wrapper.get('[data-testid="peripheral-restore-warning"]').text()).toContain('Unavailable saved Pack')
    await wrapper.get('[data-testid="peripheral-chip-search"]').trigger('focus')
    await wrapper.get('.chip-suggestion').trigger('click')
    expect(wrapper.get('[data-testid="peripheral-load"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="peripheral-load"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="peripheral-restore-warning"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="peripheral-source"]').text()).toContain('STM32F103RE')
  } finally { wrapper.unmount() }
})

it('loads a selected Pack chip, samples a GPIO bit without AXF, and keeps failed changes unchecked', async () => {
  const target = { id: 'chip', target: 'STM32F103RE', pack: 'Keil.DFP@1', svd: 'SVD/F103.svd' }
  const item = { name: 'GPIOB.12', register: 'GPIOB.IDR', address: '0x40010C08' }
  let fail = false
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    let data: object = {}
    if (url.includes('/targets')) data = { targets: [target] }
    else if (url.endsWith('/select')) {
      expect(JSON.parse(String(options?.body))).toEqual({ target_id: 'chip' })
      data = { selection: target, items: [item] }
    } else if (url.endsWith('/add')) {
      expect(JSON.parse(String(options?.body))).toEqual({ name: 'GPIOB.12' })
      data = fail ? { item: { error: 'Cannot sample' } } : { item }
    } else if (url.endsWith('/items')) data = { items: [] }
    else data = { items: [] }
    return { ok: true, json: async () => data }
  })
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(PeripheralWatchPanel, { props: { deviceConnected: true, latestValues: { 'GPIOB.12': 1 } } })
  await flushPromises()
  await wrapper.get('[data-testid="peripheral-chip-search"]').trigger('focus')
  await wrapper.get('[data-testid="peripheral-chip-search"]').trigger('keydown', { key: 'Enter' })
  expect((wrapper.get('[data-testid="peripheral-svd"]').element as HTMLSelectElement).value).toBe('chip')
  expect(wrapper.get('[data-testid="peripheral-svd"]').text()).toContain('F103.svd')
  await wrapper.get('[data-testid="peripheral-load"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[data-testid="peripheral-source"]').text()).toContain('STM32F103RE')
  expect(wrapper.get('output').text()).toBe('1')
  await wrapper.get('[data-testid="peripheral-GPIOB.12"]').setValue(true)
  await flushPromises()
  expect((wrapper.get('[data-testid="peripheral-GPIOB.12"]').element as HTMLInputElement).checked).toBe(true)
  await wrapper.get('[data-testid="peripheral-GPIOB.12"]').setValue(false)
  await flushPromises()
  fail = true
  await wrapper.get('[data-testid="peripheral-GPIOB.12"]').setValue(true)
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('Cannot sample')
  expect((wrapper.get('[data-testid="peripheral-GPIOB.12"]').element as HTMLInputElement).checked).toBe(false)
  await wrapper.setProps({ deviceConnected: false })
  expect(wrapper.find('[data-testid="peripheral-GPIOB.12"]').exists()).toBe(false)
  expect(fetchMock.mock.calls.every(([url]) => !url.includes('/symbols/'))).toBe(true)
  wrapper.unmount()
})

it('offers SVDs directly after typing a different chip without choosing a suggestion', async () => {
  vi.useFakeTimers()
  const old = { id: 'old', target: 'APM32F072VB', pack: 'Geehy.DFP@1', svd: 'SVD/APM32F072.svd' }
  const next = { id: 'next', target: 'STM32F103C8', pack: 'Keil.DFP@2', svd: 'SVD/STM32F103xx.svd' }
  const alternate = { ...next, id: 'alternate', pack: 'Keil.DFP@3' }
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    let data: object = {}
    if (url.includes('/targets')) data = { targets: url.endsWith('STM32F103C8') ? [next, alternate] : url.endsWith('missing') ? [] : [old] }
    else if (url.endsWith('/select')) {
      expect(JSON.parse(String(options?.body))).toEqual({ target_id: 'alternate' })
      data = { selection: alternate, items: [] }
    } else if (url.endsWith('/peripherals')) data = { selection: old, items: [] }
    return { ok: true, json: async () => data }
  })
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(PeripheralWatchPanel, { props: { deviceConnected: true, latestValues: {} } })
  await flushPromises()
  const input = wrapper.get('[data-testid="peripheral-chip-search"]')
  await input.trigger('focus')
  await input.trigger('keydown', { key: 'Enter' })
  await input.setValue('STM32F103C8')
  expect(wrapper.get('[data-testid="peripheral-svd"]').findAll('option')).toHaveLength(1)
  await vi.advanceTimersByTimeAsync(160)
  await flushPromises()
  // Leaving the combobox for the select must not discard its results.
  await input.trigger('focusout')
  await vi.advanceTimersByTimeAsync(1)
  const select = wrapper.get('[data-testid="peripheral-svd"]')
  expect(select.findAll('option')).toHaveLength(3)
  expect(select.text()).toContain('STM32F103xx.svd')
  expect(wrapper.get('[data-testid="peripheral-source"]').text()).toContain('APM32F072VB')
  await select.setValue('alternate')
  await wrapper.get('[data-testid="peripheral-load"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[data-testid="peripheral-source"]').text()).toContain('STM32F103C8')
  await input.setValue('missing')
  await vi.advanceTimersByTimeAsync(160)
  await flushPromises()
  expect(wrapper.find('[data-testid="peripheral-no-match"]').exists()).toBe(true)
  expect((wrapper.get('[data-testid="peripheral-load"]').element as HTMLButtonElement).disabled).toBe(true)
  wrapper.unmount()
})

it('ignores an old chip response arriving after a newer search', async () => {
  vi.useFakeTimers()
  let resolveOld!: (value: any) => void
  const newer = { id: 'new', target: 'STM32F103RE', pack: 'Keil@1', svd: 'F103.svd' }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('q=old')) return new Promise(resolve => { resolveOld = resolve })
    return { ok: true, json: async () => ({ targets: url.endsWith('q=new') ? [newer] : [] }) }
  }))
  const wrapper = mount(PeripheralWatchPanel, { props: { deviceConnected: false, latestValues: {} } })
  await flushPromises()
  const input = wrapper.get('[data-testid="peripheral-chip-search"]')
  await input.setValue('old')
  await vi.advanceTimersByTimeAsync(160)
  await input.setValue('new')
  await vi.advanceTimersByTimeAsync(160)
  await flushPromises()
  resolveOld({ ok: true, json: async () => ({ targets: [{ ...newer, id: 'old', target: 'OLD' }] }) })
  await flushPromises()
  expect(wrapper.get('[data-testid="peripheral-svd"]').text()).toContain('STM32F103RE')
  expect(wrapper.get('[data-testid="peripheral-svd"]').text()).not.toContain('OLD')
  wrapper.unmount()
})
