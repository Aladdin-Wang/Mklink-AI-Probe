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

    wrapper.unmount()
    mocks.binary.configure.mockClear()
    window.dispatchEvent(new CustomEvent('mklink:vofa-channels', { detail: [{ name: 'late' }] }))
    expect(mocks.binary.configure).not.toHaveBeenCalled()
  })
})

describe('VOFA viewer hot path source guard', () => {
  const source = fs.readFileSync(path.resolve(process.cwd(), 'src/assets/rtt_viewer.js'), 'utf8')

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
