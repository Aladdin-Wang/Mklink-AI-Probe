import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, shallowRef } from 'vue'

const mocks = vi.hoisted(() => ({
  ensureLoaded: vi.fn(),
  reparse: vi.fn(),
  writeSymbol: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  stale: { value: false },
}))

const catalogItems = [
  {
    path: 'controller.enabled', address: 0x20000028, type_name: 'bool',
    scalar_kind: 'bool', size: 1, writable: true, enum_values: {}, parent_path: 'controller',
  },
  {
    path: 'controller.target', address: 0x20000024, type_name: 'float',
    scalar_kind: 'float', size: 4, writable: true, enum_values: {}, parent_path: 'controller',
  },
  {
    path: 'gain', address: 0x20000020, type_name: 'float',
    scalar_kind: 'float', size: 4, writable: true, enum_values: {}, parent_path: null,
  },
]

vi.mock('../../composables/useSymbolCatalog', () => ({
  useSymbolCatalog: () => ({
    items: shallowRef(catalogItems),
    generation: ref(1),
    stale: mocks.stale,
    loading: ref(false),
    reparsing: ref(false),
    ensureLoaded: mocks.ensureLoaded,
    reparse: mocks.reparse,
    writeSymbol: mocks.writeSymbol,
  }),
}))

vi.mock('../../composables/useToast', () => ({
  useToast: () => ({ error: mocks.toastError, success: mocks.toastSuccess }),
}))

import SymbolVariablePanel from './SymbolVariablePanel.vue'

function okJson(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('SymbolVariablePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.stale.value = false
    mocks.ensureLoaded.mockResolvedValue(undefined)
    mocks.reparse.mockResolvedValue({ preserved: ['gain'], updated: [], removed: [] })
    mocks.writeSymbol.mockResolvedValue({ path: 'gain', generation: 1, value: 1.3, verified: true })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okJson({ items: [{ name: 'gain' }] })))
  })

  it('shows catalog variables immediately and groups structure members', async () => {
    const wrapper = mount(SymbolVariablePanel, {
      props: { deviceConnected: true, latestValues: { gain: 1.25 } },
    })
    await flushPromises()

    expect(mocks.ensureLoaded).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('controller')
    expect(wrapper.text()).toContain('controller.target')
    expect(wrapper.get('[data-testid="latest-gain"]').text()).toContain('1.25')
  })

  it('adds and removes a selected variable through the SuperWatch API', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(okJson({ items: [{ name: 'gain' }] }))
      .mockResolvedValueOnce(okJson({ item: { name: 'controller.target' } }))
      .mockResolvedValueOnce(okJson({ item: { name: 'gain', removed: true } }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(SymbolVariablePanel, { props: { deviceConnected: true, latestValues: {} } })
    await flushPromises()

    await wrapper.get('[data-testid="toggle-controller.target"]').setValue(true)
    await flushPromises()
    await wrapper.get('[data-testid="toggle-gain"]').setValue(false)
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith('/api/dash/superwatch/add', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ name: 'controller.target' }),
    }))
    expect(fetchMock).toHaveBeenCalledWith('/api/dash/superwatch/remove', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ name: 'gain' }),
    }))
  })

  it('writes a float from the variable row and shows the verified value', async () => {
    const wrapper = mount(SymbolVariablePanel, {
      props: { deviceConnected: true, latestValues: { gain: 1.25 } },
    })
    await flushPromises()
    await wrapper.get('[data-testid="edit-gain"]').trigger('click')
    await wrapper.get('[data-testid="write-input-gain"]').setValue('1.3')
    await wrapper.get('[data-testid="write-gain"]').trigger('click')
    await flushPromises()

    expect(mocks.writeSymbol).toHaveBeenCalledWith('gain', 1.3)
    expect(wrapper.get('[data-testid="write-ok-gain"]').text()).toContain('1.3')
  })

  it('refuses writes while the AXF catalog is stale', async () => {
    mocks.stale.value = true
    const wrapper = mount(SymbolVariablePanel, {
      props: { deviceConnected: true, latestValues: { gain: 1.25 } },
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="edit-gain"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('AXF 已变化')
  })
})
