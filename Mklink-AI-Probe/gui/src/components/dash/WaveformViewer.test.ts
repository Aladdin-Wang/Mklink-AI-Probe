import fs from 'node:fs'
import path from 'node:path'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, shallowRef } from 'vue'
import WaveformViewer from './WaveformViewer.vue'

const mocks = vi.hoisted(() => ({
  useBinaryStream: vi.fn(),
  binary: {
    waveformBatch: null as ReturnType<typeof shallowRef<unknown>> | null,
    telemetry: null as ReturnType<typeof shallowRef<unknown>> | null,
    start: vi.fn(), stop: vi.fn(), reset: vi.fn(), configure: vi.fn(),
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

function canvasContext(): CanvasRenderingContext2D {
  const gradient = { addColorStop: vi.fn() }
  return new Proxy({} as CanvasRenderingContext2D, {
    get(target, property) {
      if (property === 'measureText') return () => ({ width: 10 })
      if (property === 'createLinearGradient') return () => gradient
      if (!(property in target)) return () => undefined
      return target[property as keyof CanvasRenderingContext2D]
    },
    set(target, property, value) {
      ;(target as any)[property] = value
      return true
    },
  })
}

async function loadRttViewerRuntime(mode: 'VOFA' | 'SuperWatch' = 'VOFA') {
  const contextSpy = vi.spyOn(HTMLCanvasElement.prototype, 'getContext')
    .mockReturnValue(canvasContext())
  const rectSpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
    .mockReturnValue({
      x: 0, y: 0, width: 800, height: 400, top: 0, right: 800,
      bottom: 400, left: 0, toJSON: () => ({}),
    })
  const widthSpy = vi.spyOn(HTMLCanvasElement.prototype, 'clientWidth', 'get')
    .mockReturnValue(800)
  const heightSpy = vi.spyOn(HTMLCanvasElement.prototype, 'clientHeight', 'get')
    .mockReturnValue(400)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('EventSource', class {
    static CLOSED = 2
    readyState = 1
    close() {}
  })
  vi.stubGlobal('t', (key: string) => key)
  ;(globalThis as any).CONFIG = {
    maxPoints: 4, title: 'test', mode, lang: 'en', deviceConnected: true,
  }
  ;(window as any).__ringToArrayCalls = 0
  const wrapper = mount(WaveformViewer, { props: { mode, deviceConnected: true } })
  await new Promise(resolve => setTimeout(resolve, 0))
  const host = wrapper.element
  host.querySelectorAll('script[src]').forEach(script => script.remove())
  document.body.appendChild(host)
  const instrumented = viewerSource.replace(
    'RingBuffer.prototype.toArray = function() {',
    'RingBuffer.prototype.toArray = function() { window.__ringToArrayCalls++;',
  ) + `
window.__rttTestProbe = {
  fields: function() { return FIELDS; },
  metadata: function() { return CHANNEL_METADATA; },
  binary: function() { return {
    names: binaryChannelNames.slice(), timeOrigin: binaryTimeOrigin,
    lastTimestamp: binaryLastTimestamp, lastSequence: binaryLastSequence
  }; },
  trigger: triggerSettings,
  cursor: cursorState,
  applyMetadata: applyChannelMetadata
};`
  new Function(instrumented).call(window)
  return {
    wrapper,
    viewer: (window as any).__waveformViewers.VOFA as any,
    probe: (window as any).__rttTestProbe as any,
    cleanup() {
      wrapper.unmount()
      host.remove()
      contextSpy.mockRestore()
      rectSpy.mockRestore()
      widthSpy.mockRestore()
      heightSpy.mockRestore()
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

describe('WaveformViewer VOFA binary transport', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.schedulerInstances.length = 0
    mocks.binary.waveformBatch = shallowRef(null)
    mocks.binary.telemetry = shallowRef(null)
    mocks.useBinaryStream.mockReturnValue(mocks.binary)
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
    ;(window as any).__waveformViewers = {}
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

  it('keeps SuperWatch on its legacy transport', () => {
    const wrapper = mount(WaveformViewer, {
      props: { mode: 'SuperWatch', deviceConnected: true },
    })
    expect(mocks.useBinaryStream).not.toHaveBeenCalled()
    expect(mocks.schedulerInstances).toHaveLength(0)
    wrapper.unmount()
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

  it('bridges typed Worker batches without scheduling one render per sample', async () => {
    const acceptBinaryBatch = vi.fn()
    const renderBinaryFrame = vi.fn()
    ;(window as any).__waveformViewers.VOFA = { acceptBinaryBatch, renderBinaryFrame }
    const wrapper = mount(WaveformViewer, { props: { mode: 'VOFA', deviceConnected: true } })
    await new Promise(resolve => setTimeout(resolve, 0))
    ;(window as any).__waveformViewers.VOFA = { acceptBinaryBatch, renderBinaryFrame }

    const batch = {
      type: 'waveform-batch', sequence: 1n, timestampNs: 1_000_000n,
      itemCount: 2, channelCount: 2, layout: 'sample-major-float32',
      values: Float32Array.of(1, 10, 2, 20).buffer,
    }
    if (!mocks.binary.waveformBatch) throw new Error('missing batch ref')
    mocks.binary.waveformBatch.value = batch
    await nextTick()

    expect(acceptBinaryBatch).toHaveBeenCalledOnce()
    expect(mocks.schedulerInstances[0].recordCollection).toHaveBeenCalledWith(2)
    expect(mocks.schedulerInstances[0].invalidate).toHaveBeenCalledWith('data')
    expect(renderBinaryFrame).not.toHaveBeenCalled()
    mocks.schedulerInstances[0].render()
    expect(renderBinaryFrame).toHaveBeenCalledOnce()
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
})

describe('VOFA viewer hot path source guard', () => {
  const source = viewerSource

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
})

describe('VOFA viewer typed-ring runtime', () => {
  it('renders wrapped multi-channel cursor data without copying either ring', async () => {
    const runtime = await loadRttViewerRuntime()
    try {
      runtime.viewer.configureBinaryChannels([{ name: 'A' }, { name: 'B' }])
      const send = (sequence: bigint, timestampNs: bigint, values: number[]) =>
        runtime.viewer.acceptBinaryBatch({
          sequence, timestampNs, itemCount: values.length / 2, channelCount: 2,
          layout: 'sample-major-float32', values: Float32Array.from(values).buffer,
        })
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
      })).toBe(true)
      runtime.probe.trigger.enabled = true
      runtime.probe.trigger.source = 'A'
      runtime.probe.cursor.enabled = true
      runtime.probe.cursor.a = { t: 0 }
      runtime.probe.cursor.b = { t: 1 }

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
