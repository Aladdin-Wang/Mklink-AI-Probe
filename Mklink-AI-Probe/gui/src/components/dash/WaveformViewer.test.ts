import fs from 'node:fs'
import path from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, shallowRef } from 'vue'
import WaveformViewer from './WaveformViewer.vue'
import { StreamType } from '../../lib/stream/protocol'
import { StreamDecoder, type WorkerOutput } from '../../workers/streamDecoder.worker'

const mocks = vi.hoisted(() => ({
  useBinaryStream: vi.fn(),
  binary: {
    waveformBatch: null as ReturnType<typeof shallowRef<unknown>> | null,
    envelope: null as ReturnType<typeof shallowRef<unknown>> | null,
    telemetry: null as ReturnType<typeof shallowRef<unknown>> | null,
    state: null as ReturnType<typeof shallowRef<unknown>> | null,
    error: null as ReturnType<typeof shallowRef<unknown>> | null,
    superwatchMetadata: null as ReturnType<typeof shallowRef<unknown>> | null,
    start: vi.fn(), stop: vi.fn(), reset: vi.fn(), configure: vi.fn(),
    requestVisibleRange: vi.fn(),
  },
  schedulerInstances: [] as Array<{
    start: ReturnType<typeof vi.fn>
    invalidate: ReturnType<typeof vi.fn>
    recordCollection: ReturnType<typeof vi.fn>
    dispose: ReturnType<typeof vi.fn>
    render: () => void
  }>,
}))

const viewerSource = fs.readFileSync(
  path.resolve(process.cwd(), 'src/assets/rtt_viewer.js'), 'utf8',
)
const i18nSource = fs.readFileSync(
  path.resolve(process.cwd(), 'src/assets/rtt_i18n.js'), 'utf8',
)
const componentSource = fs.readFileSync(
  path.resolve(process.cwd(), 'src/components/dash/WaveformViewer.vue'), 'utf8',
)
const viewerCss = fs.readFileSync(
  path.resolve(process.cwd(), 'src/assets/rtt_viewer.css'), 'utf8',
).replaceAll('\r\n', '\n')

function waveformFrame(
  sequence: bigint, itemCount: number, timestampNs: bigint, payload: Float32Array,
): ArrayBuffer {
  const buffer = new ArrayBuffer(36 + payload.byteLength)
  const bytes = new Uint8Array(buffer)
  const view = new DataView(buffer)
  bytes.set([0x4d, 0x4b, 0x53, 0x54])
  view.setUint8(4, 1)
  view.setUint8(5, StreamType.WAVEFORM)
  view.setUint8(6, 1)
  view.setUint8(7, 36)
  view.setUint32(8, StreamType.WAVEFORM, true)
  view.setBigUint64(12, sequence, true)
  view.setBigUint64(20, timestampNs, true)
  view.setUint32(28, itemCount, true)
  view.setUint32(32, payload.byteLength, true)
  bytes.set(new Uint8Array(payload.buffer, payload.byteOffset, payload.byteLength), 36)
  return buffer
}

function superwatchFrame(
  sequence: bigint, itemCount: number, timestampNs: bigint,
  payload: Uint8Array, flags: 1 | 2,
): ArrayBuffer {
  const buffer = new ArrayBuffer(36 + payload.byteLength)
  const bytes = new Uint8Array(buffer)
  const view = new DataView(buffer)
  bytes.set([0x4d, 0x4b, 0x53, 0x54])
  view.setUint8(4, 1)
  view.setUint8(5, StreamType.SUPERWATCH)
  view.setUint8(6, flags)
  view.setUint8(7, 36)
  view.setUint32(8, StreamType.SUPERWATCH, true)
  view.setBigUint64(12, sequence, true)
  view.setBigUint64(20, timestampNs, true)
  view.setUint32(28, itemCount, true)
  view.setUint32(32, payload.byteLength, true)
  bytes.set(payload, 36)
  return buffer
}

function canvasContext(): CanvasRenderingContext2D {
  const noop = () => undefined
  const gradient = { addColorStop: noop }
  const visitPoint = () => { (window as any).__canvasPointVisits++ }
  return new Proxy({} as CanvasRenderingContext2D, {
    get(target, property) {
      if (property === 'fillRect' || property === 'stroke') return (...args: unknown[]) => { (window as any).__canvasDraws?.push({op:property,color:property==='stroke'?target.strokeStyle:target.fillStyle,args}) }
      if (property === 'measureText') return () => ({ width: 10 })
      if (property === 'createLinearGradient') return () => gradient
      if (property === 'fillText') {
        return (value: unknown) => { (window as any).__canvasLabels?.push(String(value)) }
      }
      if (property === 'moveTo' || property === 'lineTo') {
        return visitPoint
      }
      if (!(property in target)) return noop
      return target[property as keyof CanvasRenderingContext2D]
    },
    set(target, property, value) {
      ;(target as any)[property] = value
      return true
    },
  })
}

function wheelEvent(init: WheelEventInit) {
  const event = new WheelEvent('wheel', init)
  if (init.clientX !== undefined) {
    Object.defineProperty(event, 'clientX', { value: init.clientX })
  }
  if (init.clientY !== undefined) {
    Object.defineProperty(event, 'clientY', { value: init.clientY })
  }
  if (init.shiftKey !== undefined) {
    Object.defineProperty(event, 'shiftKey', { value: init.shiftKey })
  }
  return event
}

async function loadRttViewerRuntime(
  mode: 'VOFA' | 'SuperWatch' = 'VOFA', capacity = 4,
) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, json: async () => ({ running: false, channels: [] }),
  }))
  // These are DOM substitutes, not assertions: recording every call retains
  // thousands of contexts/rectangles during the sustained render gate.
  const restore: Array<() => void> = []
  function replaceProperty(target: object, name: string, descriptor: PropertyDescriptor) {
    const original = Object.getOwnPropertyDescriptor(target, name)
    Object.defineProperty(target, name, { configurable: true, ...descriptor })
    restore.push(() => {
      if (original) Object.defineProperty(target, name, original)
      else Reflect.deleteProperty(target, name)
    })
  }
  const context = canvasContext()
  replaceProperty(HTMLCanvasElement.prototype, 'getContext', { value: () => context })
  replaceProperty(HTMLElement.prototype, 'getBoundingClientRect', {
    value: function(this: HTMLElement) {
      if (this.id === 'y-axis-hit') {
        return {
          x: 0, y: 8, width: 64, height: 360, top: 8, right: 64,
          bottom: 368, left: 0, toJSON: () => ({}),
        }
      }
      return {
        x: 0, y: 0, width: 800, height: 400, top: 0, right: 800,
        bottom: 400, left: 0, toJSON: () => ({}),
      }
    },
  })
  replaceProperty(HTMLCanvasElement.prototype, 'clientWidth', { get: () => 800 })
  replaceProperty(HTMLCanvasElement.prototype, 'clientHeight', { get: () => 400 })
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('EventSource', class {
    static CLOSED = 2
    readyState = 1
    close() {}
  })
  vi.stubGlobal('t', (key: string) => key)
  ;(globalThis as any).CONFIG = {
    maxPoints: capacity, title: 'test', mode, lang: 'en', deviceConnected: true,
  }
  ;(window as any).__ringToArrayCalls = 0
  ;(window as any).__ringPointVisits = 0
  ;(window as any).__canvasPointVisits = 0
  ;(window as any).__watchTableUpdates = 0
  ;(window as any).__canvasLabels = []
  const wrapper = mount(WaveformViewer, { props: { mode, deviceConnected: true } })
  await new Promise(resolve => setTimeout(resolve, 0))
  const host = wrapper.element
  host.querySelectorAll('script[src]').forEach(script => script.remove())
  document.body.appendChild(host)
  const instrumented = viewerSource.replace(
    'RingBuffer.prototype.toArray = function() {',
    'RingBuffer.prototype.toArray = function() { window.__ringToArrayCalls++;',
  ).replace(
    'RingBuffer.prototype.timeAt = function(logicalIndex) {',
    'RingBuffer.prototype.timeAt = function(logicalIndex) { window.__ringPointVisits++;',
  ).replace(
    'RingBuffer.prototype.valueAt = function(logicalIndex) {',
    'RingBuffer.prototype.valueAt = function(logicalIndex) { window.__ringPointVisits++;',
  ).replace(
    'function updateWatchTable() {',
    'function updateWatchTable() { window.__watchTableUpdates++;',
  ) + `
window.__rttTestProbe = {
  timeGrid: timeGrid,
  fields: function() { return FIELDS; },
  metadata: function() { return CHANNEL_METADATA; },
  binary: function() { return {
    names: binaryChannelNames.slice(), timeOrigin: binaryTimeOrigin,
    lastTimestamp: binaryLastTimestamp, lastSequence: binaryLastSequence
  }; },
  trigger: triggerSettings,
  cursor: cursorState,
  applyMetadata: applyChannelMetadata,
  appendRawLog: appendRawLogLine,
  setRawLogOpen: setRawLogOpen,
  rawLogState: function() { return {
    count: rawLogStoredCount, total: rawLogLineCount, lines: rawLogSnapshot()
  }; },
  saveRawLog: saveRawLog,
  exportCSV: exportCSV,
  syncStatus: syncDashboardStatus,
  collectionState: function() { return {
    state: collectionState, paused: paused, renderPaused: renderPaused
  }; },
  currentInterval: function() { return currentInterval; },
  RingBuffer: RingBuffer,
  hover: hoverProbe,
  channelYState: function() { return channelYState; },
  globalYView: function() { return globalYView; },
  sharedYRange: function() { return getSharedYRange(); },
  splitChannel: function() { return splitChannelName; },
  panelLayout: function() { return chartPanelLayout; },
  panelYRange: function(panel) { return getPanelYRange(panel); },
  setSplitChannel: setSplitChannel,
  clearSplitChannel: clearSplitChannel,
  setArraySnapshot: setArraySnapshot,
  setBufferCapacity: setBufferCapacity,
  serializeState: serializeState,
  deserializeState: deserializeState,
  timeline: function() { return timelineView; },
  fullTimeRange: function() { return getFullTimeRange(); },
  visibleTimeRange: function() { return getVisibleTimeRange(); },
  binaryEnvelope: function() { return binaryEnvelope; },
  addSuperwatchName: superwatchAddName
};`
  new Function(instrumented).call(window)
  return {
    wrapper,
    viewer: (window as any).__waveformViewers[mode] as any,
    probe: (window as any).__rttTestProbe as any,
    cleanup() {
      wrapper.unmount()
      host.remove()
      restore.reverse().forEach(restoreProperty => restoreProperty())
    },
  }
}

vi.mock('../../composables/useBinaryStream', () => ({
  useBinaryStream: mocks.useBinaryStream,
}))
vi.mock('../../lib/stream/renderScheduler', () => ({
  RenderScheduler: class {
    start = vi.fn()
    invalidate = vi.fn()
    recordCollection = vi.fn()
    dispose = vi.fn()
    render: () => void
    constructor(render: () => void) {
      this.render = render
      mocks.schedulerInstances.push(this)
    }
  },
}))

beforeEach(() => {
  vi.clearAllMocks()
  mocks.schedulerInstances.length = 0
  mocks.binary.waveformBatch = shallowRef(null)
  mocks.binary.envelope = shallowRef(null)
  mocks.binary.telemetry = shallowRef(null)
  mocks.binary.state = shallowRef({ phase: 'stopped' })
  mocks.binary.error = shallowRef(null)
  mocks.binary.superwatchMetadata = shallowRef(null)
  mocks.useBinaryStream.mockReturnValue(mocks.binary)
  ;(window as any).__waveformViewers = {}
})

