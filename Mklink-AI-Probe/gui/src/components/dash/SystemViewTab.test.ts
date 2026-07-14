import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref, shallowRef } from 'vue'
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
  scheduler: {
    start: vi.fn(), stop: vi.fn(), invalidate: vi.fn(),
    recordCollection: vi.fn(), dispose: vi.fn(),
  },
  timeline: {
    construct: vi.fn(),
    pauseRendering: vi.fn(), resumeRendering: vi.fn(),
    setPrefilteredIntervals: vi.fn(),
  },
  importLog: vi.fn(),
}))

vi.mock('../../composables/useDashboard', () => ({ useDashboard: () => mocks.dash }))
vi.mock('../../composables/useEventSource', () => ({ useEventSource: () => mocks.status }))
vi.mock('../../composables/useBinaryStream', () => ({ useBinaryStream: () => mocks.binary }))
vi.mock('../../composables/useResourceStatus', () => ({
  useResourceStatus: () => ({ checkConflict: mocks.checkConflict }),
}))
vi.mock('../../lib/svTimeline', () => ({
  SvTimeline: class {
    constructor(_roots: unknown, data: unknown) { mocks.timeline.construct(data) }
    setData() {}
    setTickOrigin() {}
    setPrefilteredIntervals = mocks.timeline.setPrefilteredIntervals
    setWindowSize() {}
    pauseRendering = mocks.timeline.pauseRendering
    resumeRendering = mocks.timeline.resumeRendering
    reset() {}
    destroy() {}
  },
}))
vi.mock('../../lib/stream/renderScheduler', () => ({
  RenderScheduler: class {
    start = mocks.scheduler.start
    stop = mocks.scheduler.stop
    invalidate = mocks.scheduler.invalidate
    recordCollection = mocks.scheduler.recordCollection
    dispose = mocks.scheduler.dispose
  },
}))
vi.mock('../../lib/systemViewImport', () => ({
  importSystemViewJsonl: mocks.importLog,
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

describe('SystemViewTab asynchronous lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.dash.state = ref('idle') as typeof mocks.dash.state
    mocks.dash.error = ref(null) as typeof mocks.dash.error
    mocks.status.data = shallowRef([]) as typeof mocks.status.data
    mocks.binary.telemetry = shallowRef(null) as typeof mocks.binary.telemetry
    mocks.binary.systemViewVisible = shallowRef(null) as typeof mocks.binary.systemViewVisible
    mocks.dash.stop.mockResolvedValue(undefined)
    mocks.checkConflict.mockResolvedValue([])
    mocks.importLog.mockResolvedValue({ events: 0, skipped: 0, parseErrors: 0 })
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

  it('pauses only timeline rendering while Worker acquisition remains active', async () => {
    mocks.dash.getStatus.mockResolvedValue({ running: false })
    const wrapper = mount(SystemViewTab, { props: { deviceConnected: true } })
    await flushPromises()
    mocks.dash.state.value = 'running'
    await nextTick()

    await wrapper.get('.control-toolbar .btn:not(.btn-danger)').trigger('click')
    expect(mocks.scheduler.stop).toHaveBeenCalled()
    expect(mocks.timeline.pauseRendering).toHaveBeenCalled()
    expect(mocks.dash.pause).not.toHaveBeenCalled()
    expect(mocks.binary.stop).not.toHaveBeenCalled()
    publishVisibleEvent(72_000_000)
    await nextTick()
    expect(mocks.timeline.setPrefilteredIntervals).not.toHaveBeenCalled()

    await wrapper.get('.control-toolbar .btn-primary').trigger('click')
    expect(mocks.scheduler.start).toHaveBeenCalledTimes(2)
    expect(mocks.scheduler.invalidate).toHaveBeenCalledWith('data')
    expect(mocks.timeline.resumeRendering).toHaveBeenCalled()
    expect(mocks.dash.resume).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('constructs a replacement timeline already paused when the CPU clock changes', async () => {
    mocks.dash.getStatus.mockResolvedValue({ running: false })
    const wrapper = mount(SystemViewTab, { props: { deviceConnected: true } })
    await flushPromises()
    mocks.dash.state.value = 'running'
    await nextTick()

    await wrapper.get('.control-toolbar .btn:not(.btn-danger)').trigger('click')
    publishVisibleEvent(72_000_000)
    await nextTick()

    expect(mocks.timeline.construct).toHaveBeenLastCalledWith(
      expect.objectContaining({ renderPaused: true }),
    )
    wrapper.unmount()
  })

  it('clears the timeline pause across stop and start lifecycle resets', async () => {
    mocks.dash.getStatus.mockResolvedValue({ running: false })
    const wrapper = mount(SystemViewTab, { props: { deviceConnected: true } })
    await flushPromises()
    mocks.dash.state.value = 'running'
    await nextTick()

    await wrapper.get('.control-toolbar .btn:not(.btn-danger)').trigger('click')
    await wrapper.get('.control-toolbar .btn-danger').trigger('click')
    await flushPromises()
    expect(mocks.timeline.resumeRendering).toHaveBeenCalledTimes(1)
    expect(mocks.scheduler.start).toHaveBeenCalledTimes(2)

    mocks.dash.state.value = 'idle'
    await nextTick()
    await wrapper.get('.control-toolbar .btn-primary').trigger('click')
    await flushPromises()
    expect(mocks.timeline.resumeRendering).toHaveBeenCalledTimes(2)
    expect(mocks.scheduler.start).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })

  it('resumes rendering before importing an offline log from a paused trace', async () => {
    mocks.dash.getStatus.mockResolvedValue({ running: false })
    const wrapper = mount(SystemViewTab, { props: { deviceConnected: true } })
    await flushPromises()
    mocks.dash.state.value = 'running'
    await nextTick()

    await wrapper.get('.control-toolbar .btn:not(.btn-danger)').trigger('click')
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File([''], 'trace.jsonl', { type: 'application/x-ndjson' })],
    })
    await input.trigger('change')
    await flushPromises()

    expect(mocks.timeline.resumeRendering).toHaveBeenCalled()
    expect(mocks.scheduler.start).toHaveBeenCalledTimes(2)
    expect(mocks.scheduler.invalidate).toHaveBeenCalledWith('data')
    wrapper.unmount()
  })
})

function publishVisibleEvent(cpuFreq: number) {
  mocks.status.data.value = cpuFreq > 0 ? [{ _streamSeq: 1, cpu_freq: cpuFreq }] as never[] : []
  mocks.binary.systemViewVisible.value = {
    type: 'systemview-visible',
    requestId: 0,
    intervalCount: 0,
    candidateIntervalCount: 0,
    eventCount: 1,
    latestTime: 1,
    tickOrigin: 9007199254740992n,
    taskIds: new Uint32Array().buffer,
    starts: new Float64Array().buffer,
    ends: new Float64Array().buffer,
    startTicks: new BigUint64Array().buffer,
    endTicks: new BigUint64Array().buffer,
    events: [{
      kind: 'task_start_exec',
      task_id: 1,
      t_ticks: 9007199254740993n,
      t_ticks_exact: '9007199254740993',
      t_relative: 1,
    }],
  } as never
}

describe('SystemViewTab event time units', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.dash.state = ref('idle') as typeof mocks.dash.state
    mocks.dash.error = ref(null) as typeof mocks.dash.error
    mocks.status.data = shallowRef([]) as typeof mocks.status.data
    mocks.binary.telemetry = shallowRef(null) as typeof mocks.binary.telemetry
    mocks.binary.systemViewVisible = shallowRef(null) as typeof mocks.binary.systemViewVisible
    mocks.dash.getStatus.mockResolvedValue({ running: false })
    mocks.dash.stop.mockResolvedValue(undefined)
    mocks.checkConflict.mockResolvedValue([])
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
  })

  it('shows formatted seconds when CPU frequency is known', async () => {
    const wrapper = mount(SystemViewTab, { props: { deviceConnected: true } })
    publishVisibleEvent(1_000_000)
    await nextTick()

    expect(wrapper.find('.sv-events-table tbody tr td:nth-child(2)').text()).toBe('0.000001s')
    wrapper.unmount()
  })

  it('shows the exact tick string when CPU frequency is unknown', async () => {
    const wrapper = mount(SystemViewTab, { props: { deviceConnected: true } })
    publishVisibleEvent(0)
    await nextTick()

    expect(wrapper.find('.sv-events-table tbody tr td:nth-child(2)').text().replaceAll(',', ''))
      .toBe('9007199254740993 tk')
    wrapper.unmount()
  })
})
