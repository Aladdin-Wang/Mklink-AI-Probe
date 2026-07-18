import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, shallowRef } from 'vue'
import { nextTick } from 'vue'
import { saveDesktopSettings, type DesktopSettings } from '../../lib/desktopSettings'
import { StreamType } from '../../lib/stream/protocol'
import { StreamDecoder } from '../../workers/streamDecoder.worker'
import RttViewTab from './RttViewTab.vue'

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>()
  get length(): number { return this.values.size }
  clear(): void { this.values.clear() }
  getItem(key: string): string | null { return this.values.get(key) ?? null }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null }
  removeItem(key: string): void { this.values.delete(key) }
  setItem(key: string, value: string): void { this.values.set(key, value) }
}

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
  api: {
    findRtt: vi.fn(),
    writeRtt: vi.fn(),
  },
  status: { running: false, numeric_channels: [], down_buffers: [] } as Record<string, unknown>,
  scheduler: {
    render: null as null | (() => void),
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
vi.mock('../../composables/useMklinkApi', () => ({ useMklinkApi: () => mocks.api }))
vi.mock('../../lib/stream/renderScheduler', () => ({
  RenderScheduler: class {
    constructor(render: () => void) { mocks.scheduler.render = render }
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
    mocks.scheduler.render = null
    mocks.dash.start.mockResolvedValue(true)
    mocks.dash.stop.mockResolvedValue(undefined)
    mocks.api.findRtt.mockResolvedValue({ found: true, addr: '0x20001A40' })
    mocks.api.writeRtt.mockResolvedValue({ sent_bytes: 1 })
    mocks.status = { running: false, numeric_channels: [], down_buffers: [] }
    vi.stubGlobal('localStorage', new MemoryStorage())
    localStorage.clear()
    saveDesktopSettings(localStorage, desktopSettings({ rttAddress: '0x20000000' }))
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({
      ok: true,
      json: async () => mocks.status,
    })))
  })

  function desktopSettings(overrides: Partial<DesktopSettings> = {}): DesktopSettings {
    return {
      version: 1,
      symbolPath: '',
      mapPath: '',
      rttAddress: '',
      transmitMode: 'text',
      lineEnding: '',
      sendHistory: [],
      ...overrides,
    }
  }

  it('uses RTT binary transport and a bounded virtual log without EventSource', () => {
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    expect(mocks.useBinaryStream).toHaveBeenCalledWith('rtt', expect.any(Object))
    expect(wrapper.findComponent({ name: 'VirtualLogPanel' }).exists()).toBe(true)
    wrapper.unmount()
  })

  it('keeps the text log hidden until RTT text arrives', async () => {
    vi.useFakeTimers()
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })

    expect(wrapper.get('.rtt-view-log').classes()).toContain('is-empty')

    mocks.binary.rttLines.value = {
      type: 'rtt-lines', sequence: 1n,
      lines: [{ timestampNs: 1n, level: 'raw', text: 'first-line' }],
    }
    await nextTick()
    vi.advanceTimersByTime(100)
    await nextTick()

    expect(wrapper.get('.rtt-view-log').classes()).not.toContain('is-empty')
    wrapper.unmount()
  })

  it('starts and stops the binary lifecycle with dashboard controls', async () => {
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    await wrapper.get('.btn-primary').trigger('click')
    await Promise.resolve()
    expect(mocks.binary.reset).toHaveBeenCalled()
    expect(mocks.dash.start).toHaveBeenCalledWith({
      addr: '0x20000000', mode: 1, search_size: 0,
    })
    expect(mocks.binary.start).toHaveBeenCalled()
    mocks.dash.state.value = 'running'
    await nextTick()
    await wrapper.get('.btn-danger').trigger('click')
    expect(mocks.binary.stop).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('searches AXF/ELF before MAP and fills the editable RTT address', async () => {
    saveDesktopSettings(localStorage, desktopSettings({
      symbolPath: 'C:\\firmware\\app.elf',
      mapPath: 'C:\\firmware\\app.map',
      rttAddress: '0x20000000',
    }))
    mocks.api.findRtt.mockResolvedValueOnce({
      found: true, addr: '0x20001A40', source: 'binary:app.elf',
    })
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })

    await wrapper.get('[data-testid="rtt-search"]').trigger('click')
    await flushPromises()

    expect(mocks.api.findRtt).toHaveBeenCalledWith('C:\\firmware\\app.elf')
    expect((wrapper.get('[data-testid="rtt-address"]').element as HTMLInputElement).value)
      .toBe('0x20001A40')
    expect(JSON.parse(localStorage.getItem('mklink.desktop.settings.v1') ?? '{}').rttAddress)
      .toBe('0x20001A40')
    expect(wrapper.text()).toContain('binary:app.elf')
    wrapper.unmount()
  })

  it('falls back to MAP and then to the legacy project search when paths are empty', async () => {
    saveDesktopSettings(localStorage, desktopSettings({
      symbolPath: '   ',
      mapPath: 'C:\\firmware\\app.map',
    }))
    let wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    await wrapper.get('[data-testid="rtt-search"]').trigger('click')
    await flushPromises()
    expect(mocks.api.findRtt).toHaveBeenLastCalledWith('C:\\firmware\\app.map')
    wrapper.unmount()

    saveDesktopSettings(localStorage, desktopSettings())
    wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    await wrapper.get('[data-testid="rtt-search"]').trigger('click')
    await flushPromises()
    expect(mocks.api.findRtt).toHaveBeenLastCalledWith(undefined)
    wrapper.unmount()
  })

  it('does not let an in-flight search overwrite a newer manual edit', async () => {
    let resolveSearch!: (value: unknown) => void
    mocks.api.findRtt.mockReturnValueOnce(new Promise(resolve => { resolveSearch = resolve }))
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })

    await wrapper.get('[data-testid="rtt-search"]').trigger('click')
    await wrapper.get('[data-testid="rtt-address"]').setValue('0x20003333')
    resolveSearch({ found: true, addr: '0x20001111', source: 'map:old.map' })
    await flushPromises()

    expect((wrapper.get('[data-testid="rtt-address"]').element as HTMLInputElement).value)
      .toBe('0x20003333')
    expect(JSON.parse(localStorage.getItem('mklink.desktop.settings.v1') ?? '{}').rttAddress)
      .toBe('0x20003333')
    expect(wrapper.text()).not.toContain('map:old.map')
    wrapper.unmount()
  })

  it('blocks RTT start until an in-flight address search completes', async () => {
    let resolveSearch!: (value: unknown) => void
    mocks.api.findRtt.mockReturnValueOnce(new Promise(resolve => { resolveSearch = resolve }))
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })

    await wrapper.get('[data-testid="rtt-search"]').trigger('click')

    const toolbar = wrapper.findComponent({ name: 'ControlToolbar' })
    expect(toolbar.get('.btn-primary').attributes('disabled')).toBeDefined()
    toolbar.vm.$emit('start')
    await nextTick()
    expect(mocks.dash.start).not.toHaveBeenCalled()

    resolveSearch({ found: true, addr: '0x20001A40', source: 'binary:app.axf' })
    await flushPromises()
    expect(toolbar.get('.btn-primary').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('preserves the current address on search failure and ignores stale results', async () => {
    let resolveFirst!: (value: unknown) => void
    const first = new Promise(resolve => { resolveFirst = resolve })
    mocks.api.findRtt
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce({ found: true, addr: '0x20002222' })
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })

    await wrapper.get('[data-testid="rtt-search"]').trigger('click')
    await wrapper.get('[data-testid="rtt-search"]').trigger('click')
    await flushPromises()
    expect((wrapper.get('[data-testid="rtt-address"]').element as HTMLInputElement).value)
      .toBe('0x20002222')

    resolveFirst({ found: true, addr: '0x20001111' })
    await flushPromises()
    expect((wrapper.get('[data-testid="rtt-address"]').element as HTMLInputElement).value)
      .toBe('0x20002222')

    mocks.api.findRtt.mockRejectedValueOnce(new Error('未找到 RTT'))
    await wrapper.get('[data-testid="rtt-search"]').trigger('click')
    await flushPromises()
    expect((wrapper.get('[data-testid="rtt-address"]').element as HTMLInputElement).value)
      .toBe('0x20002222')
    expect(wrapper.text()).toContain('未找到 RTT')
    wrapper.unmount()
  })

  it('rejects an invalid manual address before starting', async () => {
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    await wrapper.get('[data-testid="rtt-address"]').setValue('20001A40')
    await wrapper.get('.btn-primary').trigger('click')

    expect(mocks.dash.start).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('RTT 地址')
    wrapper.unmount()
  })

  it('enables transmission only while RTT has an active DownBuffer', async () => {
    vi.useFakeTimers()
    mocks.status = {
      running: true,
      numeric_channels: [],
      down_buffers: [{ index: 0, active: true }],
    }
    mocks.dash.state.value = 'running'
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    await flushPromises()
    await nextTick()

    const bar = wrapper.findComponent({ name: 'RttTransmitBar' })
    expect(bar.props('enabled')).toBe(true)
    await bar.get('[data-testid="rtt-input"]').setValue('OK')
    await bar.get('[data-testid="rtt-send"]').trigger('click')
    await flushPromises()
    expect(mocks.api.writeRtt).toHaveBeenCalledWith(Uint8Array.of(0x4f, 0x4b))

    mocks.status = { running: true, numeric_channels: [], down_buffers: [] }
    vi.advanceTimersByTime(1_000)
    await flushPromises()
    expect(bar.props('enabled')).toBe(false)
    wrapper.unmount()
  })

  it('disables transmission immediately when stop begins', async () => {
    vi.useFakeTimers()
    let resolveStop!: () => void
    mocks.dash.stop.mockReturnValueOnce(new Promise<void>(resolve => { resolveStop = resolve }))
    mocks.status = {
      running: true,
      numeric_channels: [],
      down_buffers: [{ index: 0, active: true }],
    }
    mocks.dash.state.value = 'running'
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    await flushPromises()
    const bar = wrapper.findComponent({ name: 'RttTransmitBar' })
    expect(bar.props('enabled')).toBe(true)

    await wrapper.get('.btn-danger').trigger('click')
    expect(bar.props('enabled')).toBe(false)
    resolveStop()
    await flushPromises()
    wrapper.unmount()
  })

  it('requests the numeric envelope over the actual Worker buffer time range', async () => {
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })
    mocks.binary.telemetry.value = { bufferedSamples: 256 }
    mocks.binary.waveformBatch.value = {
      type: 'waveform-batch', sequence: 1n, timestampNs: 2_000_000_000n,
      itemCount: 256, channelCount: 4, layout: 'sample-major-float32',
      values: new ArrayBuffer(0), times: new ArrayBuffer(0),
      bufferStartMs: 1_500, bufferEndMs: 2_000,
    }
    await nextTick()

    mocks.scheduler.render?.()

    expect(mocks.binary.requestVisibleRange).toHaveBeenCalledWith(1, 1_500, 2_000, 640)
    wrapper.unmount()
  })

  it('does not start the binary transport when the dashboard start fails', async () => {
    mocks.dash.start.mockResolvedValue(false)
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })

    await wrapper.get('.btn-primary').trigger('click')
    await Promise.resolve()

    expect(mocks.binary.reset).toHaveBeenCalled()
    expect(mocks.binary.start).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('stops the binary transport and surfaces a backend runtime error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        running: false,
        error: 'RTT device entered ERROR state',
        numeric_channels: [],
      }),
    }))
    const wrapper = mount(RttViewTab, { props: { deviceConnected: true } })

    await flushPromises()
    await nextTick()

    expect(mocks.binary.stop).toHaveBeenCalled()
    const toolbar = wrapper.findComponent({ name: 'ControlToolbar' })
    expect(toolbar.props('state')).toBe('error')
    expect(toolbar.props('error')).toBe('RTT device entered ERROR state')
    expect(wrapper.findComponent({ name: 'RttTransmitBar' }).props('enabled')).toBe(false)
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
