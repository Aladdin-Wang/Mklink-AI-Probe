import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, shallowRef } from 'vue'
import { nextTick } from 'vue'
import { StreamType } from '../../lib/stream/protocol'
import { StreamDecoder } from '../../workers/streamDecoder.worker'
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
  scheduler: {
    start: vi.fn(), stop: vi.fn(), invalidate: vi.fn(),
    recordCollection: vi.fn(), dispose: vi.fn(),
  },
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
  RenderScheduler: class {
    start = mocks.scheduler.start
    stop = mocks.scheduler.stop
    invalidate = mocks.scheduler.invalidate
    recordCollection = mocks.scheduler.recordCollection
    dispose = mocks.scheduler.dispose
  },
}))

describe('RttViewTab binary migration', () => {
  afterEach(() => vi.useRealTimers())

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

  it('pauses only rendering while binary acquisition remains active', async () => {
    vi.useFakeTimers()
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    mocks.dash.state.value = 'running'
    await nextTick()

    await wrapper.get('.control-toolbar .btn:not(.btn-danger)').trigger('click')
    expect(mocks.scheduler.stop).toHaveBeenCalled()
    expect(mocks.dash.pause).not.toHaveBeenCalled()
    expect(mocks.binary.stop).not.toHaveBeenCalled()
    mocks.binary.rttLines.value = {
      type: 'rtt-lines', sequence: 1n,
      lines: [{ timestampNs: 1n, level: 'raw', text: 'paused-line' }],
    }
    await nextTick()
    vi.advanceTimersByTime(100)
    await nextTick()
    expect((wrapper.findComponent({ name: 'VirtualLogPanel' }).vm as any).retainedCount).toBe(0)

    await wrapper.get('.control-toolbar .btn-primary').trigger('click')
    expect(mocks.scheduler.start).toHaveBeenCalledTimes(2)
    expect(mocks.scheduler.invalidate).toHaveBeenCalledWith('data')
    expect(mocks.dash.resume).not.toHaveBeenCalled()
    expect(mocks.binary.start).not.toHaveBeenCalled()
    mocks.binary.rttLines.value = {
      type: 'rtt-lines', sequence: 2n,
      lines: [{ timestampNs: 2n, level: 'raw', text: 'resumed-line' }],
    }
    await nextTick()
    vi.advanceTimersByTime(100)
    await nextTick()
    expect((wrapper.findComponent({ name: 'VirtualLogPanel' }).vm as any).retainedCount).toBe(1)
    wrapper.unmount()
  })

  it('ignores an in-flight envelope that arrives after render pause', async () => {
    const clearRect = vi.fn()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      setTransform: vi.fn(), clearRect, beginPath: vi.fn(), moveTo: vi.fn(),
      lineTo: vi.fn(), stroke: vi.fn(), strokeStyle: '',
    } as unknown as CanvasRenderingContext2D)
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    mocks.dash.state.value = 'running'
    await nextTick()

    await wrapper.get('.control-toolbar .btn:not(.btn-danger)').trigger('click')
    mocks.binary.envelope.value = {
      type: 'render-envelope', requestId: 0, channelCount: 1, pointCount: 2,
      values: Float32Array.of(1, 2).buffer,
      channelOffsets: Uint32Array.of(0, 2).buffer,
    }
    await nextTick()

    expect(clearRect).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('bounds an accelerated RTT record to Worker to VirtualLog pipeline at 5000 lines', async () => {
    vi.useFakeTimers()
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    const lineCount = 6000
    const encoder = new TextEncoder()
    const encoded = Array.from({ length: lineCount }, (_, index) => encoder.encode(`line-${index + 1}`))
    const payload = new Uint8Array(encoded.reduce((size, line) => size + 13 + line.length, 0))
    const payloadView = new DataView(payload.buffer)
    let offset = 0
    encoded.forEach((line, index) => {
      payloadView.setBigUint64(offset, BigInt(index + 1), true)
      payloadView.setUint8(offset + 8, 0)
      payloadView.setUint32(offset + 9, line.length, true)
      payload.set(line, offset + 13)
      offset += 13 + line.length
    })
    const buffer = new ArrayBuffer(36 + payload.byteLength)
    const bytes = new Uint8Array(buffer)
    const view = new DataView(buffer)
    bytes.set([0x4d, 0x4b, 0x53, 0x54])
    view.setUint8(4, 1)
    view.setUint8(5, StreamType.RTT_RAW)
    view.setUint8(6, 1)
    view.setUint8(7, 36)
    view.setUint32(8, StreamType.RTT_RAW, true)
    view.setBigUint64(12, 1n, true)
    view.setBigUint64(20, BigInt(lineCount), true)
    view.setUint32(28, lineCount, true)
    view.setUint32(32, payload.byteLength, true)
    bytes.set(payload, 36)
    const decoder = new StreamDecoder(message => {
      if (message.type === 'rtt-lines') mocks.binary.rttLines.value = message
    })
    decoder.handle({ type: 'configure', capacity: 200_000, channelCount: 1 })
    decoder.handle({
      type: 'frame', buffer, connectionGeneration: 1, frameTicket: 1,
    })
    await nextTick()
    vi.advanceTimersByTime(100)
    await nextTick()

    const panel = wrapper.findComponent({ name: 'VirtualLogPanel' })
    expect((panel.vm as any).retainedCount).toBe(5000)
    expect((panel.vm as any).firstLineNumber).toBe(1001)
    expect(panel.findAll('.virtual-log-row').length).toBeLessThan(40)
    wrapper.unmount()
  })
})
