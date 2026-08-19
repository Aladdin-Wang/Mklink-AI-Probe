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

  it('reads a range and downloads the returned BIN', async () => {
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
    await flushPromises()

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/online-flash/memory/read'),
      expect.objectContaining({ method: 'POST' }),
    )
    expect(click).toHaveBeenCalledOnce()
    wrapper.unmount()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })
})