describe('WaveformViewer VOFA binary transport', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        running: true,
        channels: [
          { name: 'id', addr: 0x20000000, type: 'uint32_t', size: 4 },
          { name: 'value', addr: 0x20000004, type: 'float', size: 4 },
        ],
      }),
    }))
  })

  it('enables the binary stream only for VOFA and disposes its 30 FPS scheduler', async () => {
    const wrapper = mount(WaveformViewer, { props: { mode: 'VOFA', deviceConnected: true } })
    await new Promise(resolve => setTimeout(resolve, 0))

    expect(mocks.useBinaryStream).toHaveBeenCalledWith('vofa', expect.any(Object))
    expect(mocks.binary.configure).toHaveBeenCalledWith(2)
    expect(mocks.binary.start).toHaveBeenCalledOnce()
    expect(mocks.schedulerInstances[0].start).toHaveBeenCalledOnce()

    wrapper.unmount()
    expect(mocks.binary.stop).toHaveBeenCalledOnce()
    expect(mocks.schedulerInstances[0].dispose).toHaveBeenCalledOnce()
  })

  it('migrates SuperWatch to its binary stream and shared scheduler', async () => {
    const wrapper = mount(WaveformViewer, {
      props: { mode: 'SuperWatch', deviceConnected: true },
    })
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(mocks.useBinaryStream).toHaveBeenCalledWith('superwatch', expect.any(Object))
    expect(mocks.binary.start).toHaveBeenCalledOnce()
    expect(mocks.binary.configure).not.toHaveBeenCalled()
    expect(mocks.schedulerInstances[0].start).toHaveBeenCalledOnce()
    wrapper.unmount()
    expect(mocks.binary.stop).toHaveBeenCalledOnce()
  })

  it('emits only the latest complete SuperWatch sample for the variable directory', async () => {
    const wrapper = mount(WaveformViewer, {
      props: { mode: 'SuperWatch', deviceConnected: true },
    })
    await new Promise(resolve => setTimeout(resolve, 0))

    if (!mocks.binary.superwatchMetadata || !mocks.binary.waveformBatch) {
      throw new Error('missing SuperWatch refs')
    }
    mocks.binary.superwatchMetadata.value = {
      type: 'superwatch-metadata',
      version: 1,
      channels: [{ name: 'gain' }, { name: 'controller.target' }],
    }
    await nextTick()
    mocks.binary.waveformBatch.value = {
      type: 'waveform-batch', sequence: 1n, timestampNs: 1_000_000n,
      itemCount: 2, channelCount: 2, layout: 'sample-major-float32',
      values: Float32Array.of(1, 10, 1.25, 20).buffer,
      times: Float64Array.of(0, 1).buffer,
    }
    await nextTick()

    expect(wrapper.emitted('latest-values')?.at(-1)).toEqual([{
      gain: 1.25,
      'controller.target': 20,
    }])
    wrapper.unmount()
  })

  it('treats an array snapshot as a normal SuperWatch channel', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'gain' }])
      runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 1_000_000_000n, itemCount: 2, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(2, 3).buffer,
        times: Float64Array.of(1, 2).buffer,
      })
      expect(runtime.probe.setArraySnapshot({
        name: 'samples', type_name: 'uint16_t', element_size: 2,
        start_index: 4, count: 3, sequence: 8, values: [1, 5, 2],
      })).toBe(true)
      expect(runtime.probe.fields().samples.isArraySnapshot).toBe(true)
      expect(runtime.probe.fields().samples.arrayValues).toEqual([1, 5, 2])
      expect(runtime.probe.setSplitChannel('samples')).toBe(true)
      expect(runtime.probe.splitChannel()).toBe('samples')
      runtime.probe.clearSplitChannel()
      runtime.probe.setArraySnapshot(null)
      expect(runtime.probe.fields().samples).toBeUndefined()
    } finally {
      runtime.cleanup()
    }
  })

  it('anchors readable time divisions while panning and adapts units on zoom', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      const grid = runtime.probe.timeGrid(2.5945, 2.6678, 800)
      expect(grid.division).toBe('10 ms/div')
      const major = grid.ticks.filter((t: any) => t.major)
      expect(major.map((t: any) => grid.label(t.time))).toEqual(['2600','2610','2620','2630','2640','2650','2660'])
      const pan = runtime.probe.timeGrid(2.5955, 2.6688, 800)
      expect(pan.ticks.filter((t: any) => t.major).map((t: any) => t.time)).toEqual(major.map((t: any) => t.time))
      expect(runtime.probe.timeGrid(0, 0.000073, 800).division).toBe('10 μs/div')
      expect(runtime.probe.timeGrid(0, 73, 800).division).toBe('10 s/div')
      expect(runtime.probe.timeGrid(0, 0, 800)).toBeNull()
      expect(runtime.probe.timeGrid(0, Infinity, 800)).toBeNull()
      expect(runtime.probe.timeGrid(0, 73, 100000).ticks.length).toBeLessThanOrEqual(100)
      expect(runtime.probe.timeGrid(-0.03, 0.04, 800).label(0)).toBe('0')
    } finally { runtime.cleanup() }
  })

  it('labels a standalone array snapshot by index and counts its elements', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      ;(window as any).__canvasLabels = []
      runtime.probe.setArraySnapshot({
        name: 'samples', type_name: 'float', element_size: 4,
        start_index: 4, sequence: 1, values: [1, 5, 2, 3, 4, 6],
      })
      const labels = (window as any).__canvasLabels
      expect(labels).toContain('index')
      expect(labels).toContain('4')
      expect(labels).toContain('9')
      expect(labels).not.toContain('time (ms)')
      expect(document.getElementById('pts-count')?.textContent).toBe('6 pts')
    } finally {
      runtime.cleanup()
    }
  })

  it('keeps SuperWatch subscribed after stop so another GUI can restart it', async () => {
    const resetBinaryStream = vi.fn()
    ;(window as any).__waveformViewers.SuperWatch = { resetBinaryStream }
    const wrapper = mount(WaveformViewer, {
      props: { mode: 'SuperWatch', deviceConnected: true },
    })
    await new Promise(resolve => setTimeout(resolve, 0))
    mocks.binary.reset.mockClear()
    ;(window as any).__waveformViewers.SuperWatch = { resetBinaryStream }

    window.dispatchEvent(new CustomEvent('mklink:vofa-stream-state', { detail: 'stopped' }))

    expect(mocks.binary.stop).not.toHaveBeenCalled()
    expect(mocks.binary.reset).not.toHaveBeenCalled()
    expect(resetBinaryStream).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('reconnects SuperWatch after the running-boundary reset to replay metadata', async () => {
    const wrapper = mount(WaveformViewer, {
      props: { mode: 'SuperWatch', deviceConnected: true },
    })
    await new Promise(resolve => setTimeout(resolve, 0))
    mocks.binary.start.mockClear()
    mocks.binary.stop.mockClear()
    mocks.binary.reset.mockClear()

    window.dispatchEvent(new CustomEvent('mklink:vofa-stream-state', { detail: 'running' }))

    expect(mocks.binary.stop).toHaveBeenCalledOnce()
    expect(mocks.binary.reset).toHaveBeenCalledOnce()
    expect(mocks.binary.start).toHaveBeenCalledOnce()
    expect(mocks.binary.stop.mock.invocationCallOrder[0])
      .toBeLessThan(mocks.binary.reset.mock.invocationCallOrder[0])
    expect(mocks.binary.reset.mock.invocationCallOrder[0])
      .toBeLessThan(mocks.binary.start.mock.invocationCallOrder[0])
    wrapper.unmount()
  })

  it.each(['VOFA', 'SuperWatch'] as const)(
    'clears %s data on start but preserves the last curve on stop',
    async mode => {
      const runtime = await loadRttViewerRuntime(mode)
      const states: string[] = []
      const onState = (event: Event) => states.push(String((event as CustomEvent).detail))
      window.addEventListener('mklink:vofa-stream-state', onState)
      vi.stubGlobal('confirm', () => true)
      try {
        runtime.viewer.configureBinaryChannels([{ name: 'A' }])
        expect(runtime.viewer.acceptBinaryBatch({
          sequence: 10n, timestampNs: 1_000_000_000n, itemCount: 1, channelCount: 1,
          layout: 'sample-major-float32', values: Float32Array.of(9).buffer,
          times: Float64Array.of(1000).buffer,
        })).toBe(true)
        expect(runtime.probe.fields().A.ringBuf.count).toBe(1)
        mocks.binary.reset.mockClear()
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
          ok: true,
          json: async () => mode === 'VOFA'
            ? { status: 'running', channels: [{ name: 'A', addr: 0x20000000 }] }
            : { status: 'running', items: [{ name: 'A' }] },
        }))

        document.getElementById('btn-start')?.click()
        for (let turn = 0; turn < 6; turn++) await Promise.resolve()
        if (mode === 'VOFA') {
          const calls = vi.mocked(fetch).mock.calls
          const start = calls.find(([url]) => String(url).endsWith('/vofa/start'))
          expect(start).toBeDefined()
          expect(JSON.parse(String(start?.[1]?.body || '{}'))).not.toHaveProperty('channels')
        }
        expect(states).toEqual(['running'])
        expect(mocks.binary.reset).toHaveBeenCalledTimes(1)
        expect(Object.values(runtime.probe.fields()).every(
          (field: any) => field.ringBuf.count === 0,
        )).toBe(true)
        expect(runtime.probe.binary()).toMatchObject({
          timeOrigin: null, lastTimestamp: null, lastSequence: null,
        })

        runtime.viewer.configureBinaryChannels([{ name: 'A' }])
        expect(runtime.viewer.acceptBinaryBatch({
          sequence: 1n, timestampNs: 2_000_000_000n, itemCount: 1, channelCount: 1,
          layout: 'sample-major-float32', values: Float32Array.of(10).buffer,
          times: Float64Array.of(2000).buffer,
        })).toBe(true)
        document.getElementById('btn-stop')?.click()
        for (let turn = 0; turn < 6; turn++) await Promise.resolve()
        expect(states).toEqual(['running', 'stopped'])
        expect(mocks.binary.reset).toHaveBeenCalledTimes(1)
        expect(runtime.probe.fields().A.ringBuf.count).toBe(1)
      } finally {
        window.removeEventListener('mklink:vofa-stream-state', onState)
        runtime.cleanup()
      }
    },
  )

  it('preserves the previous interval and shows the API detail when an update fails', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      runtime.probe.syncStatus({ running: true, interval: 0.25, channels: [] })
      const fetchMock = vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({ detail: 'VOFA interval is invalid' }),
      })
      vi.stubGlobal('fetch', fetchMock)
      const input = document.getElementById('interval-input') as HTMLInputElement
      input.value = '0.5'
      document.getElementById('btn-apply-interval')?.click()
      for (let turn = 0; turn < 6; turn++) await Promise.resolve()

      expect(runtime.probe.currentInterval()).toBe(0.25)
      expect(document.getElementById('conn-status')?.textContent).toBe('VOFA interval is invalid')
      expect(document.getElementById('conn-status')?.className).toContain('badge-err')
    } finally {
      runtime.cleanup()
    }
  })

  it('follows a shared stop and restart after this window paused its display', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      await flushPromises()
      runtime.probe.syncStatus({ state: 'running' })
      document.getElementById('btn-pause')!.click()
      runtime.probe.syncStatus({ state: 'running' })
      expect(runtime.probe.collectionState().state).toBe('paused')
      runtime.probe.syncStatus({ state: 'stopped' })
      expect(runtime.probe.collectionState().state).toBe('stopped')
      runtime.probe.syncStatus({ state: 'running' })
      expect(runtime.probe.collectionState()).toMatchObject({ state: 'running', paused: false })
    } finally { runtime.cleanup() }
  })

  it('resumes a locally paused display without restarting shared acquisition', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      await flushPromises()
      runtime.probe.syncStatus({ state: 'running' })
      document.getElementById('btn-pause')!.click()
      const calls = vi.mocked(fetch).mock.calls.length
      document.getElementById('btn-start')!.click()
      expect(runtime.probe.collectionState()).toMatchObject({ state: 'running', paused: false })
      expect(vi.mocked(fetch).mock.calls.length).toBe(calls)
    } finally { runtime.cleanup() }
  })

  it('defaults SuperWatch to 1 ms and applies a new interval while running', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      const input = document.getElementById('interval-input') as HTMLInputElement
      const bufferInput = document.getElementById('buffer-input') as HTMLInputElement
      expect(bufferInput.value).toBe('50000')
      expect(bufferInput.min).toBe('50000')
      expect(bufferInput.max).toBe('1000000')
      expect(bufferInput.step).toBe('1')
      expect(input.value).toBe('0.001')
      expect(input.min).toBe('0.000001')
      expect(input.step).toBe('0.000001')
      expect(runtime.probe.currentInterval()).toBe(0.001)

      for (let turn = 0; turn < 6; turn++) await Promise.resolve()
      runtime.probe.syncStatus({ state: 'running', interval: 0.001, items: [] })
      expect(runtime.probe.collectionState().state).toBe('running')
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ interval: 0.000001 }),
      })
      vi.stubGlobal('fetch', fetchMock)
      input.focus()
      input.value = '0.000001'
      input.dispatchEvent(new Event('input', { bubbles: true }))
      input.blur()
      runtime.probe.syncStatus({ state: 'running', interval: 0.001, items: [] })
      expect(input.value).toBe('0.000001')
      document.getElementById('btn-apply-interval')?.click()
      for (let turn = 0; turn < 6; turn++) await Promise.resolve()

      expect(fetchMock).toHaveBeenCalledWith(
        '/api/dash/superwatch/interval',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ interval: 0.000001 }),
        }),
      )
      expect(runtime.probe.currentInterval()).toBe(0.000001)
      expect(input.value).toBe('0.000001')
      expect(runtime.probe.collectionState().state).toBe('running')
    } finally {
      runtime.cleanup()
    }
  })

  it('accepts integer point boundaries without truncating fractional or invalid input', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      const buffer = document.getElementById('buffer-input') as HTMLInputElement
      const pretrigger = document.getElementById('trigger-pretrig') as HTMLInputElement
      expect(buffer.checkValidity()).toBe(true)
      expect(pretrigger.checkValidity()).toBe(true)
      const alert = vi.fn()
      vi.stubGlobal('alert', alert)
      for (const value of ['', '2.5', '-1', '1000001']) {
        buffer.value = value
        document.getElementById('btn-apply-buffer')?.click()
        expect(alert).toHaveBeenCalled()
        alert.mockClear()
      }
      for (const value of ['10', '1001', '50000']) {
        pretrigger.value = value
        pretrigger.dispatchEvent(new Event('input'))
        expect(pretrigger.checkValidity()).toBe(true)
        expect(runtime.probe.trigger.preTriggerSamples).toBe(Number(value))
      }
      for (const value of ['', '9', '1000.5', '50001', '-1']) {
        pretrigger.value = value
        pretrigger.dispatchEvent(new Event('input'))
        expect(runtime.probe.trigger.preTriggerSamples).toBe(50000)
      }
      for (const value of [-1, 50001, 10.5, '1000', null]) {
        expect(runtime.probe.deserializeState({ channels: [], triggerSettings: { preTrigger: value } })).toBe(true)
        expect(runtime.probe.trigger.preTriggerSamples).toBe(1000)
      }
    } finally {
      runtime.cleanup()
    }
  })

  it('keeps displayed capacity until worker confirmation and rolls back rejected input', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      const requester = vi.fn().mockResolvedValue(undefined)
      runtime.viewer.setBinaryCapacityRequester(requester)
      for (let i = 0; i < 8; i++) await Promise.resolve()
      const previous = (window as any).MAX_POINTS
      const input = document.getElementById('buffer-input') as HTMLInputElement
      const button = document.getElementById('btn-apply-buffer') as HTMLButtonElement
      requester.mockRejectedValueOnce(new Error('allocation failed'))
      input.value = '2'
      button.click()
      expect(button.disabled).toBe(true)
      expect((window as any).MAX_POINTS).toBe(previous)
      await flushPromises()
      expect(button.disabled).toBe(false)
      expect(input.value).toBe(String(previous))
      expect(document.getElementById('conn-status')?.textContent).toBe('allocation failed')
      input.value = '2'
      button.click()
      for (let i = 0; i < 8; i++) await Promise.resolve()
      expect((window as any).MAX_POINTS).toBe(2)
    } finally { runtime.cleanup() }
  })

  it('preallocates all channels before requesting a Worker resize', async () => {
    const runtime = await loadRttViewerRuntime('VOFA', 8)
    const NativeArray = Float64Array
    let allocation: ReturnType<typeof vi.spyOn> | undefined
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      const requester = vi.fn().mockResolvedValue(undefined)
      runtime.viewer.setBinaryCapacityRequester(requester)
      for (let i = 0; i < 12; i++) await Promise.resolve()
      requester.mockClear()
      const fields = runtime.probe.fields()
      const a = fields.A.ringBuf, b = fields.B.ringBuf
      a.push(1, 11); b.push(1, 22)
      let count = 0
      allocation = vi.spyOn(globalThis, 'Float64Array').mockImplementation(function(length: number) {
        if (++count === 6) throw new Error('second channel allocation failed')
        return new NativeArray(length)
      } as any)
      expect(runtime.probe.setBufferCapacity(2)).toBe(false)
      expect(requester).not.toHaveBeenCalled()
      expect(fields.A.ringBuf).toBe(a)
      expect(fields.B.ringBuf).toBe(b)
      expect(a.latest()).toEqual({ t: 1, y: 11 })
      expect(b.latest()).toEqual({ t: 1, y: 22 })
      expect((window as any).MAX_POINTS).toBe(8)
      expect(document.getElementById('conn-status')?.textContent).toBe('second channel allocation failed')
    } finally { allocation?.mockRestore(); runtime.cleanup() }
  })

  it('includes samples arriving while a capacity acknowledgement is pending', async () => {
    const runtime = await loadRttViewerRuntime('VOFA', 8)
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      const requester = vi.fn().mockResolvedValue(undefined)
      runtime.viewer.setBinaryCapacityRequester(requester)
      for (let i = 0; i < 12; i++) await Promise.resolve()
      let acknowledge!: () => void
      requester.mockImplementationOnce(() => new Promise<void>(resolve => { acknowledge = resolve }))
      const fields = runtime.probe.fields()
      fields.A.ringBuf.push(1, 11); fields.B.ringBuf.push(1, 21)
      expect(runtime.probe.setBufferCapacity(2)).toBe(true)
      await Promise.resolve()
      fields.A.ringBuf.push(2, 12); fields.A.ringBuf.push(3, 13)
      fields.B.ringBuf.push(2, 22); fields.B.ringBuf.push(3, 23)
      acknowledge()
      for (let i = 0; i < 12; i++) await Promise.resolve()
      expect(fields.A.ringBuf.toArray()).toEqual([{ t: 2, y: 12 }, { t: 3, y: 13 }])
      expect(fields.B.ringBuf.toArray()).toEqual([{ t: 2, y: 22 }, { t: 3, y: 23 }])
      expect((window as any).MAX_POINTS).toBe(2)
    } finally { runtime.cleanup() }
  })

  it.each([false, true])('handles late-channel allocation failure with recovery failure=%s', async (failRecovery) => {
    const runtime = await loadRttViewerRuntime('VOFA', 8)
    let allocation: ReturnType<typeof vi.spyOn> | undefined
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      const requester = vi.fn().mockResolvedValue(undefined)
      runtime.viewer.setBinaryCapacityRequester(requester)
      for (let i = 0; i < 12; i++) await Promise.resolve()
      requester.mockClear()
      let acknowledge!: () => void
      requester.mockImplementationOnce(() => new Promise<void>(resolve => { acknowledge = resolve }))
      if (failRecovery) requester.mockRejectedValueOnce(new Error('worker unavailable'))
      runtime.probe.setBufferCapacity(2)
      await Promise.resolve()
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      const fields = runtime.probe.fields()
      const a = fields.A.ringBuf, b = fields.B.ringBuf
      allocation = vi.spyOn(globalThis, 'Float64Array').mockImplementationOnce(function() {
        throw new Error('late channel allocation failed')
      } as any)
      acknowledge()
      for (let i = 0; i < 20; i++) await Promise.resolve()
      allocation.mockRestore()
      expect(requester.mock.calls.map(call => call[0])).toEqual([2, 8])
      expect(fields.A.ringBuf).toBe(a)
      expect(fields.B.ringBuf).toBe(b)
      expect((window as any).MAX_POINTS).toBe(8)
      const button = document.getElementById('btn-apply-buffer') as HTMLButtonElement
      expect(button.disabled).toBe(failRecovery)
      expect(document.getElementById('conn-status')?.textContent).toContain(
        failRecovery ? 'Capacity recovery failed; reload this view' : 'late channel allocation failed',
      )
      if (failRecovery) expect(runtime.probe.setBufferCapacity(4)).toBe(false)
    } finally { allocation?.mockRestore(); runtime.cleanup() }
  })

  it('keeps the transport failure reason visible while backend status remains running', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      runtime.viewer.updateBinaryHealth({ phase: 'error', error: 'Capacity confirmation timed out; reload this view' })
      runtime.probe.syncStatus({ running: true, interval: .01, channels: [] })
      expect(document.getElementById('transport-state-badge')?.textContent).toContain('reload this view')
    } finally { runtime.cleanup() }
  })

  it('keeps a CDC acquisition failure visible while the view socket is connected', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.updateBinaryHealth({ phase: 'connected' })
      runtime.probe.syncStatus({ state: 'stopped', error: 'CDC queued read failed (WinError 31)' })
      runtime.viewer.setDeviceConnected(false)
      runtime.viewer.updateBinaryHealth({ phase: 'connected', error: null, bufferedSamples: 300 })
      const badge = document.getElementById('transport-state-badge')!
      expect(badge.textContent).toContain('CDC queued read failed')
      expect(badge.className).toContain('badge-err')
      runtime.probe.syncStatus({ state: 'running', error: null })
      expect(badge.className).toContain('badge-warn')
      runtime.viewer.setDeviceConnected(true)
      expect(badge.className).toContain('badge-ok')
      expect(badge.textContent).not.toContain('CDC queued read failed')
    } finally { runtime.cleanup() }
  })

  it('does not accumulate global listeners when resizing waveform history', async () => {
    const runtime = await loadRttViewerRuntime()
    const listener = vi.spyOn(window, 'addEventListener')
    try {
      for (let size = 10; size <= 100; size += 10) {
        expect(runtime.probe.setBufferCapacity(size)).toBe(true)
      }
      expect(listener.mock.calls.filter(([event]) => event === 'mklink-theme-change')).toHaveLength(0)
    } finally {
      listener.mockRestore()
      runtime.cleanup()
    }
  })

  it('estimates Worker history memory from the requested capacity and channel count', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 8)
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      const input = document.getElementById('buffer-input') as HTMLInputElement
      const estimate = document.getElementById('buffer-memory-estimate')!
      input.value = '1000000'
      input.dispatchEvent(new Event('input', { bubbles: true }))

      expect(estimate.textContent).toBe('~15 MB')
      expect(estimate.dataset.bytes).toBe(String(1_000_000 * (8 + 2 * 4)))
      expect(estimate.title).toContain('2 ch x 1000000 pts')
    } finally {
      runtime.cleanup()
    }
  })

  it('keeps the live time window unchanged when retained history capacity grows', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 8)
    try {
      runtime.probe.syncStatus({ state: 'running', interval: 0.25, actual_rate: 4, items: [] })
      runtime.viewer.configureBinaryChannels([{ name: 'signal' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 2_750_000_000n, itemCount: 8, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.from({ length: 8 }, (_, i) => i).buffer,
        times: Float64Array.from({ length: 8 }, (_, i) => 1000 + i * 250).buffer,
      })).toBe(true)
      const before = runtime.probe.visibleTimeRange()
      const beforeSpan = before.tMax - before.tMin
      expect(beforeSpan).toBeCloseTo(0.875, 12)

      expect(runtime.probe.setBufferCapacity(16)).toBe(true)
      const resized = runtime.probe.visibleTimeRange()
      expect(resized.tMax - resized.tMin).toBeCloseTo(beforeSpan, 12)
      expect(resized.tMax).toBeCloseTo(before.tMax, 12)

      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 2n, timestampNs: 4_750_000_000n, itemCount: 8, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.from({ length: 8 }, (_, i) => i + 8).buffer,
        times: Float64Array.from({ length: 8 }, (_, i) => 3000 + i * 250).buffer,
      })).toBe(true)
      const filled = runtime.probe.visibleTimeRange()
      expect(filled.tMax - filled.tMin).toBeCloseTo(beforeSpan, 12)
      expect(filled.tMax).toBeCloseTo(3.75, 12)

      document.getElementById('btn-pause')!.click()
      expect(runtime.probe.fullTimeRange()).toEqual({ tMin: 0, tMax: 3.75 })
      runtime.probe.timeline().offset = 0
      expect(runtime.probe.visibleTimeRange()).toEqual({ tMin: 0, tMax: 0.875 })
    } finally {
      runtime.cleanup()
    }
  })

  it('keeps live SuperWatch X zoom and pan at a fixed lag from the latest data', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 8)
    try {
      runtime.probe.syncStatus({ state: 'running', interval: 0.25, actual_rate: 4, items: [] })
      runtime.viewer.configureBinaryChannels([{ name: 'signal' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 2_750_000_000n, itemCount: 8, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.from({ length: 8 }, (_, i) => i).buffer,
        times: Float64Array.from({ length: 8 }, (_, i) => 1000 + i * 250).buffer,
      })).toBe(true)
      expect(runtime.probe.setBufferCapacity(16)).toBe(true)

      const axis = document.getElementById('x-axis-hit')!
      const minimap = document.getElementById('minimap-canvas')!
      const beforeRange = runtime.probe.visibleTimeRange()
      const beforeSpan = beforeRange.tMax - beforeRange.tMin

      axis.dispatchEvent(wheelEvent({ deltaY: -100, clientX: 400, bubbles: true }))
      const zoomed = runtime.probe.visibleTimeRange()
      expect(zoomed.tMax - zoomed.tMin).toBeLessThan(beforeSpan)
      expect(axis.classList.contains('is-live-locked')).toBe(false)
      expect(axis.title).toBe('x_axis_live_tip')

      axis.dispatchEvent(new MouseEvent('mousedown', { button: 0, clientX: 500, bubbles: true }))
      window.dispatchEvent(new MouseEvent('mousemove', { clientX: 700, bubbles: true }))
      window.dispatchEvent(new MouseEvent('mouseup', { clientX: 700, bubbles: true }))
      const lagged = runtime.probe.visibleTimeRange()
      const lag = runtime.probe.fullTimeRange().tMax - lagged.tMax
      const laggedSpan = lagged.tMax - lagged.tMin
      expect(lag).toBeGreaterThan(0)

      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 2n, timestampNs: 4_750_000_000n, itemCount: 8, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.from({ length: 8 }, (_, i) => i + 8).buffer,
        times: Float64Array.from({ length: 8 }, (_, i) => 3000 + i * 250).buffer,
      })).toBe(true)
      const advanced = runtime.probe.visibleTimeRange()
      expect(advanced.tMax - advanced.tMin).toBeCloseTo(laggedSpan, 12)
      expect(runtime.probe.fullTimeRange().tMax - advanced.tMax).toBeCloseTo(lag, 12)
      expect(advanced.tMax - lagged.tMax).toBeCloseTo(2, 12)

      minimap.dispatchEvent(new MouseEvent('click', { clientX: 40, bubbles: true }))
      expect(runtime.probe.visibleTimeRange().tMax).toBeLessThan(advanced.tMax)
    } finally {
      runtime.cleanup()
    }
  })

  it('does not invent empty history around a subsecond high-rate buffer after pause and restart', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 8)
    try {
      runtime.probe.syncStatus({ state: 'running', interval: 0.000001, actual_rate: 200000, items: [] })
      runtime.viewer.configureBinaryChannels([{ name: 'signal' }])
      runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 1_250_000_000n, itemCount: 8, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.from({ length: 8 }, (_, i) => i).buffer,
        times: Float64Array.from({ length: 8 }, (_, i) => 1000 + i * 250 / 7).buffer,
      })
      expect(runtime.viewer.acceptBinarySummary({
        sequence: 2n, timestampNs: 1_250_000_000n, collectedItemCount: 50000, bufferedItemCount: 50000,
        channelCount: 1, latestTimeMs: 1250, bufferStartMs: 1000, bufferEndMs: 1250,
        latestValues: Float32Array.of(7).buffer,
      })).toBe(true)
      expect(runtime.probe.fullTimeRange().tMax - runtime.probe.fullTimeRange().tMin).toBeCloseTo(.25)
      const requestFrozenRange = vi.fn()
      runtime.viewer.setBinaryVisibleRangeRequester(requestFrozenRange)
      const snapshotEnvelope = {
        type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
        requestId: 4, pixelWidth: 800, channelCount: 1, pointCount: 2,
        candidateSampleCount: 2, times: Float64Array.of(1050, 1250).buffer,
        timeIndices: Uint32Array.of(0, 1).buffer, values: Float32Array.of(1, 7).buffer,
        channelOffsets: Uint32Array.of(0, 2).buffer, frozenStartMs: 1050, frozenEndMs: 1300,
      }
      runtime.viewer.renderBinaryEnvelope(snapshotEnvelope)
      document.getElementById('btn-pause')!.click()
      runtime.viewer.renderBinaryEnvelope(snapshotEnvelope, true)
      expect(requestFrozenRange).toHaveBeenCalledOnce()
      expect(runtime.probe.fullTimeRange().tMin).toBeCloseTo(.05)
      expect(runtime.probe.fullTimeRange().tMax).toBeCloseTo(.30)
      runtime.viewer.renderBinaryEnvelope(snapshotEnvelope, true)
      expect(requestFrozenRange).toHaveBeenCalledOnce()
      const axis = document.getElementById('x-axis-hit')!
      for (let i = 0; i < 12; i++) axis.dispatchEvent(wheelEvent({ deltaY: 100, clientX: 400, bubbles: true }))
      const pausedRange = runtime.probe.visibleTimeRange()
      expect(pausedRange.tMax - pausedRange.tMin).toBeLessThanOrEqual(.250001)
      runtime.probe.syncStatus({ state: 'running', items: [] })
      document.getElementById('btn-start')!.click()
      await flushPromises()
      runtime.viewer.acceptBinarySummary({
        sequence: 3n, timestampNs: 1_550_000_000n, collectedItemCount: 50000, bufferedItemCount: 50000,
        channelCount: 1, latestTimeMs: 1550, bufferStartMs: 1300, bufferEndMs: 1550,
        latestValues: Float32Array.of(8).buffer,
      })
      const resumed = runtime.probe.visibleTimeRange()
      expect(resumed.tMax - resumed.tMin).toBeCloseTo(pausedRange.tMax - pausedRange.tMin)
      expect(resumed.tMin).toBeGreaterThanOrEqual(runtime.probe.fullTimeRange().tMin)
    } finally { runtime.cleanup() }
  })

  it('does not replace a user zoom when the first complete buffer establishes the default span', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 8)
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'signal' }])
      runtime.probe.syncStatus({ state: 'running', interval: .001 })
      runtime.probe.setBufferCapacity(16)
      const summary = (count: number) => runtime.viewer.acceptBinarySummary({
        sequence: BigInt(count), timestampNs: BigInt(count * 1000000000),
        collectedItemCount: count, bufferedItemCount: count,
        channelCount: 1, latestTimeMs: count * 1000, bufferStartMs: 1000, bufferEndMs: count * 1000,
        latestValues: Float32Array.of(1).buffer,
      })
      summary(8)
      document.getElementById('x-axis-hit')!.dispatchEvent(wheelEvent({ deltaY: -100, clientX: 400, bubbles: true }))
      const before = runtime.probe.visibleTimeRange()
      const span = before.tMax - before.tMin
      summary(16)
      const after = runtime.probe.visibleTimeRange()
      expect(after.tMax - after.tMin).toBeCloseTo(span, 6)
    } finally { runtime.cleanup() }
  })

  it('keeps a paused zoom span after a fresh acquisition grows beyond that span', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 50000)
    try {
      const channels = [{ name: 'signal', addr: 0x20000100, size: 4, type: 'uint32' }]
      runtime.viewer.configureBinaryChannels(channels)
      runtime.probe.syncStatus({ state: 'running', interval: .001 })
      const summary = (end: number) => runtime.viewer.acceptBinarySummary({
        sequence: BigInt(end), timestampNs: BigInt(end * 1000000),
        collectedItemCount: end, bufferedItemCount: end,
        channelCount: 1, latestTimeMs: end, bufferStartMs: 0, bufferEndMs: end,
        latestValues: Float32Array.of(1).buffer,
      }, channels)
      summary(18000)
      document.getElementById('btn-pause')!.click()
      const axis = document.getElementById('x-axis-hit')!
      for (let i = 0; i < 2; i++) axis.dispatchEvent(wheelEvent({ deltaY: -100, clientX: 400, bubbles: true }))
      const frozen = runtime.probe.visibleTimeRange()
      const span = frozen.tMax - frozen.tMin
      expect(span).toBeLessThan(9)
      document.getElementById('btn-start')!.click()
      await flushPromises()
      runtime.viewer.resetBinaryStream()
      runtime.viewer.configureBinaryChannels(channels)
      for (const end of [100, 9000, 24000]) {
        summary(end)
        const view = runtime.probe.visibleTimeRange()
        expect(view.tMax - view.tMin).toBeCloseTo(Math.min(end / 1000, span), 6)
        expect(view.tMax).toBeCloseTo(runtime.probe.fullTimeRange().tMax, 6)
      }
    } finally { runtime.cleanup() }
  })

  it('keeps the chosen X scale while restarting after stop with fresh data', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 8)
    try {
      runtime.probe.syncStatus({ state: 'running', interval: 0.25, actual_rate: 4, items: [] })
      runtime.viewer.configureBinaryChannels([{ name: 'signal' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 2_750_000_000n, itemCount: 8, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.from({ length: 8 }, (_, i) => i).buffer,
        times: Float64Array.from({ length: 8 }, (_, i) => 1000 + i * 250).buffer,
      })).toBe(true)
      expect(runtime.probe.setBufferCapacity(16)).toBe(true)

      runtime.probe.syncStatus({ state: 'stopped', items: [] })
      const axis = document.getElementById('x-axis-hit')!
      for (let i = 0; i < 8; i++) {
        axis.dispatchEvent(wheelEvent({ deltaY: 100, clientX: 400, bubbles: true }))
      }
      expect(runtime.probe.timeline()).toMatchObject({ zoom: 1, offset: 0 })
      expect(runtime.probe.fields().signal.ringBuf.count).toBe(8)
      const range = runtime.probe.visibleTimeRange()

      runtime.probe.syncStatus({ state: 'running', items: [] })
      const resumed = runtime.probe.visibleTimeRange()
      expect(resumed.tMax - resumed.tMin).toBeCloseTo(range.tMax - range.tMin, 12)
      expect(runtime.probe.timeline().offset).toBe(1)
      expect(runtime.probe.fields().signal.ringBuf.count).toBe(0)
      expect(runtime.probe.collectionState()).toMatchObject({
        state: 'running', paused: false, renderPaused: false,
      })
    } finally {
      runtime.cleanup()
    }
  })

  it('right-aligns SuperWatch samples in a fixed timeline while the ring buffer fills', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 8)
    try {
      expect(runtime.probe.timeline()).toMatchObject({ zoom: 2, offset: 1 })
      runtime.probe.syncStatus({ state: 'running', interval: 0.25 })
      runtime.viewer.configureBinaryChannels([{ name: 'signal' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 1_500_000_000n, itemCount: 3, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2, 3).buffer,
        times: Float64Array.of(1000, 1250, 1500).buffer,
      })).toBe(true)
      expect(runtime.probe.fullTimeRange()).toEqual({ tMin: -1.25, tMax: 0.5 })
      expect(runtime.probe.visibleTimeRange()).toEqual({ tMin: -0.375, tMax: 0.5 })

      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 2n, timestampNs: 2_000_000_000n, itemCount: 2, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(4, 5).buffer,
        times: Float64Array.of(1750, 2000).buffer,
      })).toBe(true)
      expect(runtime.probe.fullTimeRange()).toEqual({ tMin: -0.75, tMax: 1 })
      expect(runtime.probe.visibleTimeRange()).toEqual({ tMin: 0.125, tMax: 1 })

      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 3n, timestampNs: 3_000_000_000n, itemCount: 4, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(6, 7, 8, 9).buffer,
        times: Float64Array.of(2250, 2500, 2750, 3000).buffer,
      })).toBe(true)
      expect(runtime.probe.fullTimeRange()).toEqual({ tMin: 0.25, tMax: 2 })
    } finally {
      runtime.cleanup()
    }
  })

  it('shows measured SuperWatch rate from complete binary samples and resets it with the stream', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.probe.syncStatus({ state: 'running', interval: 0.00001, items: [] })
      runtime.viewer.configureBinaryChannels([{ name: 'signal' }])
      const send = (sequence: bigint, timestampNs: bigint, itemCount: number) => {
        const endMs = Number(timestampNs) / 1_000_000
        return runtime.viewer.acceptBinaryBatch({
          sequence, timestampNs, itemCount, channelCount: 1,
          layout: 'sample-major-float32',
          values: new Float32Array(itemCount).buffer,
          times: Float64Array.from(
            { length: itemCount }, (_, index) => endMs - itemCount + index + 1,
          ).buffer,
        })
      }

      expect(document.getElementById('sample-rate-badge')?.textContent).toBe('-- Hz')
      expect(send(1n, 1_000_000_000n, 32)).toBe(true)
      expect(send(2n, 1_250_000_000n, 250)).toBe(true)
      expect(document.getElementById('sample-rate-badge')?.textContent).toBe('-- Hz')
      expect(send(3n, 1_500_000_000n, 250)).toBe(true)
      expect(document.getElementById('sample-rate-badge')?.textContent)
        .toBe('1000.00 Hz')

      runtime.viewer.resetBinaryStream()
      expect(document.getElementById('sample-rate-badge')?.textContent).toBe('-- Hz')

      runtime.probe.syncStatus({
        state: 'running', interval: 0.00001, actual_rate: 6250, items: [],
      })
      expect(document.getElementById('sample-rate-badge')?.textContent)
        .toBe('6250.00 Hz')
    } finally {
      runtime.cleanup()
    }
  })

  it('uses the normalized server interval when zero requests fastest acquisition', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      runtime.probe.syncStatus({ running: true, interval: 0.25, channels: [] })
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ interval: 0.000001 }),
      }))
      const input = document.getElementById('interval-input') as HTMLInputElement
      expect(input.min).toBe('0')
      input.value = '0'
      document.getElementById('btn-apply-interval')?.click()
      for (let turn = 0; turn < 6; turn++) await Promise.resolve()

      expect(runtime.probe.currentInterval()).toBe(0.000001)
      expect(input.value).toBe('0.000001')
    } finally {
      runtime.cleanup()
    }
  })

  it('does not start a late VOFA stream after the component unmounts', async () => {
    let resolveFetch!: (value: unknown) => void
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(resolve => {
      resolveFetch = resolve
    })))
    const wrapper = mount(WaveformViewer, { props: { mode: 'VOFA', deviceConnected: true } })
    wrapper.unmount()
    resolveFetch({ ok: true, json: async () => ({ running: true, channels: [{ name: 'id' }] }) })
    await new Promise(resolve => setTimeout(resolve, 0))

    expect(mocks.binary.start).not.toHaveBeenCalled()
  })

  it('requests one bounded visible envelope per scheduled frame and renders its response', async () => {
    const acceptBinaryBatch = vi.fn()
    const getBinaryVisibleRange = vi.fn(() => ({ start: 10, end: 20, pixelWidth: 640 }))
    const renderBinaryEnvelope = vi.fn()
    ;(window as any).__waveformViewers.VOFA = {
      acceptBinaryBatch, getBinaryVisibleRange, renderBinaryEnvelope,
    }
    const wrapper = mount(WaveformViewer, { props: { mode: 'VOFA', deviceConnected: true } })
    await new Promise(resolve => setTimeout(resolve, 0))
    ;(window as any).__waveformViewers.VOFA = {
      acceptBinaryBatch, getBinaryVisibleRange, renderBinaryEnvelope,
    }

    const batch = {
      type: 'waveform-batch', sequence: 1n, timestampNs: 1_000_000n,
      itemCount: 2, channelCount: 2, layout: 'sample-major-float32',
      values: Float32Array.of(1, 10, 2, 20).buffer,
      times: Float64Array.of(1, 2).buffer,
    }
    if (!mocks.binary.waveformBatch) throw new Error('missing batch ref')
    mocks.binary.waveformBatch.value = batch
    await nextTick()

    expect(acceptBinaryBatch).toHaveBeenCalledOnce()
    expect(mocks.schedulerInstances[0].recordCollection).toHaveBeenCalledWith(2)
    expect(mocks.schedulerInstances[0].invalidate).toHaveBeenCalledWith('data')
    mocks.schedulerInstances[0].render()
    expect(mocks.binary.requestVisibleRange).toHaveBeenCalledWith(expect.any(Number), 10, 20, 640)
    const requestId = mocks.binary.requestVisibleRange.mock.calls[0][0]

    const envelope = {
      type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
      requestId, pixelWidth: 640, channelCount: 2, pointCount: 2,
      candidateSampleCount: 2, channelOffsets: Uint32Array.of(0, 1, 2).buffer,
      times: Float64Array.of(1, 2).buffer, timeIndices: Uint32Array.of(0, 1).buffer,
      values: Float32Array.of(1, 20).buffer,
    }
    if (!mocks.binary.envelope) throw new Error('missing envelope ref')
    mocks.binary.envelope.value = envelope
    await nextTick()
    expect(renderBinaryEnvelope).toHaveBeenCalledWith(envelope, false)
    wrapper.unmount()
  })

  it('attaches the SuperWatch viewport requester after the viewer script loads', async () => {
    const setDeviceConnected = vi.fn()
    let requestViewport: (() => void) | undefined
    const setBinaryVisibleRangeRequester = vi.fn((requester: () => void) => {
      requestViewport = requester
    })
    const getBinaryVisibleRange = vi.fn(() => ({ start: 100, end: 200, pixelWidth: 800 }))
    const renderBinaryEnvelope = vi.fn()
    const wrapper = mount(WaveformViewer, {
      props: { mode: 'SuperWatch', deviceConnected: false },
    })
    await new Promise(resolve => setTimeout(resolve, 0))

    const i18nScript = wrapper.element.querySelector('script[src]') as HTMLScriptElement
    await wrapper.setProps({ deviceConnected: true })
    i18nScript.onload?.(new Event('load'))
    ;(window as any).__waveformViewers.SuperWatch = {
      setBinaryVisibleRangeRequester, getBinaryVisibleRange, renderBinaryEnvelope, setDeviceConnected,
    }
    const scripts = wrapper.element.querySelectorAll('script[src]')
    const viewerScript = scripts[scripts.length - 1] as HTMLScriptElement
    viewerScript.onload?.(new Event('load'))
    expect(setDeviceConnected).toHaveBeenCalledWith(true)

    expect(setBinaryVisibleRangeRequester).toHaveBeenCalledOnce()
    requestViewport?.()
    expect(mocks.binary.requestVisibleRange).toHaveBeenCalledWith(
      expect.any(Number), 100, 200, 800,
    )
    const requestId = mocks.binary.requestVisibleRange.mock.calls.at(-1)?.[0]
    const envelope = {
      type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
      requestId, pixelWidth: 800, channelCount: 1, pointCount: 2,
      candidateSampleCount: 2, channelOffsets: Uint32Array.of(0, 2).buffer,
      times: Float64Array.of(100, 200).buffer,
      timeIndices: Uint32Array.of(0, 1).buffer,
      values: Float32Array.of(1, 2).buffer,
    }
    if (!mocks.binary.envelope) throw new Error('missing envelope ref')
    mocks.binary.envelope.value = envelope
    await nextTick()

    expect(renderBinaryEnvelope).toHaveBeenCalledWith(envelope, true)
    wrapper.unmount()
  })

  it('coalesces delayed Worker envelopes and immediately requests the latest visible range', async () => {
    const acceptBinaryBatch = vi.fn()
    const getBinaryVisibleRange = vi.fn()
      .mockReturnValueOnce({ start: 10, end: 20, pixelWidth: 640 })
      .mockReturnValueOnce({ start: 30, end: 40, pixelWidth: 640 })
    const renderBinaryEnvelope = vi.fn()
    ;(window as any).__waveformViewers.VOFA = {
      acceptBinaryBatch, getBinaryVisibleRange, renderBinaryEnvelope,
    }
    const wrapper = mount(WaveformViewer, { props: { mode: 'VOFA', deviceConnected: true } })
    await new Promise(resolve => setTimeout(resolve, 0))
    ;(window as any).__waveformViewers.VOFA = {
      acceptBinaryBatch, getBinaryVisibleRange, renderBinaryEnvelope,
    }

    mocks.schedulerInstances[0].render()
    mocks.schedulerInstances[0].render()
    expect(mocks.binary.requestVisibleRange).toHaveBeenCalledTimes(1)
    const firstRequestId = mocks.binary.requestVisibleRange.mock.calls[0][0]

    if (!mocks.binary.envelope) throw new Error('missing envelope ref')
    mocks.binary.envelope.value = {
      type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
      requestId: firstRequestId, pixelWidth: 640, channelCount: 2, pointCount: 2,
      candidateSampleCount: 2, channelOffsets: Uint32Array.of(0, 1, 2).buffer,
      times: Float64Array.of(1, 2).buffer, timeIndices: Uint32Array.of(0, 1).buffer,
      values: Float32Array.of(1, 20).buffer,
    }
    await nextTick()

    expect(renderBinaryEnvelope).toHaveBeenCalledOnce()
    expect(mocks.binary.requestVisibleRange).toHaveBeenCalledTimes(2)
    expect(mocks.binary.requestVisibleRange).toHaveBeenLastCalledWith(
      expect.any(Number), 30, 40, 640,
    )
    wrapper.unmount()
  })

  it('reconfigures Worker storage and labels when VOFA status changes channels', async () => {
    const configureBinaryChannels = vi.fn()
    ;(window as any).__waveformViewers.VOFA = { configureBinaryChannels }
    const wrapper = mount(WaveformViewer, { props: { mode: 'VOFA', deviceConnected: true } })
    await new Promise(resolve => setTimeout(resolve, 0))
    mocks.binary.configure.mockClear()
    ;(window as any).__waveformViewers.VOFA = { configureBinaryChannels }
    const channels = [{ name: 'a' }, { name: 'b' }, { name: 'c' }]

    window.dispatchEvent(new CustomEvent('mklink:vofa-channels', { detail: channels }))
    expect(mocks.binary.configure).toHaveBeenCalledWith(3)
    expect(configureBinaryChannels).toHaveBeenCalledWith(channels)

    mocks.binary.configure.mockClear()
    configureBinaryChannels.mockClear()
    window.dispatchEvent(new CustomEvent('mklink:vofa-channels', { detail: [] }))
    expect(mocks.binary.configure).toHaveBeenCalledWith(1)
    expect(configureBinaryChannels).toHaveBeenCalledWith([])

    wrapper.unmount()
    mocks.binary.configure.mockClear()
    window.dispatchEvent(new CustomEvent('mklink:vofa-channels', { detail: [{ name: 'late' }] }))
    expect(mocks.binary.configure).not.toHaveBeenCalled()
  })

  it('does not reset Worker storage for an identical channel snapshot', async () => {
    const configureBinaryChannels = vi.fn()
    ;(window as any).__waveformViewers.VOFA = { configureBinaryChannels }
    const wrapper = mount(WaveformViewer, { props: { mode: 'VOFA', deviceConnected: true } })
    await new Promise(resolve => setTimeout(resolve, 0))
    mocks.binary.configure.mockClear()
    configureBinaryChannels.mockClear()
    ;(window as any).__waveformViewers.VOFA = { configureBinaryChannels }
    const unchanged = [
      { name: 'id', addr: 0x20000000, type: 'uint32_t', size: 4 },
      { name: 'value', addr: 0x20000004, type: 'float', size: 4 },
    ]

    window.dispatchEvent(new CustomEvent('mklink:vofa-channels', { detail: unchanged }))

    expect(mocks.binary.configure).not.toHaveBeenCalled()
    expect(configureBinaryChannels).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('resets Worker state on reconnect but preserves it when collection stops', async () => {
    const resetBinaryStream = vi.fn()
    const updateBinaryHealth = vi.fn()
    ;(window as any).__waveformViewers.VOFA = { resetBinaryStream, updateBinaryHealth }
    const wrapper = mount(WaveformViewer, { props: { mode: 'VOFA', deviceConnected: true } })
    await new Promise(resolve => setTimeout(resolve, 0))
    mocks.binary.reset.mockClear()
    ;(window as any).__waveformViewers.VOFA = { resetBinaryStream, updateBinaryHealth }
    if (!mocks.binary.state || !mocks.binary.error) throw new Error('missing state refs')

    mocks.binary.error.value = 'old socket error'
    mocks.binary.state.value = { phase: 'reconnecting', reconnectDelayMs: 250 }
    await nextTick()
    expect(mocks.binary.reset).toHaveBeenCalledOnce()
    expect(resetBinaryStream).toHaveBeenCalledOnce()

    window.dispatchEvent(new CustomEvent('mklink:vofa-stream-state', { detail: 'stopped' }))
    expect(mocks.binary.reset).toHaveBeenCalledOnce()
    expect(resetBinaryStream).toHaveBeenCalledOnce()

    mocks.binary.state.value = { phase: 'connected' }
    await nextTick()
    expect(updateBinaryHealth).toHaveBeenLastCalledWith(expect.objectContaining({
      phase: 'connected', error: null,
    }))
    wrapper.unmount()
  })

  it('polls measured status at 1 Hz without reconfiguring and ignores late stopped responses', async () => {
    vi.useFakeTimers()
    try {
      let resolveLate!: (value: unknown) => void
      const fetchMock = vi.fn()
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            running: true, actual_rate: 0, interval: 0.001,
            channels: [{ name: 'id', addr: 0x20000000, type: 'uint32_t', size: 4 }],
          }),
        })
        .mockReturnValueOnce(new Promise(resolve => { resolveLate = resolve }))
        .mockResolvedValue({
          ok: true,
          json: async () => ({ running: true, actual_rate: 12_345, interval: 0.001, channels: [] }),
        })
      vi.stubGlobal('fetch', fetchMock)
      const updateAcquisitionStatus = vi.fn()
      ;(window as any).__waveformViewers.VOFA = { updateAcquisitionStatus }
      const wrapper = mount(WaveformViewer, { props: { mode: 'VOFA', deviceConnected: true } })
      for (let turn = 0; turn < 6; turn++) await Promise.resolve()
      await nextTick()

      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(mocks.binary.start).toHaveBeenCalledOnce()
      expect(mocks.binary.configure).toHaveBeenCalledOnce()
      expect(updateAcquisitionStatus).toHaveBeenLastCalledWith(expect.objectContaining({ actual_rate: 0 }))

      await vi.advanceTimersByTimeAsync(999)
      expect(fetchMock).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(1)
      expect(fetchMock).toHaveBeenCalledTimes(2)

      window.dispatchEvent(new CustomEvent('mklink:vofa-stream-state', { detail: 'stopped' }))
      resolveLate({
        ok: true,
        json: async () => ({ running: true, actual_rate: 99_999, interval: 0.001, channels: [] }),
      })
      for (let turn = 0; turn < 6; turn++) await Promise.resolve()
      expect(updateAcquisitionStatus).not.toHaveBeenCalledWith(
        expect.objectContaining({ actual_rate: 99_999 }),
      )
      await vi.advanceTimersByTimeAsync(2_000)
      expect(fetchMock).toHaveBeenCalledTimes(2)

      window.dispatchEvent(new CustomEvent('mklink:vofa-stream-state', { detail: 'running' }))
      for (let turn = 0; turn < 6; turn++) await Promise.resolve()
      expect(fetchMock).toHaveBeenCalledTimes(3)
      expect(updateAcquisitionStatus).toHaveBeenLastCalledWith(
        expect.objectContaining({ actual_rate: 12_345 }),
      )
      expect(mocks.binary.start).toHaveBeenCalledTimes(2)
      expect(mocks.binary.configure).toHaveBeenCalledOnce()

      wrapper.unmount()
      await vi.advanceTimersByTimeAsync(2_000)
      expect(fetchMock).toHaveBeenCalledTimes(3)
    } finally {
      vi.useRealTimers()
    }
  })

  it('bridges connection, drop, and buffer telemetry into viewer health', async () => {
    const updateBinaryHealth = vi.fn()
    ;(window as any).__waveformViewers.VOFA = { updateBinaryHealth }
    const wrapper = mount(WaveformViewer, { props: { mode: 'VOFA', deviceConnected: true } })
    await new Promise(resolve => setTimeout(resolve, 0))
    ;(window as any).__waveformViewers.VOFA = { updateBinaryHealth }
    if (!mocks.binary.state || !mocks.binary.telemetry || !mocks.binary.error) {
      throw new Error('missing health refs')
    }
    mocks.binary.state.value = { phase: 'reconnecting', reconnectDelayMs: 500 }
    mocks.binary.telemetry.value = {
      bufferedSamples: 1234, transportDroppedBatches: 2,
      backendDroppedBatches: 3, backendDroppedItems: 40,
    }
    mocks.binary.error.value = 'socket lost'
    await nextTick()

    expect(updateBinaryHealth).toHaveBeenLastCalledWith({
      phase: 'reconnecting', reconnectDelayMs: 500, bufferedSamples: 1234,
      transportDroppedBatches: 2, backendDroppedBatches: 3,
      backendDroppedItems: 40, error: 'socket lost',
    })
    wrapper.unmount()
  })
})

