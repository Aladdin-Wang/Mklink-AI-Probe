import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MemoryTab from './MemoryTab.vue'

const api = vi.hoisted(() => ({ readMemory: vi.fn(), writeMemory: vi.fn() }))
vi.mock('../../composables/useDashboard', () => ({ useDeviceApi: () => api }))
vi.mock('../../composables/useToast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../composables/useDashboardSetup', () => ({ useDashboardSetup: () => ({ connecting: false, quickConnect: vi.fn() }) }))

describe('Memory write destination', () => {
  it('preserves an unaligned write address through automatic and manual read-back', async () => {
    api.readMemory.mockResolvedValue({ address: '0x20001000', data_hex: '00010203' })
    api.writeMemory.mockResolvedValue({})
    const wrapper = mount(MemoryTab, { props: { deviceConnected: true } })
    await wrapper.get('.mem-controls button').trigger('click')
    await flushPromises()
    const inputs = wrapper.findAll('.mem-write input')
    expect(inputs[0].element.value).toBe('0x20001000')
    await inputs[0].setValue('0x20001001')
    await inputs[1].setValue('A1B2C3')
    await wrapper.get('.mem-write button').trigger('click')
    await flushPromises()
    expect(inputs[0].element.value).toBe('0x20001001')
    await wrapper.get('.mem-controls button').trigger('click')
    await flushPromises()
    await inputs[1].setValue('010203')
    await wrapper.get('.mem-write button').trigger('click')
    await flushPromises()
    expect(api.writeMemory.mock.calls).toEqual([
      ['0x20001001', 'A1B2C3'], ['0x20001001', '010203'],
    ])
    wrapper.unmount()
  })
})
