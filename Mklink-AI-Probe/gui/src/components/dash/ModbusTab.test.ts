import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  listUartPorts: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}))

vi.mock('../../composables/useMklinkApi', () => ({
  useMklinkApi: () => ({ listUartPorts: mocks.listUartPorts }),
}))

vi.mock('../../composables/useToast', () => ({
  useToast: () => ({ error: mocks.toastError, success: vi.fn(), info: mocks.toastInfo }),
}))

import ModbusTab from './ModbusTab.vue'

describe('ModbusTab prerequisites', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('EventSource', class { close() {} })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      running: false,
      loop: { running: false, completed: 0, errors: 0 },
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })))
    mocks.listUartPorts.mockResolvedValue([{
      device: 'SERIAL_PORT', description: 'Virtual serial', manufacturer: 'test', vid: null, pid: null,
    }])
  })

  it('shows serial controls without an MKLink Device prerequisite', async () => {
    const wrapper = mount(ModbusTab)
    await flushPromises()

    expect(wrapper.text()).not.toContain('请先连接设备')
    expect(wrapper.find('select').element.value).toBe('SERIAL_PORT')
    expect(wrapper.findAll('button').some(button => button.text() === '连接')).toBe(true)
  })

  it('surfaces the backend serial-port conflict instead of entering running state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
      detail: { conflict: 'user:dashboard:serial', resource: 'serial_port' },
    }), {
      status: 409,
      headers: { 'Content-Type': 'application/json' },
    }))))
    const wrapper = mount(ModbusTab)
    await flushPromises()

    await wrapper.findAll('button').find(button => button.text() === '连接')!.trigger('click')
    await flushPromises()

    expect(mocks.toastError).toHaveBeenCalledWith(expect.stringContaining('user:dashboard:serial'))
    expect(wrapper.findAll('button').some(button => button.text() === '连接')).toBe(true)
  })
  it('keeps stop pending visible and permits retry after a failed disconnect', async () => {
    let stopping = false
    const fetch = vi.fn(async (url: string) => {
      if (url.endsWith('/stop')) {
        stopping = true
        return new Response(JSON.stringify({ detail: 'worker still active' }), { status: 409 })
      }
      return new Response(JSON.stringify({ running: !stopping, stopping, loop: { running: false } }))
    })
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(ModbusTab)
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '断开连接')!.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith(expect.stringContaining('worker still active'))
    expect(mocks.toastInfo).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('等待停止')
    expect(wrapper.findAll('button').some(button => button.text() === '连接')).toBe(false)
    expect(wrapper.find('.send-button').attributes('disabled')).toBeDefined()
    expect(wrapper.find('select').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').find(button => button.text() === '断开连接')!.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('does not claim the loop stopped when the backend times out', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/loop/stop')
      ? new Response(JSON.stringify({ detail: 'loop still active' }), { status: 409 })
      : new Response(JSON.stringify({ running: true, loop: { running: true, completed: 1, errors: 0 } }))))
    const wrapper = mount(ModbusTab)
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '停止循环')!.trigger('click')
    await flushPromises()
    expect(mocks.toastError).toHaveBeenCalledWith(expect.stringContaining('loop still active'))
    expect(wrapper.findAll('button').some(button => button.text() === '停止循环')).toBe(true)
    wrapper.unmount()
  })

  it('restores the backend connection instead of showing this browser saved selection', async () => {
    mocks.listUartPorts.mockResolvedValue([{ device: 'UART_BACKEND', description: '' }])
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ running: true,
      slave: 7, connection: { port: 'UART_BACKEND', baudrate: 57600, bytesize: 8, parity: 'E',
        stopbits: 2, timeout: 1, retries: 0, local_echo: false }, loop: { running: false } }))))
    const wrapper = mount(ModbusTab)
    await flushPromises()
    expect(wrapper.find('.connection-summary').text()).toContain('UART_BACKEND')
    expect(wrapper.find('.connection-summary').text()).toContain('57600')
    expect(wrapper.find('.connection-summary').text()).toContain('8E2')
    wrapper.unmount()
  })

})
