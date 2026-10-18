import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import SuperWatchRecording from './SuperWatchRecording.vue'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })
it('uses one toggle, never starts recording on mount, and stops an existing recording', async () => {
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn() })
  const request = vi.fn(async (url: string) => ({ ok: true, json: async () => ({
    active: !url.endsWith('/stop'), state: url.endsWith('/stop') ? 'completed' : 'recording', samples: 3,
  }) }))
  vi.stubGlobal('fetch', request)
  const wrapper = mount(SuperWatchRecording)
  try {
    await flushPromises()
    expect(request.mock.calls.map(call => call[0])).toEqual([expect.stringContaining('/recording/status')])
    expect(wrapper.findAll('[data-testid=sw-record-toggle]')).toHaveLength(1)
    expect(wrapper.get('[data-testid=sw-record-toggle]').text()).toMatch(/停止记录|Stop recording/)
    await wrapper.get('[data-testid=sw-record-toggle]').trigger('click'); await flushPromises()
    expect(request.mock.calls.at(-1)![0]).toContain('/recording/stop')
    expect(wrapper.get('[data-testid=sw-record-toggle]').text()).toMatch(/开始记录|Start recording/)
  } finally { wrapper.unmount() }
})