describe('VOFA viewer hot path source guard', () => {
  it('uses the application language and does not inject a local language button', () => {
    const componentSource = fs.readFileSync('src/components/dash/WaveformViewer.vue', 'utf8')

    expect(componentSource).toContain("import { language } from '../../composables/useLanguage'")
    expect(componentSource).not.toContain('id="btn-lang-toggle"')
  })

  const source = viewerSource

  it('describes coordinate-axis zoom, drag, and reset interactions in both languages', () => {
    expect(componentSource).toContain('data-i18n-title="x_axis_tip"')
    expect(componentSource).toContain('data-i18n-title="y_axis_tip"')
    expect(i18nSource).toContain("x_axis_tip: '横轴：滚轮缩放；按住鼠标左键拖动；双击恢复默认视图'")
    expect(i18nSource).toContain("y_axis_tip: '纵轴：滚轮缩放；按住鼠标左键拖动；双击恢复自动范围'")
    expect(i18nSource).toContain("x_axis_tip: 'X axis: scroll to zoom; hold the left mouse button and drag; double-click to reset'")
    expect(i18nSource).toContain("y_axis_tip: 'Y axis: scroll to zoom; hold the left mouse button and drag; double-click for auto range'")
  })

  it('routes waveform API calls through the runtime-selected backend origin', () => {
    expect(componentSource).toContain("import { API_BASE } from '../../lib/runtimeEndpoint'")
    expect(componentSource).toContain('fetch(`${API_BASE}/api/dash/${')
    expect(componentSource).toContain('apiBase: ${JSON.stringify(API_BASE)}')
    expect(source).toContain("var API_BASE = CONFIG.apiBase || '';")
    expect(source).toContain("var API_CTRL = API_BASE + '/api/dash/'")
    expect(source).toContain("var API_SW = API_BASE + '/api/dash/superwatch/';")
  })

  it('keeps SuperWatch symbol selection outside the waveform workspace', () => {
    expect(componentSource).not.toContain('superwatch-search-input')
    expect(componentSource).not.toContain('superwatch-add-btn')
    expect(source).not.toContain('sw-search-dropdown')
    expect(source).not.toContain("API_SYMBOLS + 'search'")
  })

  it('suppresses the redundant Watch panel only in the desktop SuperWatch workspace', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      expect(runtime.wrapper.get('.waveform-viewer').classes()).toContain('superwatch-desktop')
      expect(document.getElementById('watch-panel')).not.toBeNull()
      expect(viewerCss).toContain('.waveform-viewer.superwatch-desktop #watch-panel')
      expect(viewerCss).toContain('.waveform-viewer.superwatch-desktop #watch-resizer')
    } finally {
      runtime.cleanup()
    }
  })

  it('removes the dynamic statistics footer from the waveform layout', () => {
    expect(componentSource).not.toContain('id="stats-footer"')
    expect(viewerSource).not.toContain("document.getElementById('stats-footer')")
    expect(viewerCss).not.toMatch(/(^|\n)\s*footer\s*\{/)
  })

  it('keeps waveform header styles scoped to the viewer', () => {
    expect(viewerCss).not.toMatch(/(^|\n)\s*header(?:\s+h1)?\s*\{/)
    expect(viewerCss).toContain('.waveform-viewer header {')
    expect(viewerCss).toContain('.waveform-viewer header h1 {')
  })

  it('keeps desktop SuperWatch live status and controls in stable rows', () => {
    expect(componentSource).toContain('<div class="header-status">')
    expect(viewerCss).toContain('.waveform-viewer.superwatch-desktop header')
    expect(viewerCss).toContain('grid-template-columns: minmax(0, 1fr) auto')
    expect(viewerCss).toContain('.waveform-viewer.superwatch-desktop #control-toolbar')
    expect(viewerCss).toContain('.waveform-viewer.superwatch-desktop #trigger-toolbar')
    expect(viewerCss).toContain('.waveform-viewer.superwatch-desktop #transport-health-badge')
    expect(viewerCss).toContain(
      '.waveform-viewer.superwatch-desktop #sample-rate-badge {\n' +
      '    width: 104px;\n    overflow: hidden;',
    )
    expect(viewerCss).toContain('flex-wrap: nowrap')
    expect(viewerCss).toContain(
      '.waveform-viewer.superwatch-desktop #control-toolbar > *,\n' +
      '  .waveform-viewer.superwatch-desktop #trigger-toolbar > * {\n' +
      '    flex: 0 0 auto;\n' +
      '    white-space: nowrap;',
    )
    expect(viewerCss).toContain('#interval-group > * { flex: 0 0 auto; }')
    expect(viewerCss).toContain('#trigger-enable-btn,\n#trigger-force-btn {\n  flex: 0 0 auto;')
    expect(viewerCss).toContain('flex: 1 1 140px')
    expect(viewerCss).toContain('text-overflow: ellipsis')
  })

  it('documents live and paused SuperWatch navigation accurately in both languages', () => {
    expect(i18nSource).toContain('后端采集不会停止')
    expect(i18nSource).toContain('恢复或重新开始时保留缩放比例')
    expect(i18nSource).toContain('保持与最新数据的固定时间差并继续前移')
    expect(i18nSource).toContain('backend acquisition continues')
    expect(i18nSource).toContain('Resume or restart keeps your zoom scale')
    expect(i18nSource).toContain('keeps a fixed lag from the latest data and continues moving forward')
  })

  it('bounds the channel layout legend inside the chart on narrow viewports', () => {
    expect(componentSource).toContain('id="chart-legend-toggle"')
    expect(viewerCss).toContain('max-width: calc(100% - 84px)')
    expect(viewerCss).toContain('.chart-legend-row {\n  display: grid;')
    expect(viewerCss).toContain('max-width: 100%;')
    expect(viewerCss).toContain('#chart-legend.is-visible')
    expect(i18nSource).toContain("show_channel_legend_tip: '显示通道列表'")
  })

  it('auto-hides the channel legend and reveals it while the pointer is nearby', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    vi.useFakeTimers()
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      const toggle = document.getElementById('chart-legend-toggle')!
      const legend = document.getElementById('chart-legend')!

      expect(toggle.hidden).toBe(false)
      expect(toggle.getAttribute('aria-expanded')).toBe('true')
      expect(legend.classList.contains('is-visible')).toBe(true)
      vi.advanceTimersByTime(2000)
      expect(toggle.getAttribute('aria-expanded')).toBe('false')
      expect(legend.getAttribute('aria-hidden')).toBe('true')

      toggle.dispatchEvent(new MouseEvent('mouseenter'))
      expect(legend.classList.contains('is-visible')).toBe(true)
      toggle.dispatchEvent(new MouseEvent('mouseleave'))
      vi.advanceTimersByTime(699)
      expect(legend.classList.contains('is-visible')).toBe(true)
      legend.dispatchEvent(new MouseEvent('mouseenter'))
      vi.advanceTimersByTime(1)
      expect(legend.classList.contains('is-visible')).toBe(true)
      legend.dispatchEvent(new MouseEvent('mouseleave'))
      vi.advanceTimersByTime(700)
      expect(legend.classList.contains('is-visible')).toBe(false)
    } finally {
      runtime.cleanup()
      vi.useRealTimers()
    }
  })

  it('keeps the channel legend visible while a channel is being split', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    vi.useFakeTimers()
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 2,
        layout: 'sample-major-float32', values: Float32Array.of(1, 10, 2, 20, 3, 30).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)
      vi.advanceTimersByTime(2000)
      const legend = document.getElementById('chart-legend')!
      document.getElementById('chart-legend-toggle')!
        .dispatchEvent(new MouseEvent('mouseenter'))
      expect(runtime.probe.setSplitChannel('A')).toBe(true)

      expect(runtime.probe.splitChannel()).toBe('A')
      expect(legend.classList.contains('is-visible')).toBe(true)
      expect(legend.querySelector<HTMLButtonElement>('[data-channel="A"]')?.textContent)
        .toBe('merge_channel')
    } finally {
      runtime.cleanup()
      vi.useRealTimers()
    }
  })

  it('hides selected curves without stopping their binary samples', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      runtime.viewer.setHiddenChannels(['B'])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 2,
        layout: 'sample-major-float32', values: Float32Array.of(1, 10, 2, 20, 3, 30).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)

      expect(runtime.probe.fields().A.visible).toBe(true)
      expect(runtime.probe.fields().B.visible).toBe(false)
      expect(runtime.probe.fields().B.ringBuf.count).toBe(3)

      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      expect(runtime.probe.fields().B.visible).toBe(false)
      runtime.viewer.setHiddenChannels([])
      expect(runtime.probe.fields().B.visible).toBe(true)
    } finally {
      runtime.cleanup()
    }
  })

  it('forwards Vue hidden-channel prop replacements to the canvas runtime', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      await runtime.wrapper.setProps({ hiddenChannels: new Set(['B']) })
      await nextTick()

      expect(runtime.probe.fields().A.visible).toBe(true)
      expect(runtime.probe.fields().B.visible).toBe(false)
    } finally {
      runtime.cleanup()
    }
  })

  it('draws one shared numeric Y axis from visible SuperWatch channels', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'signal' }, { name: 'outlier' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 2,
        layout: 'sample-major-float32', values: Float32Array.of(0, 1000, 1, 1500, 2, 2000).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)

      ;(window as any).__canvasLabels = []
      runtime.viewer.renderBinaryFrame()
      const allTicks = (window as any).__canvasLabels
        .filter((label: string) => /^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(label))
        .map(Number)
      expect(allTicks).toHaveLength(6)
      expect(Math.max(...allTicks)).toBeGreaterThan(2000)

      runtime.viewer.setHiddenChannels(['outlier'])
      ;(window as any).__canvasLabels = []
      runtime.viewer.renderBinaryFrame()
      const signalTicks = (window as any).__canvasLabels
        .filter((label: string) => /^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(label))
        .map(Number)
      expect(signalTicks).toHaveLength(6)
      expect(Math.max(...signalTicks)).toBeLessThan(3)
    } finally {
      runtime.cleanup()
    }
  })

  it('lays out three multi-signal panes without resetting samples and preserves aliases', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch', 10)
    try {
      const names = ['a','b','c','d','e','f']
      runtime.viewer.configureBinaryChannels(names.map(name => ({name})))
      runtime.viewer.acceptBinaryBatch({sequence:1n,timestampNs:1_100_000_000n,itemCount:2,channelCount:6,
        layout:'sample-major-float32',values:Float32Array.of(1,2,100,200,1000,2000,2,3,110,210,1100,2100).buffer,
        times:Float64Array.of(1000,1100).buffer})
      const workspace = {version:1,groups:[],panes:['p1','p2','p3'].map(id=>({id,name:id,height:200})),
        signals:Object.fromEntries(names.map((name,i)=>[name,{pane:'p'+(Math.floor(i/2)+1),alias:'信号'+name,emphasis:i===0}]))}
      runtime.viewer.setWorkspace(workspace)
      const panes = runtime.probe.panelLayout().panes
      expect(panes).toHaveLength(3)
      expect(panes[0].range.yMax).toBeLessThan(panes[1].range.yMin)
      expect(panes[1].range.yMax).toBeLessThan(panes[2].range.yMin)
      expect(runtime.probe.fields().a.ringBuf.count).toBe(2)
      expect(runtime.probe.serializeState().workspace).toEqual(workspace)
      expect(document.querySelector('.chart-legend-name')?.textContent).toBe('信号a')
      ;(window as any).__canvasDraws=[]
      runtime.viewer.setWorkspace({...workspace,signals:{...workspace.signals,a:{...workspace.signals.a,renderMode:'points'}}})
      const color=runtime.probe.fields().a.color
      const draws=(window as any).__canvasDraws.filter((d:any)=>d.color===color)
      expect(draws.some((d:any)=>d.op==='fillRect' && d.args[2]===5)).toBe(true)
      expect(draws.some((d:any)=>d.op==='stroke')).toBe(false)
      expect(runtime.probe.fields().a.ringBuf.count).toBe(2)
      ;(window as any).__canvasDraws=[]
      runtime.viewer.setWorkspace(workspace)
      expect((window as any).__canvasDraws.some((d:any)=>d.color===color&&d.op==='stroke')).toBe(true)
      delete (window as any).__canvasDraws
      // Empty groups neither reserve canvas space nor change signal routing.
      const withEmpty={...workspace,panes:[{id:'empty',name:'空组',height:800},...workspace.panes]}
      runtime.viewer.setWorkspace(withEmpty)
      expect(runtime.probe.panelLayout().panes.map((p:any)=>p.id)).toEqual(['p1','p2','p3'])
      let resized:any
      const capture=(event:Event)=>{resized=(event as CustomEvent).detail}
      window.addEventListener('mklink:workspace-resize',capture)
      document.querySelector('.workspace-divider')!.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}))
      window.removeEventListener('mklink:workspace-resize',capture)
      expect(resized.find((p:any)=>p.id==='empty').height).toBe(800)
      expect(resized.find((p:any)=>p.id==='p1').height).toBe(220)
      expect(resized.find((p:any)=>p.id==='p2').height).toBe(180)
      const other = {...panes[1].range}
      document.getElementById('chart')!.dispatchEvent(new WheelEvent('wheel',{deltaY:-100,clientX:400,clientY:panes[0].top+20,cancelable:true}))
      expect(runtime.probe.panelYRange(panes[1])).toEqual(other)
      expect(runtime.probe.fields().a.ringBuf.count).toBe(2)
    } finally { runtime.cleanup() }
  })

  it('splits one SuperWatch channel into an independent Y panel and merges it back', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'small' }, { name: 'large' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 1_200_000_000n, itemCount: 3, channelCount: 2,
        layout: 'sample-major-float32', values: Float32Array.of(1, 100, 2, 200, 3, 300).buffer,
        times: Float64Array.of(1000, 1100, 1200).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()

      expect(runtime.probe.setSplitChannel('large')).toBe(true)
      runtime.viewer.renderBinaryFrame()
      expect(runtime.probe.splitChannel()).toBe('large')
      expect(runtime.probe.panelLayout()).toMatchObject({ split: true })

      const mainPanel = { kind: 'main' }
      const splitPanel = { kind: 'split', name: 'large' }
      const mainBefore = runtime.probe.panelYRange(mainPanel)
      const splitBefore = runtime.probe.panelYRange(splitPanel)
      expect(mainBefore.yMax).toBeLessThan(10)
      expect(splitBefore.yMin).toBeGreaterThan(50)

      const layout = runtime.probe.panelLayout()
      const splitY = layout.splitTop + layout.splitHeight / 2
      const canvas = document.getElementById('chart')!
      canvas.dispatchEvent(wheelEvent({
        deltaY: -100, clientX: 400, clientY: splitY, bubbles: true, cancelable: true,
      }))
      const splitZoomed = runtime.probe.panelYRange(splitPanel)
      expect(runtime.probe.panelYRange(mainPanel)).toEqual(mainBefore)
      expect(splitZoomed.yMax - splitZoomed.yMin)
        .toBeCloseTo((splitBefore.yMax - splitBefore.yMin) * 0.8, 12)

      canvas.dispatchEvent(new MouseEvent('mousedown', {
        button: 0, clientX: 400, clientY: splitY, bubbles: true, cancelable: true,
      }))
      window.dispatchEvent(new MouseEvent('mousemove', {
        clientX: 400, clientY: splitY + 20, bubbles: true,
      }))
      window.dispatchEvent(new MouseEvent('mouseup', { button: 0, clientX: 400, clientY: splitY + 20 }))
      const splitPanned = runtime.probe.panelYRange(splitPanel)
      expect(runtime.probe.panelYRange(mainPanel)).toEqual(mainBefore)
      expect(splitPanned.yMin).toBeGreaterThan(splitZoomed.yMin)
      expect(splitPanned.yMax).toBeGreaterThan(splitZoomed.yMax)

      const timeline = runtime.probe.timeline()
      const beforeTimelineZoom = timeline.zoom
      const beforeSplitRange = runtime.probe.panelYRange(splitPanel)
      canvas.dispatchEvent(wheelEvent({
        deltaY: -100, shiftKey: true, clientX: 400, clientY: splitY,
        bubbles: true, cancelable: true,
      }))
      expect(timeline.zoom).toBeGreaterThan(beforeTimelineZoom)
      expect(runtime.probe.panelYRange(splitPanel)).toEqual(beforeSplitRange)
      expect(runtime.probe.panelYRange(mainPanel)).toEqual(mainBefore)

      const saved = runtime.probe.serializeState()
      expect(saved.splitChannel).toBe('large')
      runtime.probe.clearSplitChannel()
      expect(runtime.probe.panelLayout().split).toBe(false)
      expect(runtime.probe.deserializeState(saved)).toBe(true)
      expect(runtime.probe.splitChannel()).toBe('large')
      expect(runtime.probe.panelLayout().split).toBe(true)

      const yAxis = document.getElementById('y-axis-hit')!
      yAxis.dispatchEvent(new MouseEvent('dblclick', {
        clientY: splitY, bubbles: true, cancelable: true,
      }))
      expect(runtime.probe.panelYRange(splitPanel)).toEqual({ yMin: 80, yMax: 320 })
      expect(runtime.probe.panelYRange(mainPanel)).toEqual(mainBefore)

      runtime.probe.clearSplitChannel()
      expect(runtime.probe.splitChannel()).toBe(null)
      expect(runtime.probe.panelLayout().split).toBe(false)

      runtime.probe.setSplitChannel('large')
      runtime.viewer.renderBinaryFrame()
      const splitControl = document.getElementById('split-panel-control')!
      expect(splitControl.hidden).toBe(false)
      expect(document.getElementById('split-panel-name')?.textContent).toBe('large')
      document.getElementById('split-panel-merge')!.click()
      expect(runtime.probe.splitChannel()).toBe(null)
      expect(splitControl.hidden).toBe(true)
    } finally {
      runtime.cleanup()
    }
  })

  it('anchors shared SuperWatch canvas wheel zoom to the pointer Y value', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch', 8)
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'small' }, { name: 'uwTick' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 2,
        layout: 'sample-major-float32',
        values: Float32Array.of(1, 100000, 2, 200000, 3, 300000).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()

      const canvas = document.getElementById('chart')!
      const before = runtime.probe.sharedYRange()
      const plotTop = 8
      const plotHeight = 400 - plotTop - 32
      const anchorRatio = 0.25
      const pointerY = plotTop + plotHeight * anchorRatio
      const anchorBefore = before.yMax - anchorRatio * (before.yMax - before.yMin)

      const zoomEvent = wheelEvent({
        deltaY: -100, clientX: 400, clientY: pointerY, bubbles: true, cancelable: true,
      })
      expect(zoomEvent.clientY).toBe(pointerY)
      canvas.dispatchEvent(zoomEvent)

      const after = runtime.probe.sharedYRange()
      const expectedSpan = (before.yMax - before.yMin) * 0.8
      expect(after).toEqual({
        yMin: anchorBefore - (1 - anchorRatio) * expectedSpan,
        yMax: anchorBefore + anchorRatio * expectedSpan,
      })
      const anchorAfter = after.yMax - anchorRatio * (after.yMax - after.yMin)
      expect(after.yMax - after.yMin).toBeLessThan(before.yMax - before.yMin)
      expect(anchorAfter).toBeCloseTo(anchorBefore, 8)
      expect(runtime.probe.globalYView()).toMatchObject({ autoRange: false })
    } finally {
      runtime.cleanup()
    }
  })

  it('keeps a manual shared SuperWatch Y range fixed as later values grow', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch', 8)
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'small' }, { name: 'uwTick' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 2,
        layout: 'sample-major-float32',
        values: Float32Array.of(1, 100000, 2, 200000, 3, 300000).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()

      document.getElementById('chart')!.dispatchEvent(wheelEvent({
        deltaY: -100, clientX: 400, clientY: 98, bubbles: true, cancelable: true,
      }))
      const lockedRange = runtime.probe.sharedYRange()

      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 2n, timestampNs: 5_000_000n, itemCount: 2, channelCount: 2,
        layout: 'sample-major-float32',
        values: Float32Array.of(4, 900000, 5, 1000000).buffer,
        times: Float64Array.of(3, 4).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()

      expect(runtime.probe.sharedYRange()).toEqual(lockedRange)
      expect(runtime.probe.fields().uwTick.ringBuf._max).toBe(1000000)
    } finally {
      runtime.cleanup()
    }
  })

  it('persists an absolute manual shared SuperWatch Y range', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2, 3).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()
      document.getElementById('y-axis-hit')!.dispatchEvent(wheelEvent({
        deltaY: -100, clientY: 160, bubbles: true,
      }))
      const manualRange = runtime.probe.sharedYRange()
      const saved = runtime.probe.serializeState()
      expect(saved.globalYView).toEqual({
        zoom: 1, offset: 0, autoRange: false,
        manualMin: manualRange.yMin, manualMax: manualRange.yMax,
      })

      document.getElementById('y-axis-hit')!.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))
      expect(runtime.probe.deserializeState(saved)).toBe(true)
      expect(runtime.probe.sharedYRange()).toEqual(manualRange)
      expect(runtime.probe.globalYView()).toEqual(saved.globalYView)
    } finally {
      runtime.cleanup()
    }
  })

  it('loads legacy shared Y zoom and rejects invalid manual bounds', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      expect(runtime.probe.deserializeState({
        channels: [{ name: 'A' }],
        globalYView: { zoom: 2, offset: 0.25 },
      })).toBe(true)
      expect(runtime.probe.globalYView()).toEqual({
        zoom: 2, offset: 0.25, autoRange: true, manualMin: null, manualMax: null,
      })

      expect(runtime.probe.deserializeState({
        channels: [{ name: 'A' }],
        globalYView: {
          zoom: 3, offset: 0.5, autoRange: false, manualMin: null, manualMax: 10,
        },
      })).toBe(true)
      expect(runtime.probe.globalYView()).toEqual({
        zoom: 3, offset: 0.5, autoRange: true, manualMin: null, manualMax: null,
      })
    } finally {
      runtime.cleanup()
    }
  })

  it('resets a previous manual shared Y range when a legacy project omits global Y state', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2, 3).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()
      document.getElementById('y-axis-hit')!.dispatchEvent(wheelEvent({
        deltaY: -100, clientY: 160, bubbles: true,
      }))
      expect(runtime.probe.globalYView()).toMatchObject({ autoRange: false })

      expect(runtime.probe.deserializeState({ channels: [{ name: 'A' }] })).toBe(true)
      expect(runtime.probe.globalYView()).toEqual({
        zoom: 1, offset: 0, autoRange: true, manualMin: null, manualMax: null,
      })
    } finally {
      runtime.cleanup()
    }
  })

  it('zooms, pans, and resets the X axis through its hit region', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime()
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2, 3).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })
      const axis = document.getElementById('x-axis-hit')!

      axis.dispatchEvent(wheelEvent({ deltaY: -100, clientX: 400, bubbles: true }))
      expect(runtime.probe.timeline().zoom).toBeGreaterThan(1)
      axis.dispatchEvent(new MouseEvent('mousedown', { button: 0, clientX: 500, bubbles: true }))
      window.dispatchEvent(new MouseEvent('mousemove', { clientX: 300, bubbles: true }))
      window.dispatchEvent(new MouseEvent('mouseup', { clientX: 300, bubbles: true }))
      expect(runtime.probe.timeline().offset).toBeGreaterThan(0)

      axis.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))
      expect(runtime.probe.timeline()).toMatchObject({ zoom: 1, offset: 0 })
    } finally {
      runtime.cleanup()
    }
  })

  it('resets the SuperWatch X axis to its right-aligned half-window default', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      const timeline = runtime.probe.timeline()
      expect(timeline).toMatchObject({ zoom: 2, offset: 1 })
      timeline.zoom = 5
      timeline.offset = 0.25
      document.getElementById('x-axis-hit')!.dispatchEvent(
        new MouseEvent('dblclick', { bubbles: true }),
      )
      expect(timeline).toMatchObject({ zoom: 2, offset: 1 })
    } finally {
      runtime.cleanup()
    }
  })

  it('zooms, pans, and resets an absolute shared SuperWatch Y range through its hit region', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2, 3).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })
      const axis = document.getElementById('y-axis-hit')!

      const beforeZoom = runtime.probe.sharedYRange()
      const anchorRatio = (160 - 8) / 360
      const anchorBefore = beforeZoom.yMax - anchorRatio * (beforeZoom.yMax - beforeZoom.yMin)
      axis.dispatchEvent(wheelEvent({ deltaY: -100, clientY: 160, bubbles: true }))
      const zoomedRange = runtime.probe.sharedYRange()
      const anchorAfter = zoomedRange.yMax - anchorRatio * (zoomedRange.yMax - zoomedRange.yMin)
      expect(anchorAfter).toBeCloseTo(anchorBefore, 12)
      expect(runtime.probe.globalYView()).toMatchObject({
        zoom: 1, offset: 0, autoRange: false,
        manualMin: zoomedRange.yMin, manualMax: zoomedRange.yMax,
      })
      axis.dispatchEvent(new MouseEvent('mousedown', { button: 0, clientY: 120, bubbles: true }))
      window.dispatchEvent(new MouseEvent('mousemove', { clientY: 180, bubbles: true }))
      window.dispatchEvent(new MouseEvent('mouseup', { clientY: 180, bubbles: true }))
      const pannedRange = runtime.probe.sharedYRange()
      expect(pannedRange.yMax - pannedRange.yMin)
        .toBeCloseTo(zoomedRange.yMax - zoomedRange.yMin, 12)
      expect(pannedRange.yMin).toBeGreaterThan(zoomedRange.yMin)
      expect(runtime.probe.globalYView()).toMatchObject({
        zoom: 1, offset: 0, autoRange: false,
        manualMin: pannedRange.yMin, manualMax: pannedRange.yMax,
      })

      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 2n, timestampNs: 5_000_000n, itemCount: 2, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(900000, 1000000).buffer,
        times: Float64Array.of(3, 4).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()
      expect(runtime.probe.sharedYRange()).toEqual(pannedRange)

      axis.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))
      expect(runtime.probe.globalYView()).toEqual({
        zoom: 1, offset: 0, autoRange: true, manualMin: null, manualMax: null,
      })
    } finally {
      runtime.cleanup()
    }
  })

  it('pans the manual shared SuperWatch Y range by plain-left dragging the plot', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2, 3).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()

      const canvas = document.getElementById('chart')!
      canvas.dispatchEvent(wheelEvent({
        deltaY: -100, clientX: 400, clientY: 160, bubbles: true, cancelable: true,
      }))
      const before = runtime.probe.sharedYRange()

      canvas.dispatchEvent(new MouseEvent('mousedown', {
        button: 0, clientX: 400, clientY: 160, bubbles: true, cancelable: true,
      }))
      window.dispatchEvent(new MouseEvent('mousemove', {
        clientX: 400, clientY: 220, bubbles: true,
      }))
      window.dispatchEvent(new MouseEvent('mouseup', {
        button: 0, clientX: 400, clientY: 220, bubbles: true,
      }))

      const after = runtime.probe.sharedYRange()
      expect(after.yMax - after.yMin).toBeCloseTo(before.yMax - before.yMin, 12)
      expect(after.yMin).toBeGreaterThan(before.yMin)
      expect(after.yMax).toBeGreaterThan(before.yMax)
      expect(runtime.probe.globalYView()).toMatchObject({
        autoRange: false, manualMin: after.yMin, manualMax: after.yMax,
      })
    } finally {
      runtime.cleanup()
    }
  })

  it('toggles the SuperWatch hover probe with a plain-left plot click', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2, 3).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()

      const canvas = document.getElementById('chart')!
      const clickPlot = () => {
        canvas.dispatchEvent(new MouseEvent('mousedown', {
          button: 0, clientX: 400, clientY: 160, bubbles: true, cancelable: true,
        }))
        window.dispatchEvent(new MouseEvent('mouseup', {
          button: 0, clientX: 400, clientY: 160, bubbles: true,
        }))
      }

      expect(runtime.probe.hover.active).toBe(false)
      clickPlot()
      expect(runtime.probe.hover.active).toBe(true)
      clickPlot()
      expect(runtime.probe.hover.active).toBe(false)
    } finally {
      runtime.cleanup()
    }
  })

  it('keeps shared SuperWatch Y automatic during a horizontal plot pan', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2, 3).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()

      const canvas = document.getElementById('chart')!
      canvas.dispatchEvent(wheelEvent({
        deltaY: -100, shiftKey: true, clientX: 500, clientY: 160,
        bubbles: true, cancelable: true,
      }))
      const beforeOffset = runtime.probe.timeline().offset
      const beforeY = runtime.probe.sharedYRange()
      expect(runtime.probe.globalYView()).toEqual({
        zoom: 1, offset: 0, autoRange: true, manualMin: null, manualMax: null,
      })

      canvas.dispatchEvent(new MouseEvent('mousedown', {
        button: 0, clientX: 500, clientY: 160, bubbles: true, cancelable: true,
      }))
      window.dispatchEvent(new MouseEvent('mousemove', {
        clientX: 700, clientY: 160, bubbles: true,
      }))
      window.dispatchEvent(new MouseEvent('mouseup', {
        button: 0, clientX: 700, clientY: 160, bubbles: true,
      }))

      expect(runtime.probe.timeline().offset).toBeLessThan(beforeOffset)
      expect(runtime.probe.globalYView()).toEqual({
        zoom: 1, offset: 0, autoRange: true, manualMin: null, manualMax: null,
      })
      expect(runtime.probe.sharedYRange()).toEqual(beforeY)
    } finally {
      runtime.cleanup()
    }
  })

  it('scales horizontal SuperWatch plot pan by the visible timeline span', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2, 3).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)
      const timeline = runtime.probe.timeline()
      timeline.zoom = 100
      timeline.offset = 0.5
      runtime.viewer.renderBinaryFrame()
      const beforeY = runtime.probe.sharedYRange()

      const canvas = document.getElementById('chart')!
      const plotWidth = 800 - 64 - 16
      const dragPixels = plotWidth * 0.1
      canvas.dispatchEvent(new MouseEvent('mousedown', {
        button: 0, clientX: 500, clientY: 160, bubbles: true, cancelable: true,
      }))
      window.dispatchEvent(new MouseEvent('mousemove', {
        clientX: 500 - dragPixels, clientY: 160, bubbles: true,
      }))
      window.dispatchEvent(new MouseEvent('mouseup', {
        button: 0, clientX: 500 - dragPixels, clientY: 160, bubbles: true,
      }))

      expect(timeline.offset).toBeCloseTo(0.5 + 0.1 / (100 - 1), 12)
      expect(runtime.probe.globalYView()).toEqual({
        zoom: 1, offset: 0, autoRange: true, manualMin: null, manualMax: null,
      })
      expect(runtime.probe.sharedYRange()).toEqual(beforeY)
    } finally {
      runtime.cleanup()
    }
  })

  it('pans both axes on a diagonal plain-left SuperWatch plot drag when X is zoomed', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2, 3).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()

      const canvas = document.getElementById('chart')!
      canvas.dispatchEvent(wheelEvent({
        deltaY: -100, shiftKey: true, clientX: 500, clientY: 160,
        bubbles: true, cancelable: true,
      }))
      const beforeTimelineOffset = runtime.probe.timeline().offset
      const beforeY = runtime.probe.sharedYRange()
      expect(runtime.probe.timeline().zoom).toBeGreaterThan(1)

      canvas.dispatchEvent(new MouseEvent('mousedown', {
        button: 0, clientX: 500, clientY: 160, bubbles: true, cancelable: true,
      }))
      window.dispatchEvent(new MouseEvent('mousemove', {
        clientX: 700, clientY: 220, bubbles: true,
      }))
      window.dispatchEvent(new MouseEvent('mouseup', {
        button: 0, clientX: 700, clientY: 220, bubbles: true,
      }))

      const afterY = runtime.probe.sharedYRange()
      expect(runtime.probe.timeline().offset).toBeLessThan(beforeTimelineOffset)
      expect(afterY.yMax - afterY.yMin).toBeCloseTo(beforeY.yMax - beforeY.yMin, 12)
      expect(afterY.yMin).toBeGreaterThan(beforeY.yMin)
      expect(afterY.yMax).toBeGreaterThan(beforeY.yMax)
      expect(runtime.probe.globalYView()).toMatchObject({
        autoRange: false, manualMin: afterY.yMin, manualMax: afterY.yMax,
      })
    } finally {
      runtime.cleanup()
    }
  })

  it('keeps cursor and trigger drags ahead of SuperWatch plot viewport panning', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 3_000_000n, itemCount: 3, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2, 3).buffer,
        times: Float64Array.of(0, 1, 2).buffer,
      })).toBe(true)
      runtime.viewer.renderBinaryFrame()

      const canvas = document.getElementById('chart')!
      canvas.dispatchEvent(wheelEvent({
        deltaY: -100, clientX: 400, clientY: 160, bubbles: true, cancelable: true,
      }))
      canvas.dispatchEvent(wheelEvent({
        deltaY: -100, shiftKey: true, clientX: 500, clientY: 160,
        bubbles: true, cancelable: true,
      }))

      const timeline = runtime.probe.timeline()
      const ring = runtime.probe.fields().A.ringBuf
      const fullMin = ring.oldest().t
      const fullMax = ring.latest().t
      const fullSpan = fullMax - fullMin
      const visibleSpan = fullSpan / timeline.zoom
      const visibleMin = fullMin + timeline.offset * (fullSpan - visibleSpan)
      runtime.probe.cursor.enabled = true
      runtime.probe.cursor.a = { t: visibleMin + visibleSpan / 2 }
      runtime.probe.cursor.b = { t: visibleMin + visibleSpan * 0.75 }
      runtime.viewer.renderBinaryFrame()
      const cursorX = Number.parseFloat(document.getElementById('cursor-a')!.style.left)
      const beforeCursorY = runtime.probe.sharedYRange()
      const beforeCursorOffset = timeline.offset

      canvas.dispatchEvent(new MouseEvent('mousedown', {
        button: 0, clientX: cursorX, clientY: 160, bubbles: true, cancelable: true,
      }))
      canvas.dispatchEvent(new MouseEvent('mousemove', {
        clientX: 500, clientY: 220, bubbles: true,
      }))
      window.dispatchEvent(new MouseEvent('mouseup', {
        button: 0, clientX: 500, clientY: 220, bubbles: true,
      }))
      expect(runtime.probe.sharedYRange()).toEqual(beforeCursorY)
      expect(timeline.offset).toBe(beforeCursorOffset)

      const triggerRange = runtime.probe.sharedYRange()
      runtime.probe.trigger.enabled = true
      runtime.probe.trigger.source = 'A'
      runtime.probe.trigger.level = (triggerRange.yMin + triggerRange.yMax) / 2
      runtime.viewer.renderBinaryFrame()
      const beforeTriggerY = runtime.probe.sharedYRange()
      const beforeTriggerOffset = timeline.offset

      canvas.dispatchEvent(new MouseEvent('mousedown', {
        button: 0, clientX: 400, clientY: 192, bubbles: true, cancelable: true,
      }))
      canvas.dispatchEvent(new MouseEvent('mousemove', {
        clientX: 300, clientY: 240, bubbles: true,
      }))
      window.dispatchEvent(new MouseEvent('mouseup', {
        button: 0, clientX: 300, clientY: 240, bubbles: true,
      }))
      expect(runtime.probe.sharedYRange()).toEqual(beforeTriggerY)
      expect(timeline.offset).toBe(beforeTriggerOffset)
    } finally {
      runtime.cleanup()
    }
  })

  it('disposes global viewer observers and listeners when the Vue view unmounts', () => {
    expect(componentSource).toContain('viewers?.[props.mode]?.dispose?.()')
    expect(source).toContain('var viewerAbortController = new AbortController();')
    expect(source).toContain('viewerResizeObserver.disconnect();')
    expect(source).toContain('viewerAbortController.abort();')
    expect(source).toContain('binaryViewer.dispose = disposeViewer;')
  })

  it('stops an active watch-column resize when the viewer is disposed', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime()
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      const resizer = document.querySelector(
        '#watch-table thead .watch-col-resizer[data-col="name"]',
      ) as HTMLElement | null
      const header = document.querySelector(
        '#watch-table thead th[data-col="name"]',
      ) as HTMLElement | null
      expect(resizer).not.toBeNull()
      expect(header).not.toBeNull()

      resizer?.dispatchEvent(new MouseEvent('mousedown', {
        bubbles: true,
        clientX: 100,
      }))
      const widthBeforeDispose = header?.style.width
      runtime.viewer.dispose()
      document.dispatchEvent(new MouseEvent('mousemove', {
        bubbles: true,
        clientX: 220,
      }))
      await new Promise(resolve => setTimeout(resolve, 20))

      expect(header?.style.width).toBe(widthBeforeDispose)
    } finally {
      runtime.cleanup()
    }
  })

  it('does not append DOM text, copy rings, or sort fields on each VOFA frame', () => {
    const processPoint = source.match(/function processPoint\(point\)[\s\S]*?\n}\n\n\/\//)?.[0] ?? ''
    const drawChart = source.match(/function drawChart\(\)[\s\S]*?\n}\n\n\/\//)?.[0] ?? ''
    const drawMinimap = source.match(/function drawMinimap\(\)[\s\S]*?\n}\n\n\/\//)?.[0] ?? ''
    expect(processPoint).not.toContain('rawLogEl.textContent +=')
    expect(drawChart).not.toContain('.ringBuf.toArray()')
    expect(drawMinimap).not.toContain('.ringBuf.toArray()')
    expect(source).not.toContain('Object.keys(FIELDS).sort()')
  })

  it('keeps project, cursor, trigger, and export controls wired', () => {
    for (const token of [
      'serializeState', 'deserializeState', 'exportCSV', 'exportPNG',
      'checkTrigger', 'cursor-a', 'cursor-b',
    ]) expect(source).toContain(token)
  })

  it('limits collection-boundary resets to VOFA and SuperWatch binary modes', () => {
    expect(source).toContain('var IS_BINARY_WAVEFORM_MODE = IS_VOFA_MODE || IS_SUPERWATCH_MODE;')
    expect(source).toContain("if (!IS_BINARY_WAVEFORM_MODE || typeof window === 'undefined'")
  })

  it('pauses only rendering without calling the backend pause endpoint', () => {
    const pauseHandler = source.match(/document\.getElementById\('btn-pause'\)\.addEventListener[\s\S]*?\n}\);/)?.[0] ?? ''
    expect(pauseHandler).toContain("updateCollectionUI(renderPaused ? 'paused' : 'running')")
    expect(pauseHandler).not.toContain("API_CTRL + action")
    expect(pauseHandler).not.toContain("fetch(")
  })

  it('stops collection directly and surfaces stop failures inline', () => {
    const stopHandler = viewerSource.match(/function stopCollection\(\)[\s\S]*?\n}/)?.[0] ?? ''
    expect(stopHandler).not.toContain('confirm(')
    expect(stopHandler).toContain('showControlError')
  })

  it('clears a stale render pause before starting a new acquisition', () => {
    const startHandler = source.match(/document\.getElementById\('btn-start'\)\.addEventListener[\s\S]*?\n}\);/)?.[0] ?? ''
    expect(startHandler).toContain('renderPaused = false;')
  })

  it('does not let SuperWatch status polling cancel a local render pause', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.probe.syncStatus({ state: 'running', items: [] })
      document.getElementById('btn-pause')!.click()
      expect(runtime.probe.collectionState()).toMatchObject({ state: 'paused', paused: true, renderPaused: true })

      runtime.probe.syncStatus({ state: 'running', items: [] })

      expect(runtime.probe.collectionState()).toMatchObject({ state: 'paused', paused: true, renderPaused: true })
    } finally {
      runtime.cleanup()
    }
  })

  it('shows capture invalidation from status and permits an explicit restart', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.probe.syncStatus({ state: 'running' })
      const error = 'DAP changed the target; restart capture after debugging.'
      runtime.probe.syncStatus({ state: 'stopped', error })
      expect(runtime.probe.collectionState().state).toBe('stopped')
      expect(document.getElementById('conn-status')!.textContent).toBe(error)
      expect((document.getElementById('btn-start') as HTMLButtonElement).disabled).toBe(false)
      expect((document.getElementById('btn-pause') as HTMLButtonElement).disabled).toBe(true)
    } finally {
      runtime.cleanup()
    }
  })

  it('freezes the SuperWatch viewport and envelope while render pause is active', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 8)
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 2_000_000_000n, itemCount: 2, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2).buffer,
        times: Float64Array.of(1_000, 2_000).buffer,
      })
      runtime.viewer.renderBinaryEnvelope({
        type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
        requestId: 1, pixelWidth: 100, channelCount: 1, pointCount: 2,
        candidateSampleCount: 2, times: Float64Array.of(1_000, 2_000).buffer,
        timeIndices: Uint32Array.of(0, 1).buffer, values: Float32Array.of(1, 2).buffer,
        channelOffsets: Uint32Array.of(0, 2).buffer,
      })
      runtime.probe.syncStatus({ state: 'running', items: [{ name: 'A' }] })
      document.getElementById('btn-pause')!.click()
      const frozenTime = runtime.probe.fullTimeRange()
      const frozenY = runtime.probe.sharedYRange()
      const frozenEnvelope = Array.from(runtime.probe.binaryEnvelope().values)

      runtime.viewer.acceptBinaryBatch({
        sequence: 2n, timestampNs: 4_000_000_000n, itemCount: 2, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1_000, 2_000).buffer,
        times: Float64Array.of(3_000, 4_000).buffer,
      })
      runtime.viewer.renderBinaryEnvelope({
        type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
        requestId: 2, pixelWidth: 100, channelCount: 1, pointCount: 2,
        candidateSampleCount: 2, times: Float64Array.of(3_000, 4_000).buffer,
        timeIndices: Uint32Array.of(0, 1).buffer, values: Float32Array.of(1_000, 2_000).buffer,
        channelOffsets: Uint32Array.of(0, 2).buffer,
      })
      const canvas = document.getElementById('chart') as HTMLCanvasElement
      canvas.onmouseleave?.({} as MouseEvent)
      canvas.onmousemove?.({ clientX: 400, clientY: 200 } as MouseEvent)

      expect(runtime.probe.fullTimeRange()).toEqual(frozenTime)
      expect(runtime.probe.sharedYRange()).toEqual(frozenY)
      expect(Array.from(runtime.probe.binaryEnvelope().values)).toEqual(frozenEnvelope)
    } finally {
      runtime.cleanup()
    }
  })

  it('reloads the requested SuperWatch envelope when the paused or stopped timeline moves', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 50_000)
    try {
      const requestVisibleRange = vi.fn()
      runtime.viewer.setBinaryVisibleRangeRequester(requestVisibleRange)
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      runtime.viewer.acceptBinarySummary({
        sequence: 1n, timestampNs: 8_000_000_000n,
        collectedItemCount: 8, bufferedItemCount: 8, channelCount: 1,
        bufferStartMs: 0, bufferEndMs: 8_000, latestTimeMs: 8_000,
        latestValues: Float32Array.of(8).buffer,
      })
      runtime.viewer.renderBinaryEnvelope({
        type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
        requestId: 1, pixelWidth: 800, channelCount: 1, pointCount: 4,
        candidateSampleCount: 4, times: Float64Array.of(4_000, 5_000, 6_000, 8_000).buffer,
        timeIndices: Uint32Array.of(0, 1, 2, 3).buffer,
        values: Float32Array.of(4, 5, 6, 8).buffer,
        channelOffsets: Uint32Array.of(0, 4).buffer,
      })
      runtime.probe.syncStatus({ state: 'running', items: [{ name: 'A' }] })
      document.getElementById('btn-pause')!.click()

      const axis = document.getElementById('x-axis-hit')!
      axis.dispatchEvent(wheelEvent({ deltaY: -100, clientX: 400, bubbles: true }))
      expect(requestVisibleRange).toHaveBeenCalledOnce()

      ;(window as any).__canvasPointVisits = 0
      const historicalEnvelope = {
        type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
        requestId: 2, pixelWidth: 800, channelCount: 1, pointCount: 4,
        candidateSampleCount: 4, times: Float64Array.of(2_000, 2_500, 3_000, 3_500).buffer,
        timeIndices: Uint32Array.of(0, 1, 2, 3).buffer,
        values: Float32Array.of(20, 25, 30, 35).buffer,
        channelOffsets: Uint32Array.of(0, 4).buffer,
      }
      expect(runtime.viewer.renderBinaryEnvelope(historicalEnvelope, true)).toBe(true)
      expect(Array.from(runtime.probe.binaryEnvelope().values)).toEqual([20, 25, 30, 35])
      expect((window as any).__canvasPointVisits).toBeGreaterThan(0)

      runtime.probe.syncStatus({ state: 'stopped', items: [{ name: 'A' }] })
      axis.dispatchEvent(wheelEvent({ deltaY: 100, clientX: 400, bubbles: true }))
      expect(requestVisibleRange).toHaveBeenCalledTimes(2)
      expect(Array.from(runtime.probe.binaryEnvelope().values)).toEqual([20, 25, 30, 35])
    } finally {
      runtime.cleanup()
    }
  })

  it('continues drawing the accepted binary envelope while SuperWatch is paused', () => {
    expect(viewerSource).not.toContain(
      'binaryEnvelope &&\n    !(IS_SUPERWATCH_MODE && paused)',
    )
  })

  it('retains only the latest SuperWatch row on the main thread while Worker bounds drive history', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 50_000)
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      expect(runtime.viewer.acceptBinarySummary({
        sequence: 1n, timestampNs: 1_000_000_000n, collectedItemCount: 512, bufferedItemCount: 512,
        channelCount: 2, bufferStartMs: 0, bufferEndMs: 1_000,
        latestTimeMs: 1_000, latestValues: Float32Array.of(1, 10).buffer,
      })).toBe(true)
      expect(runtime.viewer.acceptBinarySummary({
        sequence: 2n, timestampNs: 2_000_000_000n, collectedItemCount: 512, bufferedItemCount: 1_024,
        channelCount: 2, bufferStartMs: 0, bufferEndMs: 2_000,
        latestTimeMs: 2_000, latestValues: Float32Array.of(2, 20).buffer,
      })).toBe(true)

      const fields = runtime.probe.fields()
      expect(fields.A.ringBuf.count).toBe(1)
      expect(fields.B.ringBuf.count).toBe(1)
      expect(fields.A.ringBuf.capacity).toBe(2)
      expect(fields.B.ringBuf.capacity).toBe(2)
      expect(fields.A.ringBuf.latest().y).toBe(2)
      expect(fields.B.ringBuf.latest().y).toBe(20)
      expect(runtime.probe.fullTimeRange()).toEqual({ tMin: 0, tMax: 2 })
      expect(runtime.viewer.getStorageDiagnostics()).toMatchObject({
        historyOwner: 'worker', workerCapacity: 50_000, workerBufferedSamples: 1_024,
        mainRingCapacity: 2, mainRingMaxCount: 1, detailEnabled: false,
      })
      runtime.viewer.renderBinaryEnvelope({
        type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
        requestId: 1, pixelWidth: 800, channelCount: 2, pointCount: 4,
        candidateSampleCount: 1_024, times: Float64Array.of(1_000, 2_000).buffer,
        timeIndices: Uint32Array.of(0, 1, 0, 1).buffer,
        values: Float32Array.of(1, 2, 10, 20).buffer,
        channelOffsets: Uint32Array.of(0, 2, 4).buffer,
      })
      expect(document.getElementById('pts-count')!.textContent).toBe('1024 pts')
    } finally {
      runtime.cleanup()
    }
  })

  it('keeps the full SuperWatch history navigable while render pause is active', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch', 8)
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 8_000_000_000n, itemCount: 8, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.from({ length: 8 }, (_, index) => index + 1).buffer,
        times: Float64Array.from({ length: 8 }, (_, index) => index * 1_000).buffer,
      })
      runtime.viewer.renderBinaryEnvelope({
        type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
        requestId: 1, pixelWidth: 100, channelCount: 1, pointCount: 4,
        candidateSampleCount: 4, times: Float64Array.of(4_000, 5_000, 6_000, 7_000).buffer,
        timeIndices: Uint32Array.of(0, 1, 2, 3).buffer,
        values: Float32Array.of(5, 6, 7, 8).buffer,
        channelOffsets: Uint32Array.of(0, 4).buffer,
      })
      runtime.probe.syncStatus({ state: 'running', items: [{ name: 'A' }] })
      document.getElementById('btn-pause')!.click()

      runtime.viewer.acceptBinaryBatch({
        sequence: 2n, timestampNs: 16_000_000_000n, itemCount: 8, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.from({ length: 8 }, (_, index) => index + 9).buffer,
        times: Float64Array.from({ length: 8 }, (_, index) => (index + 8) * 1_000).buffer,
      })

      const ring = runtime.probe.fields().A.ringBuf
      expect(ring.count).toBe(8)
      expect(ring.oldest().y).toBe(1)
      expect(ring.latest().y).toBe(8)
      expect(runtime.probe.binary().lastSequence).toBe(2n)

      const canvas = document.getElementById('chart') as HTMLCanvasElement
      ;(window as any).__ringPointVisits = 0
      canvas.onmousedown?.({
        button: 0, altKey: true, clientX: 100, clientY: 200,
        preventDefault: vi.fn(),
      } as unknown as MouseEvent)
      canvas.onmousemove?.({ clientX: 1_600, clientY: 200 } as MouseEvent)
      window.dispatchEvent(new MouseEvent('mouseup', {
        button: 0, clientX: 1_600, clientY: 200, bubbles: true,
      }))

      expect(runtime.probe.timeline().offset).toBe(0)
      expect((window as any).__ringPointVisits).toBe(0)

      document.getElementById('btn-pause')!.click()
      expect(ring.count).toBe(0)
      runtime.viewer.acceptBinaryBatch({
        sequence: 3n, timestampNs: 18_000_000_000n, itemCount: 2, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(17, 18).buffer,
        times: Float64Array.of(16_000, 17_000).buffer,
      })
      expect(ring.count).toBe(2)
      expect(ring.latest().y).toBe(18)
    } finally {
      runtime.cleanup()
    }
  })

  it('does not trigger viewer shortcuts while typing in the variable search input', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    const runtime = await loadRttViewerRuntime('SuperWatch')
    const search = document.createElement('input')
    search.dataset.testid = 'variable-search'
    document.body.appendChild(search)
    try {
      runtime.probe.setRawLogOpen(false)
      const event = new KeyboardEvent('keydown', {
        key: 'L', bubbles: true, cancelable: true,
      })

      search.dispatchEvent(event)

      expect(event.defaultPrevented).toBe(false)
      expect(document.getElementById('raw-log-panel')?.dataset.open).toBe('false')
    } finally {
      search.remove()
      runtime.cleanup()
    }
  })

  it('records selected SuperWatch values with timestamps and saves the raw log', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    const createObjectURL = vi.fn(() => 'blob:superwatch-log')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'gain' }, { name: 'target' }])
      runtime.probe.setRawLogOpen(true)
      runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 1_700_000_000_100_000_000n,
        itemCount: 2, channelCount: 2, layout: 'sample-major-float32',
        values: Float32Array.of(1, 10, 1.25, 20).buffer,
        times: Float64Array.of(1_700_000_000_000, 1_700_000_000_100).buffer,
      })

      const lines = runtime.probe.rawLogState().lines
      expect(lines).toHaveLength(2)
      expect(lines[0]).toMatch(/^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] gain=1, target=10$/)
      expect(lines[1]).toContain('gain=1.25, target=20')
      runtime.probe.saveRawLog()
      expect(createObjectURL).toHaveBeenCalledOnce()
      expect(click).toHaveBeenCalledOnce()
      expect(document.getElementById('raw-log-save')).not.toBeNull()
    } finally {
      click.mockRestore()
      vi.unstubAllGlobals()
      runtime.cleanup()
    }
  })

  it('routes SuperWatch CSV and raw-log exports through the desktop save bridge', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    const nativeSave = vi.fn().mockResolvedValue(true)
    ;(window as any).__MKLINK_SAVE_FILE__ = nativeSave
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'gain' }])
      runtime.probe.setRawLogOpen(true)
      runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 1_000_000_000n,
        itemCount: 2, channelCount: 1, layout: 'sample-major-float32',
        values: Float32Array.of(1, 1.25).buffer,
        times: Float64Array.of(1_000, 2_000).buffer,
      })

      runtime.probe.saveRawLog()
      runtime.probe.exportCSV()
      await Promise.resolve()

      expect(nativeSave).toHaveBeenCalledTimes(2)
      expect(nativeSave.mock.calls[0][0]).toMatch(/^superwatch-raw-\d{8}-\d{6}\.txt$/)
      expect(nativeSave.mock.calls[0][1]).toContain('gain=1.25')
      expect(nativeSave.mock.calls[1][0]).toBe('jscope_export.csv')
      expect(nativeSave.mock.calls[1][1]).toContain('timestamp,gain')
    } finally {
      runtime.cleanup()
    }
  })

  it('shows an invalid SuperWatch symbol error inline without a blocking alert', async () => {
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    const runtime = await loadRttViewerRuntime('SuperWatch')
    const alertSpy = vi.fn()
    vi.stubGlobal('alert', alertSpy)
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        item: {
          error: "Cannot resolve 'temp1': skipped (address outside SRAM or not found)",
        },
      }),
    } as Response)
    try {
      runtime.probe.addSuperwatchName('temp1')
      await new Promise(resolve => setTimeout(resolve, 0))
      runtime.probe.syncStatus({ state: 'running', items: [] })

      expect(document.getElementById('conn-status')?.textContent)
        .toBe('无法监视“temp1”：符号不存在或地址不在 SRAM 范围内。')
      expect(alertSpy).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllGlobals()
      runtime.cleanup()
    }
  })
})

