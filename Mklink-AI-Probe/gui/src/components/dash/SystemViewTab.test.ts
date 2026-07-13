import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SystemViewTab from './SystemViewTab.vue'

const mocks = vi.hoisted(() => ({
  dash: {
    state: { __v_isRef: true, value: 'idle' },
    error: { __v_isRef: true, value: null },
    getStatus: vi.fn(), start: vi.fn(), stop: vi.fn(),
    pause: vi.fn(), resume: vi.fn(),
  },
  status: {
    data: { __v_isRef: true, value: [] },
    connect: vi.fn(), disconnect: vi.fn(),
  },
  binary: {
    telemetry: { __v_isRef: true, value: null },
    systemViewVisible: { __v_isRef: true, value: null },
    start: vi.fn(), stop: vi.fn(), reset: vi.fn(), requestVisibleRange: vi.fn(),
  },
  checkConflict: vi.fn(),
}))

vi.mock('../../composables/useDashboard', () => ({ useDashboard: () => mocks.dash }))
vi.mock('../../composables/useEventSource', () => ({ useEventSource: () => mocks.status }))
vi.mock('../../composables/useBinaryStream', () => ({ useBinaryStream: () => mocks.binary }))
vi.mock('../../composables/useResourceStatus', () => ({
  useResourceStatus: () => ({ checkConflict: mocks.checkConflict }),
}))
vi.mock('../../lib/svTimeline', () => ({
  SvTimeline: class {
    setData() {}
    setPrefilteredIntervals() {}
    setWindowSize() {}
    reset() {}
    destroy() {}
  },
}))
vi.mock('../../lib/stream/renderScheduler', () => ({
  RenderScheduler: class {
    start() {}
    invalidate() {}
    recordCollection() {}
    dispose() {}
  },
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

describe('SystemViewTab asynchronous lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.dash.state.value = 'idle'
    mocks.status.data.value = []
    mocks.dash.stop.mockResolvedValue(undefined)
    mocks.checkConflict.mockResolvedValue([])
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
  })

  it('does not start either transport when getStatus resolves after unmount', async () => {
    const status = deferred<{ running: boolean }>()
    mocks.dash.getStatus.mockReturnValue(status.promise)
    const wrapper = mount(SystemViewTab, { props: { deviceConnected: true } })

    wrapper.unmount()
    status.resolve({ running: true })
    await flushPromises()

    expect(mocks.dash.start).not.toHaveBeenCalled()
    expect(mocks.status.connect).not.toHaveBeenCalled()
    expect(mocks.binary.start).not.toHaveBeenCalled()
  })

  it('does not connect when a running-trace start resolves after unmount', async () => {
    const started = deferred<void>()
    mocks.dash.getStatus.mockResolvedValue({ running: true })
    mocks.dash.start.mockReturnValue(started.promise)
    const wrapper = mount(SystemViewTab, { props: { deviceConnected: true } })
    await flushPromises()
    expect(mocks.dash.start).toHaveBeenCalledOnce()

    wrapper.unmount()
    started.resolve()
    await flushPromises()

    expect(mocks.status.connect).not.toHaveBeenCalled()
    expect(mocks.binary.start).not.toHaveBeenCalled()
  })

  it('does not arm delayed transports when a user start resolves after unmount', async () => {
    const started = deferred<void>()
    mocks.dash.getStatus.mockResolvedValue({ running: false })
    mocks.dash.start.mockReturnValue(started.promise)
    const wrapper = mount(SystemViewTab, { props: { deviceConnected: true } })
    await flushPromises()
    await wrapper.get('.btn-primary').trigger('click')
    await flushPromises()
    expect(mocks.dash.start).toHaveBeenCalledOnce()

    wrapper.unmount()
    started.resolve()
    await flushPromises()

    expect(mocks.status.connect).not.toHaveBeenCalled()
    expect(mocks.binary.start).not.toHaveBeenCalled()
  })
})
