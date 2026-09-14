import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DeviceConfigurationPanel from './DeviceConfigurationPanel.vue'

const props = { partNumber: 'HPM5301', model: 'V4', unlockBeforeDownload: false, lockAfterDownload: false }
const description = { kind: 'otp', read_supported: true, reason: '只读', fields: [
  { id: 'USB_VID', label: 'USB VID', description: '厂商标识', bit_width: 16, current: null, shadow: null },
] }
const response = (data: unknown, ok = true) => ({ ok, json: async () => data })
afterEach(() => vi.unstubAllGlobals())

describe('DeviceConfigurationPanel', () => {
  it('edits reversible fields, clears changes to preserve, and displays ARM shadows', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ kind: 'option_bytes', read_supported: true,
      shadow_supported: true, reason: 'STM32F103', fields: [
        { id: 'RDP', current: 'unprotected', shadow: null },
        { id: 'DATA0', current: 255, shadow: 90, bit_width: 8, writable: true },
        { id: 'WDG_SW', current: 1, shadow: 1, bit_width: 1, writable: true },
      ] })))
    const wrapper = mount(DeviceConfigurationPanel, { props: { ...props, partNumber: 'STM32F103xE',
      hasFirmware: false, changes: { DATA0: '0x5A' } } })
    await flushPromises()
    expect(wrapper.text()).toContain('0x5A')
    expect(wrapper.get('[data-testid="configuration-plan"]').text()).toContain('写入选项字节')
    expect(wrapper.get('[data-testid="configuration-plan"]').text()).not.toContain('烧录固件')
    expect(wrapper.find('[aria-label="RDP"]').exists()).toBe(false)
    await wrapper.get('[aria-label="WDG_SW"]').setValue('1')
    expect(wrapper.emitted('update:changes')?.at(-1)).toEqual([{ DATA0: '0x5A', WDG_SW: '1' }])
    await wrapper.get('[aria-label="DATA0"]').setValue('')
    expect(wrapper.emitted('update:changes')?.at(-1)).toEqual([{}])
    wrapper.unmount()
  })
  it('loads descriptions without reading hardware and keeps fuse and shadow distinct', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response(description)).mockResolvedValueOnce(response({
      ...description, read_at: '2026-09-11T00:00:00Z', fields: [{ ...description.fields[0], current: 0x1234, shadow: 0x5678 }],
    }))
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(DeviceConfigurationPanel, { props })
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[0]![1].method).toBe('GET')
    await wrapper.get('[data-testid="configuration-read"]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls[1]![1].method).toBe('POST')
    expect(wrapper.text()).toContain('0x1234')
    expect(wrapper.text()).toContain('0x5678')
    expect(wrapper.get('[data-testid="configuration-timestamp"]').text()).toContain('2026-09-11')
    expect(wrapper.findAll('input')).toHaveLength(0)
    wrapper.unmount()
  })

  it('discards stale reads when changing chip and reports failures without showing zero', async () => {
    let finish!: (value: unknown) => void
    const fetch = vi.fn().mockResolvedValueOnce(response(description))
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      .mockResolvedValueOnce(response({ ...description, fields: [], read_supported: false }))
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(DeviceConfigurationPanel, { props })
    await flushPromises()
    await wrapper.get('button').trigger('click')
    await wrapper.setProps({ partNumber: 'HPM6200' })
    finish(response({ ...description, fields: [{ ...description.fields[0], current: 0x1234, shadow: 0x5678 }] }))
    await flushPromises()
    expect(wrapper.text()).not.toContain('0x1234')
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('clears the last snapshot on read failure and shows the pending ARM actions separately', async () => {
    const snapshot = { ...description, kind: 'option_bytes', read_at: 'old', fields: [{ ...description.fields[0], id: 'RDP', current: 'unprotected' }] }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(snapshot))
      .mockResolvedValueOnce(response({ detail: 'Device not connected' }, false)))
    const wrapper = mount(DeviceConfigurationPanel, { props: { ...props, partNumber: 'STM32F103C8', unlockBeforeDownload: true, lockAfterDownload: true } })
    await flushPromises()
    expect(wrapper.get('[data-testid="configuration-plan"]').text()).toContain('解锁并擦除 → 烧录固件 → 加锁')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Device not connected')
    expect(wrapper.find('[data-testid="configuration-timestamp"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('未保护')
    wrapper.unmount()
  })
})