describe('VOFA viewer typed-ring runtime', () => {
  it('preserves configured waveform fields when status omits channel metadata', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      const channels = [{ name: 'A' }, { name: 'B' }]
      runtime.viewer.configureBinaryChannels(channels)

      runtime.probe.syncStatus({ running: true, interval: 0.00001, channels })

      expect(Object.keys(runtime.probe.fields())).toEqual(['A', 'B'])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 2_000_000n, itemCount: 2, channelCount: 2,
        layout: 'sample-major-float32', values: Float32Array.of(1, 10, 2, 20).buffer,
        times: Float64Array.of(0, 1).buffer,
      }, channels)).toBe(true)
      expect(runtime.probe.fields().A.ringBuf.count).toBe(2)
      expect(runtime.probe.fields().B.ringBuf.count).toBe(2)
    } finally {
      runtime.cleanup()
    }
  })

  it('updates the VOFA watch table at no more than 5 Hz while envelopes render at 30 FPS', async () => {
    const runtime = await loadRttViewerRuntime()
    const now = vi.spyOn(performance, 'now').mockReturnValue(0)
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 1_000_000n, itemCount: 2, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2).buffer,
        times: Float64Array.of(0, 1).buffer,
      })).toBe(true)
      const envelope = {
        type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
        requestId: 1, pixelWidth: 100, channelCount: 1, pointCount: 2,
        candidateSampleCount: 2, times: Float64Array.of(0, 1).buffer,
        timeIndices: Uint32Array.of(0, 1).buffer, values: Float32Array.of(1, 2).buffer,
        channelOffsets: Uint32Array.of(0, 2).buffer,
      }
      ;(window as any).__watchTableUpdates = 0
      for (let frame = 0; frame < 30; frame++) {
        now.mockReturnValue(frame * (1_000 / 30))
        runtime.viewer.renderBinaryEnvelope(envelope)
      }
      expect((window as any).__watchTableUpdates).toBeLessThanOrEqual(5)
    } finally {
      now.mockRestore()
      runtime.cleanup()
    }
  })

  it('finds the first nearest logical sample for empty, repeated, and wrapped rings', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      const RingBuffer = runtime.probe.RingBuffer
      const empty = new RingBuffer(4)
      expect(empty.nearestSample(1)).toBeNull()

      const repeated = new RingBuffer(5)
      repeated.push(1, 10)
      repeated.push(2, 20)
      repeated.push(2, 21)
      repeated.push(3, 30)
      expect(repeated.nearestSample(2)).toEqual({ index: 1, time: 2, value: 20, distance: 0 })
      expect(repeated.nearestSample(2.5)).toEqual({ index: 1, time: 2, value: 20, distance: 0.5 })

      const wrapped = new RingBuffer(4)
      for (let time = 1; time <= 6; time++) wrapped.push(time, time * 10)
      expect(wrapped.nearestSample(4.4)).toEqual({
        index: 1, time: 4, value: 40, distance: expect.closeTo(0.4),
      })
    } finally {
      runtime.cleanup()
    }
  })

  it('maintains exact extrema without full rescans during 200k x 8 ramp overwrite', async () => {
    const capacity = 200_000
    const channelCount = 8
    const appended = 512
    const runtime = await loadRttViewerRuntime('VOFA', capacity)
    try {
      const channels = Array.from({ length: channelCount }, (_, index) => ({ name: `R${index}` }))
      runtime.viewer.configureBinaryChannels(channels)
      const initialTimes = new Float64Array(capacity)
      const initialValues = new Float32Array(capacity * channelCount)
      for (let sample = 0; sample < capacity; sample++) {
        initialTimes[sample] = sample
        for (let channel = 0; channel < channelCount; channel++) {
          initialValues[sample * channelCount + channel] = sample + channel / 10
        }
      }
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 200_000_000_000n, itemCount: capacity,
        channelCount, layout: 'sample-major-float32', values: initialValues.buffer,
        times: initialTimes.buffer,
      })).toBe(true)

      let fullRescans = 0
      for (const channel of channels) {
        runtime.probe.fields()[channel.name].ringBuf.recomputeStats = () => { fullRescans++ }
      }
      const nextTimes = new Float64Array(appended)
      const nextValues = new Float32Array(appended * channelCount)
      for (let sample = 0; sample < appended; sample++) {
        nextTimes[sample] = capacity + sample
        for (let channel = 0; channel < channelCount; channel++) {
          nextValues[sample * channelCount + channel] = capacity + sample + channel / 10
        }
      }
      const started = performance.now()
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 2n, timestampNs: 200_512_000_000n, itemCount: appended,
        channelCount, layout: 'sample-major-float32', values: nextValues.buffer,
        times: nextTimes.buffer,
      })).toBe(true)
      const elapsedMs = performance.now() - started

      expect(fullRescans).toBe(0)
      for (let channel = 0; channel < channelCount; channel++) {
        const ring = runtime.probe.fields()[`R${channel}`].ringBuf
        expect(ring.count).toBe(capacity)
        expect(ring._min).toBe(Math.fround(appended + channel / 10))
        expect(ring._max).toBe(Math.fround(capacity + appended - 1 + channel / 10))
      }
      expect(elapsedMs).toBeLessThan(500)
    } finally {
      runtime.cleanup()
    }
  })

  it('keeps legacy NaN extrema semantics across overwrite and clear', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      const RingBuffer = runtime.probe.RingBuffer
      const ring = new RingBuffer(3)
      ring.push(1, Number.NaN)
      ring.push(2, 5)
      ring.push(3, -2)
      expect({ min: ring._min, max: ring._max, count: ring._count }).toEqual({
        min: -2, max: 5, count: 2,
      })
      ring.push(4, 7)
      ring.push(5, Number.NaN)
      ring.push(6, 9)
      expect({ min: ring._min, max: ring._max, count: ring._count }).toEqual({
        min: 7, max: 9, count: 2,
      })
      ring.clear()
      expect({ min: ring._min, max: ring._max, count: ring._count }).toEqual({
        min: Infinity, max: -Infinity, count: 0,
      })
    } finally {
      runtime.cleanup()
    }
  })

  it('bounds 200k x 8 hover and ctrl-wheel lookups to logarithmic ring visits', async () => {
    const sampleCount = 200_000
    const channelCount = 8
    const runtime = await loadRttViewerRuntime('VOFA', sampleCount)
    try {
      const channels = Array.from({ length: channelCount }, (_, index) => ({ name: `I${index}` }))
      runtime.viewer.configureBinaryChannels(channels)
      const times = new Float64Array(sampleCount)
      const values = new Float32Array(sampleCount * channelCount)
      for (let sample = 0; sample < sampleCount; sample++) {
        times[sample] = sample / 10
        for (let channel = 0; channel < channelCount; channel++) {
          values[sample * channelCount + channel] = sample + channel / 10
        }
      }
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 20_000_000_000n, itemCount: sampleCount,
        channelCount, layout: 'sample-major-float32', values: values.buffer,
        times: times.buffer,
      })).toBe(true)

      const envelopeTimes = Float64Array.of(times[0], times[sampleCount - 1])
      const pointCount = channelCount * 2
      const timeIndices = new Uint32Array(pointCount)
      const envelopeValues = new Float32Array(pointCount)
      const channelOffsets = new Uint32Array(channelCount + 1)
      for (let channel = 0; channel < channelCount; channel++) {
        const offset = channel * 2
        channelOffsets[channel] = offset
        timeIndices[offset] = 0
        timeIndices[offset + 1] = 1
        envelopeValues[offset] = channel / 10
        envelopeValues[offset + 1] = sampleCount - 1 + channel / 10
      }
      channelOffsets[channelCount] = pointCount
      expect(runtime.viewer.renderBinaryEnvelope({
        type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
        requestId: 1, pixelWidth: 800, channelCount, pointCount,
        candidateSampleCount: sampleCount, times: envelopeTimes.buffer,
        timeIndices: timeIndices.buffer, values: envelopeValues.buffer,
        channelOffsets: channelOffsets.buffer,
      })).toBe(true)

      const canvas = document.getElementById('chart') as HTMLCanvasElement
      runtime.probe.hover.active = true
      ;(window as any).__ringPointVisits = 0
      canvas.onmousemove?.({ clientX: 400, clientY: 200 } as MouseEvent)
      const hoverVisits = (window as any).__ringPointVisits
      expect(hoverVisits).toBeLessThanOrEqual(channelCount * 48)
      expect(document.getElementById('tooltip')?.textContent).toContain('I0')

      ;(window as any).__ringPointVisits = 0
      canvas.onwheel?.({
        clientX: 400, clientY: 200, ctrlKey: true, shiftKey: false,
        deltaY: -1, preventDefault: vi.fn(),
      } as unknown as WheelEvent)
      const wheelVisits = (window as any).__ringPointVisits
      console.info('[vofa-interaction-gate]', JSON.stringify({ hoverVisits, wheelVisits }))
      expect(wheelVisits).toBeLessThanOrEqual(channelCount * 48)
      expect(runtime.probe.channelYState().I0.zoom).toBe(1.25)
      expect(runtime.probe.channelYState().I1.zoom).toBe(1)
    } finally {
      runtime.cleanup()
    }
  })

  it('keeps closed raw logs DOM-cold and paints its fixed ring at no more than 10 Hz', async () => {
    const runtime = await loadRttViewerRuntime()
    const now = vi.spyOn(performance, 'now').mockReturnValue(0)
    try {
      const raw = document.getElementById('raw-log')!
      const count = document.getElementById('raw-log-count')!
      let writes = 0
      let rawText = raw.textContent
      let countText = count.textContent
      Object.defineProperty(raw, 'textContent', {
        configurable: true, get: () => rawText,
        set: value => { writes++; rawText = String(value) },
      })
      Object.defineProperty(count, 'textContent', {
        configurable: true, get: () => countText,
        set: value => { writes++; countText = String(value) },
      })
      for (let index = 0; index < 5001; index++) runtime.probe.appendRawLog(`line-${index}`)
      expect(writes).toBe(0)
      expect(runtime.probe.rawLogState()).toMatchObject({ count: 5000, total: 5001 })
      expect(runtime.probe.rawLogState().lines.slice(0, 2)).toEqual(['line-1', 'line-2'])

      runtime.probe.setRawLogOpen(true)
      writes = 0
      for (let index = 0; index < 100; index++) runtime.probe.appendRawLog(`burst-${index}`)
      expect(writes).toBe(0)
      now.mockReturnValue(101)
      runtime.probe.appendRawLog('paint')
      expect(writes).toBe(2)
    } finally {
      now.mockRestore()
      runtime.cleanup()
    }
  })

  it('shows backend actual rate and binary transport health without interval estimation', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      runtime.probe.syncStatus({ running: true, interval: 0.1, actual_rate: 9.75, channels: [] })
      expect(document.getElementById('sample-rate-badge')?.textContent).toContain('9.75 Hz')
      runtime.probe.syncStatus({ running: false, interval: 0.1, actual_rate: 0, channels: [] })
      expect(document.getElementById('sample-rate-badge')?.textContent).toContain('0.00 Hz')

      runtime.viewer.updateBinaryHealth({
        phase: 'connected', bufferedSamples: 200000, transportDroppedBatches: 1,
        backendDroppedBatches: 3, backendDroppedItems: 80, error: null,
      })
      expect(document.getElementById('transport-state-badge')?.textContent).toContain('connected')
      expect(document.getElementById('transport-health-badge')?.textContent).toContain('transport 1')
      expect(document.getElementById('transport-health-badge')?.textContent).toContain('backend 3/80')
      expect(document.getElementById('transport-health-badge')?.textContent).toContain('buffer 200000')
      expect(document.getElementById('transport-health-badge')?.title)
        .toBe('transport 1 / backend 3/80 / buffer 200000')
      expect(document.getElementById('transport-health-badge')?.className).toContain('badge-warn')
    } finally {
      runtime.cleanup()
    }
  })

  it('sustains a 60-second 10 kHz x 8 Worker/viewer run with 30 FPS bounded envelopes', async () => {
    const durationSeconds = 60
    const sampleRate = 10_000
    const channelCount = 8
    const batchSamples = 2_000
    const pixelWidth = 320
    const runtime = await loadRttViewerRuntime('VOFA', 200_000)
    try {
      runtime.viewer.configureBinaryChannels(
        Array.from({ length: channelCount }, (_, index) => ({ name: `P${index}` })),
      )
      let errors = 0
      let rejectedBatches = 0
      let acceptedFrames = 0
      let bufferedSamples = 0
      let transportDroppedBatches = 0
      let backendDroppedBatches = 0
      let backendDroppedItems = 0
      let renderRequests = 0
      let maxPointCount = 0
      let maxCandidateSamples = 0
      let maxRingVisits = 0
      let maxCanvasVisits = 0
      const decoder = new StreamDecoder((message: WorkerOutput) => {
        if (message.type === 'error') errors++
        if (message.type === 'telemetry') {
          acceptedFrames = message.acceptedFrames
          bufferedSamples = message.bufferedSamples
          transportDroppedBatches = message.transportDroppedBatches
          backendDroppedBatches = message.backendDroppedBatches
          backendDroppedItems = message.backendDroppedItems
        }
        if (message.type === 'waveform-batch' && !runtime.viewer.acceptBinaryBatch(message)) {
          rejectedBatches++
        }
        if (message.type === 'render-envelope') {
          renderRequests++
          maxPointCount = Math.max(maxPointCount, message.pointCount)
          maxCandidateSamples = Math.max(maxCandidateSamples, message.candidateSampleCount)
          ;(window as any).__ringPointVisits = 0
          ;(window as any).__canvasPointVisits = 0
          if (!runtime.viewer.renderBinaryEnvelope(message)) errors++
          maxRingVisits = Math.max(maxRingVisits, (window as any).__ringPointVisits)
          maxCanvasVisits = Math.max(maxCanvasVisits, (window as any).__canvasPointVisits)
        }
      })
      decoder.handle({ type: 'configure', capacity: 200_000, channelCount })
      const raw = document.getElementById('raw-log')!
      const rawCount = document.getElementById('raw-log-count')!
      let rawDomWrites = 0
      let rawText = raw.textContent
      let rawCountText = rawCount.textContent
      Object.defineProperty(raw, 'textContent', {
        configurable: true, get: () => rawText,
        set: value => { rawDomWrites++; rawText = String(value) },
      })
      Object.defineProperty(rawCount, 'textContent', {
        configurable: true, get: () => rawCountText,
        set: value => { rawDomWrites++; rawCountText = String(value) },
      })
      // Do not include a growing canvas-label transcript in the memory gate.
      ;(window as any).__canvasLabels = undefined
      // The accelerated loop delivers 60 seconds without idle time. Collect
      // before the baseline and once per simulated second so raw heap peaks
      // do not depend on the host's V8 heap expansion/GC schedule. Keep sampling
      // BEFORE collection and preserve the existing allocation limits.
      if (!globalThis.gc) throw new Error('The memory gate requires --expose-gc')
      globalThis.gc()
      const baseline = process.memoryUsage()
      let peakHeap = baseline.heapUsed
      let seed = 0x12345678
      let requestId = 0
      const batchCount = durationSeconds * sampleRate / batchSamples
      const requestsPerBatch = 30 * batchSamples / sampleRate
      const started = performance.now()
      for (let batch = 0; batch < batchCount; batch++) {
        const values = new Float32Array(batchSamples * channelCount)
        for (let index = 0; index < values.length; index++) {
          seed ^= seed << 13
          seed ^= seed >>> 17
          seed ^= seed << 5
          values[index] = (seed >>> 0) / 0xffffffff * 2 - 1
        }
        const endMs = (batch + 1) * batchSamples / sampleRate * 1_000
        decoder.handle({
          type: 'frame',
          buffer: waveformFrame(BigInt(batch + 1), batchSamples, BigInt(Math.round(endMs * 1_000_000)), values),
          connectionGeneration: 1,
          frameTicket: batch + 1,
        })
        for (let render = 0; render < requestsPerBatch; render++) {
          decoder.handle({
            type: 'visible-range', requestId: ++requestId,
            start: Math.max(0, endMs - 1_000), end: endMs, pixelWidth,
          })
        }
        peakHeap = Math.max(peakHeap, process.memoryUsage().heapUsed)
        if ((batch + 1) % (sampleRate / batchSamples) === 0) globalThis.gc()
      }
      const elapsedMs = performance.now() - started
      const finalMemory = process.memoryUsage()
      console.info('[vofa-60s-gate]', JSON.stringify({
        elapsedMs: Math.round(elapsedMs), acceptedFrames, bufferedSamples,
        renderRequests, maxCandidateSamples, maxPointCount,
        maxRingVisits, maxCanvasVisits, rawDomWrites, errors, rejectedBatches,
        transportDroppedBatches, backendDroppedBatches, backendDroppedItems,
        peakHeapGrowth: peakHeap - baseline.heapUsed,
        arrayBufferGrowth: finalMemory.arrayBuffers - baseline.arrayBuffers,
      }))

      expect(errors).toBe(0)
      expect(rejectedBatches).toBe(0)
      expect(transportDroppedBatches).toBe(0)
      expect(backendDroppedBatches).toBe(0)
      expect(backendDroppedItems).toBe(0)
      expect(acceptedFrames).toBe(batchCount)
      expect(bufferedSamples).toBe(200_000)
      expect(rawDomWrites).toBe(0)
      expect(renderRequests).toBe(durationSeconds * 30)
      expect(maxCandidateSamples).toBeLessThanOrEqual(sampleRate + batchSamples)
      expect(maxPointCount).toBeLessThanOrEqual(2 * pixelWidth * channelCount)
      expect(maxRingVisits).toBe(0)
      expect(maxCanvasVisits).toBeLessThanOrEqual(2 * maxPointCount + 100)
      expect(elapsedMs).toBeLessThan(60_000)
      expect(peakHeap - baseline.heapUsed).toBeLessThan(192 * 1024 * 1024)
      expect(finalMemory.arrayBuffers - baseline.arrayBuffers).toBeLessThan(128 * 1024 * 1024)
    } finally {
      runtime.cleanup()
    }
  }, 90_000)

  it('runs an accelerated 60-second SuperWatch metadata/sample Worker/viewer envelope gate', async () => {
    const durationSeconds = 60
    const sampleRate = 10_000
    const channelCount = 8
    const batchSamples = 2_000
    const pixelWidth = 320
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.envelope = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.binary.state = shallowRef({ phase: 'stopped' })
    mocks.binary.error = shallowRef(null)
    mocks.binary.superwatchMetadata = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
    ;(window as any).__waveformViewers = {}
    const runtime = await loadRttViewerRuntime('SuperWatch', 200_000)
    try {
      let errors = 0
      let rejectedBatches = 0
      let bufferedSamples = 0
      let renderRequests = 0
      let maxPointCount = 0
      const decoder = new StreamDecoder((message: WorkerOutput) => {
        if (message.type === 'error') errors++
        if (message.type === 'superwatch-metadata') {
          runtime.viewer.configureBinaryChannels(message.channels)
        }
        if (message.type === 'waveform-batch' && !runtime.viewer.acceptBinaryBatch(message)) {
          rejectedBatches++
        }
        if (message.type === 'telemetry') bufferedSamples = message.bufferedSamples
        if (message.type === 'render-envelope') {
          renderRequests++
          maxPointCount = Math.max(maxPointCount, message.pointCount)
          if (!runtime.viewer.renderBinaryEnvelope(message)) errors++
        }
      })
      decoder.handle({ type: 'configure', capacity: 200_000, channelCount: 1 })
      const metadata = new TextEncoder().encode(JSON.stringify({
        version: 1,
        channels: Array.from({ length: channelCount }, (_, index) => ({ name: `S${index}` })),
      }))
      decoder.handle({
        type: 'frame',
        buffer: superwatchFrame(1n, 0, 1n, metadata, 2),
        connectionGeneration: 1, frameTicket: 1,
      })
      const batchCount = durationSeconds * sampleRate / batchSamples
      for (let batch = 0; batch < batchCount; batch++) {
        const values = new Float32Array(batchSamples * channelCount)
        for (let index = 0; index < values.length; index++) {
          values[index] = (batch * batchSamples + index) % 10_000
        }
        const endMs = (batch + 1) * batchSamples / sampleRate * 1_000
        decoder.handle({
          type: 'frame',
          buffer: superwatchFrame(
            BigInt(batch + 2), batchSamples, BigInt(Math.round(endMs * 1_000_000)),
            new Uint8Array(values.buffer), 1,
          ),
          connectionGeneration: 1, frameTicket: batch + 2,
        })
      }
      decoder.handle({
        type: 'visible-range', requestId: 1,
        start: durationSeconds * 1_000 - 1_000,
        end: durationSeconds * 1_000,
        pixelWidth,
      })

      expect(errors).toBe(0)
      expect(rejectedBatches).toBe(0)
      expect(bufferedSamples).toBe(200_000)
      expect(runtime.probe.fields().S0.ringBuf.count).toBe(200_000)
      expect(renderRequests).toBe(1)
      expect(maxPointCount).toBeLessThanOrEqual(2 * pixelWidth * channelCount)
    } finally {
      runtime.cleanup()
    }
  }, 90_000)

  it.each(['VOFA', 'SuperWatch'] as const)(
    'renders a 200k x 8 %s snapshot from a bounded envelope without scanning rings', async mode => {
    const sampleCount = 200_000
    const channelCount = 8
    const pixelWidth = 800
    const runtime = await loadRttViewerRuntime(mode, sampleCount)
    try {
      const channels = Array.from({ length: channelCount }, (_, index) => ({ name: `C${index}` }))
      runtime.viewer.configureBinaryChannels(channels)
      const times = new Float64Array(sampleCount)
      const values = new Float32Array(sampleCount * channelCount)
      for (let sample = 0; sample < sampleCount; sample++) {
        times[sample] = sample / 10
        for (let channel = 0; channel < channelCount; channel++) {
          values[sample * channelCount + channel] = sample + channel
        }
      }
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 20_000_000_000n, itemCount: sampleCount,
        channelCount, layout: 'sample-major-float32', values: values.buffer,
        times: times.buffer,
      })).toBe(true)

      const pointsPerChannel = 2 * pixelWidth
      const pointCount = pointsPerChannel * channelCount
      const selectedTimes = Float64Array.from(
        { length: pointsPerChannel }, (_, index) => index * 100,
      )
      const timeIndices = new Uint32Array(pointCount)
      const envelopeValues = new Float32Array(pointCount)
      const channelOffsets = new Uint32Array(channelCount + 1)
      for (let channel = 0; channel < channelCount; channel++) {
        channelOffsets[channel] = channel * pointsPerChannel
        for (let point = 0; point < pointsPerChannel; point++) {
          const offset = channel * pointsPerChannel + point
          timeIndices[offset] = point
          envelopeValues[offset] = point + channel
        }
      }
      channelOffsets[channelCount] = pointCount
      ;(window as any).__ringPointVisits = 0
      ;(window as any).__canvasPointVisits = 0

      runtime.viewer.renderBinaryEnvelope({
        type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
        requestId: 1, pixelWidth, channelCount, pointCount,
        candidateSampleCount: sampleCount, times: selectedTimes.buffer,
        timeIndices: timeIndices.buffer, values: envelopeValues.buffer,
        channelOffsets: channelOffsets.buffer,
      })

      expect(pointCount).toBeLessThanOrEqual(2 * pixelWidth * channelCount)
      expect((window as any).__ringPointVisits).toBe(0)
      expect((window as any).__canvasPointVisits).toBeLessThanOrEqual(2 * pointCount + 100)
    } finally {
      runtime.cleanup()
    }
    },
  )

  it('rearms an enabled SuperWatch trigger with detail after every acquisition reset', async () => {
    mocks.useBinaryStream.mockReturnValue({
      ...mocks.binary, waveformBatch: shallowRef(null), envelope: shallowRef(null),
      telemetry: shallowRef(null), state: shallowRef({ phase: 'stopped' }),
      error: shallowRef(null), superwatchMetadata: shallowRef(null),
    })
    const runtime = await loadRttViewerRuntime('SuperWatch', 32)
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      const detail = vi.fn()
      runtime.viewer.setBinaryDetailRequester(detail)
      Object.assign(runtime.probe.trigger, { source: 'A', mode: 'single', preTriggerSamples: 2 })
      document.getElementById('trigger-enable-btn')!.click()
      for (let run = 0; run < 2; run++) {
        runtime.probe.syncStatus({ state: 'running' })
        runtime.viewer.resetBinaryStream()
        expect(runtime.probe.trigger.state).toBe('armed')
        expect(detail).toHaveBeenLastCalledWith(true)
        expect(runtime.viewer.acceptBinaryBatch({
          sequence: 1n, timestampNs: 5_000_000n, itemCount: 5, channelCount: 1,
          layout: 'sample-major-float32', values: Float32Array.of(-2, -1, 1, 2, 3).buffer,
          times: Float64Array.of(1, 2, 3, 4, 5).buffer,
        })).toBe(true)
        expect(runtime.probe.trigger.state).toBe('done')
        expect(detail).toHaveBeenLastCalledWith(false)
        expect(runtime.probe.fields().A.ringBuf.toArray().map((p: any) => p.y)).toEqual([-2, -1, 1, 2, 3])
        const capturedRange = runtime.probe.fullTimeRange()
        expect(capturedRange.tMax - capturedRange.tMin).toBeCloseTo(0.004)
        runtime.viewer.acceptBinarySummary({
          sequence: 99n, channelCount: 1, latestTimeMs: 9_000,
          bufferStartMs: 0, bufferEndMs: 9_000,
          latestValues: Float32Array.of(99).buffer,
        })
        runtime.viewer.renderBinaryEnvelope({ invalid: 'late pending render' }, true)
        expect(runtime.probe.fullTimeRange()).toEqual(capturedRange)
        expect(runtime.probe.fields().A.ringBuf.count).toBe(5)
        expect(runtime.viewer.getBinaryVisibleRange()).toBeNull()
        await new Promise(resolve => setTimeout(resolve, 0))
        expect(runtime.probe.collectionState().state).toBe('stopped')
        expect(fetch).toHaveBeenCalledWith('/api/dash/superwatch/stop', { method: 'POST' })
      }
      document.getElementById('trigger-enable-btn')!.click()
      runtime.viewer.resetBinaryStream()
      expect(runtime.probe.trigger.state).toBe('idle')
      expect(detail).toHaveBeenLastCalledWith(false)
    } finally {
      runtime.cleanup()
    }
  })

  it('freezes 16 channels at 100 pre + crossing + 100 post samples and retains them if stop fails', async () => {
    mocks.useBinaryStream.mockReturnValue({
      ...mocks.binary, waveformBatch: shallowRef(null), envelope: shallowRef(null),
      telemetry: shallowRef(null), state: shallowRef({ phase: 'stopped' }),
      error: shallowRef(null), superwatchMetadata: shallowRef(null),
    })
    const runtime = await loadRttViewerRuntime('SuperWatch', 32)
    try {
      await new Promise(resolve => setTimeout(resolve, 0))
      runtime.viewer.configureBinaryChannels(Array.from({ length: 16 }, (_, i) => ({ name: `wave[${i}]` })))
      Object.assign(runtime.probe.trigger, { source: 'wave[0]', mode: 'single', preTriggerSamples: 100 })
      document.getElementById('trigger-enable-btn')!.click()
      runtime.probe.syncStatus({ state: 'running' })
      runtime.viewer.resetBinaryStream()
      let failStop = true
      vi.mocked(fetch).mockImplementation(async url => {
        if (String(url).endsWith('/stop') && failStop) {
          failStop = false
          return { ok: false, status: 503, json: async () => ({ detail: 'stop failed' }) } as Response
        }
        return { ok: true, json: async () => ({}) } as Response
      })
      const send = (sequence: bigint, first: number, count: number) => runtime.viewer.acceptBinaryBatch({
        sequence, timestampNs: BigInt(first + count) * 1_000_000n, itemCount: count, channelCount: 16,
        layout: 'sample-major-float32',
        values: Float32Array.from({ length: count * 16 }, (_, i) => first + Math.floor(i / 16) - 199.5 + (i % 16) * 1000).buffer,
        times: Float64Array.from({ length: count }, (_, i) => first + i).buffer,
      })
      send(1n, 0, 200)
      expect(runtime.probe.trigger.state).toBe('armed')
      send(2n, 200, 110)
      expect(runtime.probe.trigger.state).toBe('done')
      send(3n, 310, 100)
      for (let channel = 0; channel < 16; channel++) {
        const ring = runtime.probe.fields()[`wave[${channel}]`].ringBuf
        expect(ring.count).toBe(201)
        expect(ring.valueAt(0)).toBe(-99.5 + channel * 1000)
        expect(ring.valueAt(200)).toBe(100.5 + channel * 1000)
      }
      await new Promise(resolve => setTimeout(resolve, 0))
      expect(runtime.probe.collectionState()).toMatchObject({ state: 'paused', paused: true })
      expect(document.getElementById('conn-status')?.textContent).toContain('stop failed')
      document.getElementById('btn-stop')!.click()
      await new Promise(resolve => setTimeout(resolve, 0))
      expect(runtime.probe.collectionState().state).toBe('stopped')
      expect(runtime.probe.fields()['wave[0]'].ringBuf.count).toBe(201)
      const save = vi.fn()
      const previousSave = (window as any).__MKLINK_SAVE_FILE__
      ;(window as any).__MKLINK_SAVE_FILE__ = save
      try {
        runtime.probe.exportCSV()
        expect(save).toHaveBeenCalledOnce()
        const rows = String(save.mock.calls[0][1]).split('\n')
        expect(rows).toHaveLength(202)
        expect(rows[0].split(',')).toHaveLength(17)
        const channelZero = rows[0].split(',').indexOf('wave[0]')
        expect(Number(rows[1].split(',')[channelZero])).toBe(-99.5)
        expect(Number(rows[201].split(',')[channelZero])).toBe(100.5)
      } finally {
        ;(window as any).__MKLINK_SAVE_FILE__ = previousSave
      }
    } finally {
      runtime.cleanup()
    }
  })

  it.each(['time', 'value'])('uses the same SuperWatch history for both %s cursor readouts', async mode => {
    mocks.useBinaryStream.mockReturnValue({
      ...mocks.binary, waveformBatch: shallowRef(null), envelope: shallowRef(null),
      telemetry: shallowRef(null), state: shallowRef({ phase: 'stopped' }),
      error: shallowRef(null), superwatchMetadata: shallowRef(null),
    })
    const runtime = await loadRttViewerRuntime('SuperWatch', 32)
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }])
      runtime.viewer.acceptBinarySummary({
        sequence: 1n, timestampNs: 8_000_000_000n,
        collectedItemCount: 8, bufferedItemCount: 8, channelCount: 1,
        bufferStartMs: 0, bufferEndMs: 8_000, latestTimeMs: 8_000,
        latestValues: Float32Array.of(99).buffer,
      })
      Object.assign(runtime.probe.cursor, { enabled: true, mode, a: { t: 1 }, b: { t: 2 } })
      runtime.viewer.renderBinaryEnvelope({
        type: 'render-envelope', mode: 'min-max-v1', timestampKind: 'sample-milliseconds',
        requestId: 1, pixelWidth: 800, channelCount: 1, pointCount: 3,
        candidateSampleCount: 3, times: Float64Array.of(0, 1_000, 2_000).buffer,
        timeIndices: Uint32Array.of(0, 1, 2).buffer,
        values: Float32Array.of(0, 10, 30).buffer,
        channelOffsets: Uint32Array.of(0, 3).buffer,
      })
      expect(runtime.probe.fields().A.ringBuf.count).toBe(1)
      expect(document.getElementById('cursor-readout')?.textContent).toContain('A d=20.00')
      expect(document.getElementById('cursor-measure-panel')?.textContent)
        .toContain(mode === 'time' ? 'd=20.00' : 'A:10.00 B:30.00 dV:20.00')
    } finally {
      runtime.cleanup()
    }
  })

  it('renders wrapped multi-channel cursor data without copying either ring', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      const send = (sequence: bigint, timestampNs: bigint, values: number[]) => {
        const itemCount = values.length / 2
        const endMs = Number(timestampNs) / 1_000_000
        const times = sequence === 1n
          ? Float64Array.of(endMs - 0.001, endMs)
          : Float64Array.from({ length: itemCount }, (_, index) => endMs - (itemCount - 1 - index) * 500)
        return runtime.viewer.acceptBinaryBatch({
          sequence, timestampNs, itemCount, channelCount: 2,
          layout: 'sample-major-float32', values: Float32Array.from(values).buffer,
          times: times.buffer,
        })
      }
      send(1n, 10_000_000_000n, [1, 10, 2, 20])
      send(2n, 12_000_000_000n, [3, 30, 4, 40, 5, 50, 6, 60])
      send(3n, 14_000_000_000n, [7, 70, 8, 80, 9, 90, 10, 100])
      runtime.probe.cursor.enabled = true
      runtime.probe.cursor.mode = 'value'
      runtime.probe.cursor.a = { t: 2.6 }
      runtime.probe.cursor.b = { t: 3.9 }
      ;(window as any).__ringToArrayCalls = 0

      runtime.viewer.renderBinaryFrame()

      expect((window as any).__ringToArrayCalls).toBe(0)
      expect(runtime.probe.fields().A.ringBuf.count).toBe(4)
      expect(runtime.probe.fields().A.ringBuf.timeAt(0)).toBeCloseTo(2.5)
      expect(runtime.probe.fields().A.ringBuf.valueAt(3)).toBe(10)
      expect(document.getElementById('cursor-readout')?.textContent).toContain('A d=3.00')
      expect(document.getElementById('cursor-readout')?.textContent).toContain('B d=30.00')
    } finally {
      runtime.cleanup()
    }
  })

  it('replaces same-count and changed-count VOFA channel snapshots atomically', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 10n, timestampNs: 1_000_000_000n, itemCount: 1, channelCount: 2,
        layout: 'sample-major-float32', values: Float32Array.of(1, 2).buffer,
        times: Float64Array.of(1000).buffer,
      })).toBe(true)
      runtime.probe.trigger.enabled = true
      runtime.probe.trigger.source = 'A'
      runtime.probe.cursor.enabled = true
      runtime.probe.cursor.a = { t: 0 }
      runtime.probe.cursor.b = { t: 1 }

      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      expect(runtime.probe.fields().A.ringBuf.count).toBe(1)
      expect(runtime.probe.trigger).toMatchObject({ enabled: true, source: 'A' })

      runtime.viewer.configureBinaryChannels([{ name: 'C' }, { name: 'D' }])

      expect(Object.keys(runtime.probe.fields()).sort()).toEqual(['C', 'D'])
      expect(Object.keys(runtime.probe.metadata()).sort()).toEqual(['C', 'D'])
      expect(runtime.probe.binary()).toEqual({
        names: ['C', 'D'], timeOrigin: null, lastTimestamp: null, lastSequence: null,
      })
      expect(runtime.probe.trigger).toMatchObject({ enabled: false, source: '', state: 'idle' })
      expect(runtime.probe.cursor).toMatchObject({ enabled: false, a: null, b: null })
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 2_000_000_000n, itemCount: 1, channelCount: 2,
        layout: 'sample-major-float32', values: Float32Array.of(3, 4).buffer,
        times: Float64Array.of(2000).buffer,
      })).toBe(true)

      runtime.probe.metadata().C.legacy = 'stale'
      runtime.probe.fields().C.thresholds = { warnHigh: 1 }
      runtime.viewer.configureBinaryChannels([
        { name: 'C', type: 'uint32_t', addr: 0x20000000 },
        { name: 'D' },
      ])
      expect(runtime.probe.metadata().C).toEqual({
        type: 'uint32_t', size: 4, address: 0x20000000, unit: '',
      })
      expect(runtime.probe.fields().C.thresholds).toBeNull()

      runtime.viewer.configureBinaryChannels([{ name: 'E' }])
      expect(Object.keys(runtime.probe.fields())).toEqual(['E'])
      expect(runtime.probe.binary().names).toEqual(['E'])
      runtime.viewer.configureBinaryChannels([])
      expect(Object.keys(runtime.probe.fields())).toEqual([])
      expect(Object.keys(runtime.probe.metadata())).toEqual([])
    } finally {
      runtime.cleanup()
    }
  })

  it('resets binary sequence, envelope, and rings without changing channel metadata', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      const channels = [{ name: 'A', type: 'float', unit: 'V' }]
      runtime.viewer.configureBinaryChannels(channels)
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 10n, timestampNs: 1_000_000_000n, itemCount: 1, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(7).buffer,
        times: Float64Array.of(1000).buffer,
      })).toBe(true)

      runtime.viewer.resetBinaryStream()

      expect(runtime.probe.fields().A.ringBuf.count).toBe(0)
      expect(runtime.probe.metadata().A).toMatchObject({ type: 'float', unit: 'V' })
      expect(runtime.probe.binary()).toEqual({
        names: ['A'], timeOrigin: null, lastTimestamp: null, lastSequence: null,
      })
      expect(runtime.viewer.acceptBinaryBatch({
        sequence: 1n, timestampNs: 2_000_000_000n, itemCount: 1, channelCount: 1,
        layout: 'sample-major-float32', values: Float32Array.of(8).buffer,
        times: Float64Array.of(2000).buffer,
      })).toBe(true)
    } finally {
      runtime.cleanup()
    }
  })

  it('keeps SuperWatch incremental metadata updates non-purging', async () => {
    const runtime = await loadRttViewerRuntime('SuperWatch')
    try {
      runtime.probe.applyMetadata({ A: { type: 'float' } }, false)
      runtime.probe.applyMetadata({ B: { type: 'float' } }, false)
      expect(Object.keys(runtime.probe.fields()).sort()).toEqual(['A', 'B'])
      expect(Object.keys(runtime.probe.metadata()).sort()).toEqual(['A', 'B'])
    } finally {
      runtime.cleanup()
    }
  })
})
