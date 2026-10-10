import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import SuperWatchTab from './SuperWatchTab.vue'
import SymbolVariablePanel from './SymbolVariablePanel.vue'
import WaveformViewer from './WaveformViewer.vue'
import { DESKTOP_SETTINGS_STORAGE_KEY } from '../../lib/desktopSettings'

describe('SuperWatchTab', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ profile: 'medium' }) })))
  })
  afterEach(() => vi.unstubAllGlobals())
  it('ignores obsolete hidden-pane preferences while retaining the useful layout settings', async () => {
    vi.stubGlobal('localStorage', { getItem: (key: string) => key === DESKTOP_SETTINGS_STORAGE_KEY + '.superwatch-layout'
      ? JSON.stringify({ panelWidth: 420, hideSettings: true, hideCatalog: true }) : null, setItem: vi.fn() })
    const wrapper = mount(SuperWatchTab, {
      props: { deviceConnected: false },
      global: { stubs: { SymbolVariablePanel: true, PeripheralWatchPanel: true, WaveformViewer: true } },
    })
    expect(wrapper.get('.superwatch-workspace').classes()).not.toContain('compact')
    expect(wrapper.get('.superwatch-workspace').classes()).not.toContain('catalog-hidden')
    expect(wrapper.get('.superwatch-workspace').attributes('style')).toContain('420px')
    expect(wrapper.get('.workspace-actions').findAll('button')).toHaveLength(1)
    expect(wrapper.get('#superwatch-speed').isVisible()).toBe(true)
    wrapper.unmount()
  })
  it.each([
    [{ busy: ['superwatch'] }, '请先停止采集，再应用调试速率'],
    [{ message: 'Target is busy debugging' }, 'Target is busy debugging'],
  ])('explains a rejected speed change without stopping shared capture', async (detail, message) => {
    const fetchMock = vi.fn(async (_url: any, init?: RequestInit) => ({
      ok: !init, statusText: 'Conflict',
      json: async () => init ? { detail } : { profile: 'medium' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(SuperWatchTab, {
      props: { deviceConnected: true },
      global: { stubs: { SymbolVariablePanel: true, PeripheralWatchPanel: true, WaveformViewer: true } },
    })
    try {
      await flushPromises()
      await wrapper.get('[data-testid="superwatch-speed"]').setValue('ultra')
      await wrapper.get('[data-testid="apply-superwatch-speed"]').trigger('click')
      await flushPromises()
      expect(wrapper.get('[role="status"]').text()).toContain(message)
      expect(wrapper.get<HTMLSelectElement>('#superwatch-speed').element.value).toBe('ultra')
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/stop'))).toBe(false)
    } finally { wrapper.unmount() }
  })
  it('follows external clock changes but preserves an unapplied user choice', async () => {
    vi.useFakeTimers()
    let profile = 'medium'
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ profile }) })))
    const wrapper = mount(SuperWatchTab, {
      props: { deviceConnected: true },
      global: { stubs: { SymbolVariablePanel: true, PeripheralWatchPanel: true, WaveformViewer: true } },
    })
    await flushPromises()
    profile = 'ultra'
    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper.get<HTMLSelectElement>('#superwatch-speed').element.value).toBe('ultra')
    await wrapper.get('#superwatch-speed').setValue('high')
    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper.get<HTMLSelectElement>('#superwatch-speed').element.value).toBe('high')
    wrapper.unmount()
    vi.useRealTimers()
  })
  it('restores ultra while retaining high as the existing 20 MHz choice', async () => {
    const fetchMock = vi.fn(async (_url: any, init?: RequestInit) => ({
      ok: true, json: async () => init ? { clock_hz: 30000000 } : { profile: 'ultra' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(SuperWatchTab, {
      props: { deviceConnected: true },
      global: { stubs: { SymbolVariablePanel: true, PeripheralWatchPanel: true, WaveformViewer: true } },
    })
    await flushPromises()
    const select = wrapper.get<HTMLSelectElement>('[data-testid="superwatch-speed"]')
    expect(select.element.value).toBe('ultra')
    expect(select.findAll('option').map(option => option.attributes('value'))).toEqual(['low', 'medium', 'high', 'ultra'])
    expect(select.get('option[value="high"]').text()).toContain('20 MHz')
    await wrapper.get('[data-testid="apply-superwatch-speed"]').trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/device/debug-speed'), expect.objectContaining({
      method: 'POST', body: JSON.stringify({ profile: 'ultra' }),
    }))
    wrapper.unmount()
    vi.unstubAllGlobals()
  })
  it('defaults to medium and applies the selected memory sampling clock', async () => {
    const fetchMock = vi.fn(async (_url: any, init?: RequestInit) => ({
      ok: true, json: async () => init ? { clock_hz: 20000000 } : { profile: 'medium' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(SuperWatchTab, {
      props: { deviceConnected: true },
      global: { stubs: { SymbolVariablePanel: true, PeripheralWatchPanel: true, WaveformViewer: true } },
    })
    await flushPromises()
    expect(wrapper.get<HTMLSelectElement>('[data-testid="superwatch-speed"]').element.value).toBe('medium')
    await wrapper.get('[data-testid="superwatch-speed"]').setValue('high')
    await wrapper.get('[data-testid="apply-superwatch-speed"]').trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/device/debug-speed'), expect.objectContaining({
      method: 'POST', body: JSON.stringify({ profile: 'high' }),
    }))
    expect(wrapper.get('[role="status"]').text()).toBe('')
    wrapper.unmount()
    vi.unstubAllGlobals()
  })
  it('shares waveform values and channel visibility between both workspace panes', async () => {
    const wrapper = mount(SuperWatchTab, {
      props: { deviceConnected: true },
      global: {
        stubs: {
          PeripheralWatchPanel: true,
          SymbolVariablePanel: {
            name: 'SymbolVariablePanel',
            emits: ['visibility-change', 'selection-removed', 'snapshot-change'],
            props: ['deviceConnected', 'latestValues', 'hiddenChannels'],
            template: '<aside class="variable-panel-stub" />',
          },
          WaveformViewer: {
            name: 'WaveformViewer',
            emits: ['latest-values'],
            props: ['mode', 'deviceConnected', 'hiddenChannels', 'arraySnapshotPath'],
            template: '<main class="waveform-stub" />',
          },
        },
      },
    })

    expect(wrapper.get('.superwatch-workspace').exists()).toBe(true)
    wrapper.findComponent(WaveformViewer).vm.$emit('latest-values', { gain: 1.25 })
    await nextTick()

    expect(wrapper.findComponent(SymbolVariablePanel).props('latestValues')).toEqual({ gain: 1.25 })

    wrapper.findComponent(SymbolVariablePanel).vm.$emit('visibility-change', 'gain', false)
    await nextTick()
    expect(wrapper.findComponent(SymbolVariablePanel).props('hiddenChannels')).toEqual(new Set(['gain']))
    expect(wrapper.findComponent(WaveformViewer).props('hiddenChannels')).toEqual(new Set(['gain']))
    expect(wrapper.findComponent(WaveformViewer).props('arraySnapshotPath')).toBe(null)
    wrapper.findComponent(SymbolVariablePanel).vm.$emit('snapshot-change', 'samples')
    await nextTick()
    expect(wrapper.findComponent(WaveformViewer).props('arraySnapshotPath')).toBe('samples')

    wrapper.findComponent(SymbolVariablePanel).vm.$emit('selection-removed', 'gain')
    await nextTick()
    expect(wrapper.findComponent(SymbolVariablePanel).props('hiddenChannels')).toEqual(new Set())
    expect(wrapper.findComponent(WaveformViewer).props('hiddenChannels')).toEqual(new Set())
  })
})
