import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import HardFaultTab from './HardFaultTab.vue'

const apiMock = vi.hoisted(() => ({ getHardfaultDetail: vi.fn() }))

vi.mock('../../composables/useDashboard', () => ({
  useDeviceApi: () => apiMock,
}))

vi.mock('../../composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

describe('HardFaultTab', () => {
  beforeEach(() => {
    apiMock.getHardfaultDetail.mockResolvedValue({
      fault: true,
      summary: 'FORCED',
      fault_function: 'afe_inject_hardfault',
      fault_location: 'applications/afe_task.c:118',
      exception_stack: {
        pointer: 'psp', pointer_address: 0x20001000, frame_address: 0x20001024,
        frame_offset: 36, exc_return: 0xfffffffD, handler_lr: 0x08005231,
        extended_frame: false,
      },
      call_stack: [
        { index: 0, address: 0x0800c120, lookup_address: 0x0800c120, function: 'afe_inject_hardfault', location: 'applications/afe_task.c:118', source: 'exception_pc', confidence: 'exact' },
        { index: 1, address: 0x0800c1b1, lookup_address: 0x0800c1ae, function: 'afe_thread_entry', location: 'applications/afe_task.c:180', source: 'exception_lr', confidence: 'high' },
      ],
    })
  })

  it('shows the faulting function and resolved call stack', async () => {
    const wrapper = mount(HardFaultTab, { props: { deviceConnected: true } })

    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="fault-focus"]').text()).toContain('afe_inject_hardfault')
    expect(wrapper.get('[data-testid="fault-focus"]').text()).toContain('afe_task.c:118')
    expect(wrapper.get('[data-testid="hardfault-call-stack"]').text()).toContain('afe_thread_entry')
    expect(wrapper.get('[data-testid="hardfault-call-stack"]').text()).toContain('异常 PC · 精确')
    expect(wrapper.text()).toContain('PSP 0x20001000')
    wrapper.unmount()
  })
})
