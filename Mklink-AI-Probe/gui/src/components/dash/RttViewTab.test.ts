import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, shallowRef } from 'vue'
import { nextTick } from 'vue'
import RttViewTab from './RttViewTab.vue'

const mocks = vi.hoisted(() => ({
  useBinaryStream: vi.fn(),
  binary: {
    rttLines: null as any,
    waveformBatch: null as any,
    envelope: null as any,
    telemetry: null as any,
    state: null as any,
    error: null as any,
    start: vi.fn(), stop: vi.fn(), reset: vi.fn(), configure: vi.fn(),
    requestVisibleRange: vi.fn(),
  },
  dash: {
    state: null as any, error: null as any,
    start: vi.fn(), stop: vi.fn(), pause: vi.fn(), resume: vi.fn(),
  },
  checkConflict: vi.fn(),
}))

vi.mock('../../composables/useBinaryStream', () => ({ useBinaryStream: mocks.useBinaryStream }))
vi.mock('../../composables/useDashboard', () => ({ useDashboard: () => mocks.dash }))
vi.mock('../../composables/useEventSource', () => ({
  useEventSource: () => { throw new Error('RTT high-rate SSE must not be constructed') },
}))
vi.mock('../../composables/useResourceStatus', () => ({
  useResourceStatus: () => ({ checkConflict: mocks.checkConflict }),
}))
vi.mock('../../lib/stream/renderScheduler', () => ({
  RenderScheduler: class { start() {} invalidate() {} recordCollection() {} dispose() {} },
}))

describe('RttViewTab binary migration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.binary.rttLines = shallowRef(null)
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.dash.state = ref('idle')
    mocks.dash.error = ref(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    mocks.checkConflict.mockResolvedValue([])
    mocks.dash.start.mockResolvedValue(undefined)
    mocks.dash.stop.mockResolvedValue(undefined)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ running: false }) }))
  })

  it('uses RTT binary transport and a bounded virtual log without EventSource', () => {
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    expect(mocks.useBinaryStream).toHaveBeenCalledWith('rtt', expect.any(Object))
    expect(wrapper.findComponent({ name: 'VirtualLogPanel' }).exists()).toBe(true)
    wrapper.unmount()
  })

  it('starts and stops the binary lifecycle with dashboard controls', async () => {
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    await wrapper.get('.btn-primary').trigger('click')
    await Promise.resolve()
    expect(mocks.binary.reset).toHaveBeenCalled()
    expect(mocks.binary.start).toHaveBeenCalled()
    mocks.dash.state.value = 'running'
    await nextTick()
    await wrapper.get('.btn-danger').trigger('click')
    expect(mocks.binary.stop).toHaveBeenCalled()
    wrapper.unmount()
  })
})
