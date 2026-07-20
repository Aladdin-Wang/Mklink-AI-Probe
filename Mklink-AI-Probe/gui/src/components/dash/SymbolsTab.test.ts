import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, shallowRef } from 'vue'

const mocks = vi.hoisted(() => ({
  ensureLoaded: vi.fn(),
  refreshStatus: vi.fn(),
  reparse: vi.fn(),
  typeinfo: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('../../composables/useSymbolCatalog', () => ({
  useSymbolCatalog: () => ({
    items: shallowRef([
      {
        path: 'controller.target', address: 0x20000024, type_name: 'float',
        scalar_kind: 'float', size: 4, writable: true, enum_values: {}, parent_path: 'controller',
      },
      {
        path: 'gain', address: 0x20000020, type_name: 'float',
        scalar_kind: 'float', size: 4, writable: true, enum_values: {}, parent_path: null,
      },
    ]),
    generation: ref(1),
    stale: ref(false),
    truncatedRoots: shallowRef(['controller']),
    loading: ref(false),
    reparsing: ref(false),
    error: ref(null),
    ensureLoaded: mocks.ensureLoaded,
    refreshStatus: mocks.refreshStatus,
    reparse: mocks.reparse,
  }),
}))

vi.mock('../../composables/useDashboard', () => ({
  useSymbolsApi: () => ({ typeinfo: mocks.typeinfo }),
}))

vi.mock('../../composables/useToast', () => ({
  useToast: () => ({ error: mocks.toastError, success: vi.fn() }),
}))

import SymbolsTab from './SymbolsTab.vue'

describe('SymbolsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.ensureLoaded.mockResolvedValue(undefined)
    mocks.typeinfo.mockResolvedValue({
      name: 'gain', found: true, type: 'float', size: 4, address: 0x20000020,
    })
  })

  it('shows valid catalog variables immediately when opened', async () => {
    const wrapper = mount(SymbolsTab, { props: { deviceConnected: true } })
    await flushPromises()

    expect(mocks.ensureLoaded).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('controller.target')
    expect(wrapper.text()).toContain('gain')
    expect(wrapper.text()).toContain('controller')
    expect(wrapper.text()).toContain('前 256 个')
  })

  it('filters the loaded catalog locally', async () => {
    const wrapper = mount(SymbolsTab, { props: { deviceConnected: true } })
    await wrapper.get('[data-testid="symbol-search"]').setValue('target')

    expect(wrapper.text()).toContain('controller.target')
    expect(wrapper.text()).not.toContain('gain')
    expect(mocks.ensureLoaded).toHaveBeenCalledOnce()
  })

  it('loads type details when a catalog row is selected', async () => {
    const wrapper = mount(SymbolsTab, { props: { deviceConnected: true } })
    await wrapper.get('[data-symbol="gain"]').trigger('click')
    await flushPromises()

    expect(mocks.typeinfo).toHaveBeenCalledWith('gain')
    expect(wrapper.text()).toContain('0x20000020')
  })
})
