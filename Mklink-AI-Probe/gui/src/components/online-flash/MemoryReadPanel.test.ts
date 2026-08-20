import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MemoryReadPanel from './MemoryReadPanel.vue'

describe('MemoryReadPanel', () => {
  it('explains that HPM reads are unavailable', () => {
    const wrapper = mount(MemoryReadPanel, {
      props: {
        probeId: 'probe', targetPart: 'HPM5300', hpm: true,
        frequency: 1_000_000, connectMode: 'halt', resetMode: 'default',
      },
    })
    expect(wrapper.text()).toContain('HPM ROM API')
    expect(wrapper.find('[data-testid="memory-read-submit"]').exists()).toBe(false)
  })

  it('prompts for a range, reads it in chunks, then saves the returned BIN', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(new Uint8Array([1, 2, 3, 4]), {
      status: 200,
      headers: { 'Content-Type': 'application/octet-stream' },
    }))
    vi.stubGlobal('fetch', fetch)
    const click = vi.fn()
    const remove = vi.fn()
    const createElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation(tag => tag === 'a'
      ? ({ href: '', download: '', style: {}, click, remove } as unknown as HTMLAnchorElement)
      : createElement(tag))
    vi.spyOn(document.body, 'appendChild').mockImplementation(node => node)
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() })

    const wrapper = mount(MemoryReadPanel, {
      props: {
        probeId: 'probe', targetPart: 'STM32F103C8', hpm: false,
        frequency: 1_000_000, connectMode: 'halt', resetMode: 'default',
      },
    })
    await wrapper.get('[data-testid="memory-read-submit"]').trigger('click')
    await wrapper.get('[data-testid="memory-read-address"]').setValue('0x1000')
    await wrapper.get('[data-testid="memory-read-end-address"]').setValue('0x1004')
    await wrapper.get('[data-testid="memory-read-confirm"]').trigger('click')
    await flushPromises()

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/online-flash/memory/read'),
      expect.objectContaining({ method: 'POST' }),
    )
    expect(click).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="memory-read-progress"]').text()).toContain('100%')
    await wrapper.get('[data-testid="memory-read-save"]').trigger('click')
    expect(click).toHaveBeenCalledOnce()
    wrapper.unmount()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('uses the target sector size for each read request', async () => {
    const fetch = vi.fn().mockImplementation(async (_url: string, options: RequestInit) => {
      const size = Number((JSON.parse(String(options.body)) as { size: number }).size)
      return new Response(new Uint8Array(size), {
        status: 200,
        headers: { 'Content-Type': 'application/octet-stream' },
      })
    })
    vi.stubGlobal('fetch', fetch)

    const wrapper = mount(MemoryReadPanel, {
      props: {
        probeId: 'probe', targetPart: 'STM32F103C8', hpm: false,
        frequency: 1_000_000, connectMode: 'halt', resetMode: 'default',
        memoryRegions: [{ name: 'flash', start: 0x1000, length: 0x1000, sector_size: 0x800 }],
      },
    })
    await wrapper.get('[data-testid="memory-read-submit"]').trigger('click')
    await wrapper.get('[data-testid="memory-read-address"]').setValue('0x1000')
    await wrapper.get('[data-testid="memory-read-end-address"]').setValue('0x2000')
    expect(wrapper.text()).toContain('按目标 Flash 扇区分块（2048 字节）')
    await wrapper.get('[data-testid="memory-read-confirm"]').trigger('click')
    await flushPromises()

    expect(fetch).toHaveBeenCalledOnce()
    const payload = JSON.parse(String(fetch.mock.calls[0]?.[1].body)) as { size: number; chunk_sizes: number[] }
    expect(payload.size).toBe(0x1000)
    expect(payload.chunk_sizes).toEqual([0x800, 0x800])
    expect(wrapper.get('[data-testid="memory-read-log"]').text()).toContain('2048 Bytes')
    wrapper.unmount()
    vi.unstubAllGlobals()
  })
})
