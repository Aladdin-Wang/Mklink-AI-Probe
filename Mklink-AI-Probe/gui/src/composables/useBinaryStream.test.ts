import { defineComponent, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import {
  useBinaryStream,
  type BinaryStreamClient,
} from './useBinaryStream'
import type { StreamClientOptions, StreamClientState } from '../lib/stream/streamClient'
import type { WorkerOutput } from '../workers/streamDecoder.worker'

describe('useBinaryStream', () => {
  it('retires an unresponsive worker and ignores late capacity replies', async () => {
    vi.useFakeTimers()
    let options: StreamClientOptions | undefined
    let api: ReturnType<typeof useBinaryStream> | undefined
    const client = { start: vi.fn(), stop: vi.fn(), reset: vi.fn(), configure: vi.fn(),
      resizeWaveform: vi.fn(), requestVisibleRange: vi.fn(), dispose: vi.fn() }
    const wrapper = mount(defineComponent({ setup() {
      api = useBinaryStream('vofa', { capacity: 10000, channelCount: 1, createClient: next => { options = next; return client } })
      return () => null
    } }))
    try {
      const pending = api!.resizeWaveform(2)
      const rejected = expect(pending).rejects.toThrow('timed out')
      api!.configure(3)
      await vi.advanceTimersByTimeAsync(5000)
      await rejected
      expect(client.dispose).toHaveBeenCalledOnce()
      expect(api!.state.value).toMatchObject({ phase: 'error', fatal: true })
      options!.onWorkerMessage!({ type: 'waveform-capacity-result', requestId: 1, capacity: 2 })
      expect(client.configure).not.toHaveBeenCalled()
      await expect(api!.resizeWaveform(4)).rejects.toThrow('reload')
      expect(client.resizeWaveform).toHaveBeenCalledTimes(1)
    } finally { wrapper.unmount(); vi.useRealTimers() }
  })

  it('confirms resize before queued channel changes and preserves capacity after rejection', async () => {
    const client = { start: vi.fn(), stop: vi.fn(), reset: vi.fn(), configure: vi.fn(),
      resizeWaveform: vi.fn(), requestVisibleRange: vi.fn(), dispose: vi.fn() }
    let api: ReturnType<typeof useBinaryStream> | undefined
    let options: StreamClientOptions | undefined
    const wrapper = mount(defineComponent({
      setup() {
        api = useBinaryStream('vofa', { capacity: 10000, channelCount: 2, createClient: next => { options = next; return client } })
        return () => null
      },
    }))
    try {
      const resized = api!.resizeWaveform(16)
      expect(client.resizeWaveform).toHaveBeenCalledWith(16, 1)
      expect(client.reset).not.toHaveBeenCalled()
      expect(client.configure).not.toHaveBeenCalled()
      api!.configure(3)
      expect(client.configure).not.toHaveBeenCalled()
      options!.onWorkerMessage!({ type: 'waveform-capacity-result', requestId: 1, capacity: 16 })
      await resized
      expect(client.configure).toHaveBeenCalledWith(16, 3)
      expect(() => api!.resizeWaveform(2.5)).toThrow()
      expect(client.resizeWaveform).toHaveBeenCalledTimes(1)
      const failed = api!.resizeWaveform(32)
      const rejection = expect(failed).rejects.toThrow('allocation failed')
      api!.configure(4)
      options!.onWorkerMessage!({ type: 'waveform-capacity-result', requestId: 2, capacity: 16, error: 'allocation failed' })
      await rejection
      expect(client.configure).toHaveBeenLastCalledWith(16, 4)
    } finally { wrapper.unmount() }
  })

  it('coalesces high-rate presentation without losing sample counts or leaking across reset', () => {
    vi.useFakeTimers()
    let options: StreamClientOptions | undefined
    let api: ReturnType<typeof useBinaryStream> | undefined
    const wrapper = mount(defineComponent({
      setup() {
        api = useBinaryStream('superwatch', {
          capacity: 200000, channelCount: 1,
          createClient: next => {
            options = next
            return { start: vi.fn(), stop: vi.fn(), reset: vi.fn(), configure: vi.fn(),
              requestVisibleRange: vi.fn(), dispose: vi.fn() }
          },
        })
        return () => null
      },
    }))
    const summary = (n: number) => ({
      type: 'waveform-summary', sequence: BigInt(n), timestampNs: BigInt(n * 1000),
      collectedItemCount: 512, bufferedItemCount: n * 512, channelCount: 1,
      bufferStartMs: 0, bufferEndMs: n, latestTimeMs: n,
      latestValues: Float32Array.of(n).buffer,
    } as const)
    for (let n = 1; n <= 10; n++) options?.onWorkerMessage?.(summary(n))
    expect(api?.waveformSummary.value).toBeNull()
    vi.advanceTimersByTime(33)
    expect(api?.waveformSummary.value?.collectedItemCount).toBe(5120)
    expect(api?.waveformSummary.value?.sequence).toBe(10n)
    options?.onWorkerMessage?.(summary(11))
    api?.reset()
    vi.advanceTimersByTime(33)
    expect(api?.waveformSummary.value).toBeNull()
    options?.onWorkerMessage?.(summary(1))
    api?.stop()
    expect(api?.waveformSummary.value?.collectedItemCount).toBe(512)
    options?.onWorkerMessage?.(summary(2))
    wrapper.unmount()
    vi.advanceTimersByTime(100)
    expect(api?.waveformSummary.value?.sequence).toBe(1n)
    vi.useRealTimers()
  })
  it('exposes stream state and disposes socket/worker ownership on unmount', async () => {
    let options: StreamClientOptions | undefined
    const client: BinaryStreamClient = {
      start: vi.fn(),
      stop: vi.fn(),
      reset: vi.fn(),
      configure: vi.fn(),
      requestVisibleRange: vi.fn(),
      dispose: vi.fn(),
    }
    const createClient = vi.fn((next: StreamClientOptions) => {
      options = next
      return client
    })
    let api: ReturnType<typeof useBinaryStream> | undefined
    const wrapper = mount(defineComponent({
      setup() {
        api = useBinaryStream('vofa', {
          capacity: 1000,
          channelCount: 2,
          token: 'secret',
          autoStart: true,
          createClient,
        })
        return () => null
      },
    }))

    expect(createClient).toHaveBeenCalledOnce()
    expect(options?.url).toMatch(/\/ws\/streams\/vofa$/)
    expect(options?.token).toBe('secret')
    expect(client.start).toHaveBeenCalledOnce()

    options?.onState?.({ phase: 'connected' } satisfies StreamClientState)
    options?.onWorkerMessage?.({
      type: 'telemetry',
      acceptedFrames: 1,
      acceptedConnectionGeneration: 1,
      acceptedFrameTicket: 1,
      bufferedSamples: 10,
      transportDroppedBatches: 2,
      backendDroppedBatches: 3,
      backendDroppedItems: 30,
      backendDroppedBytes: 120,
      lastSequence: 9n,
    } satisfies WorkerOutput)
    await nextTick()
    expect(api?.connected.value).toBe(true)
    expect(api?.telemetry.value?.bufferedSamples).toBe(10)

    const values = Float32Array.of(1, 10, 2, 20).buffer
    options?.onWorkerMessage?.({
      type: 'waveform-batch', sequence: 1n, timestampNs: 10n,
      itemCount: 2, channelCount: 2, layout: 'sample-major-float32', values,
    } satisfies WorkerOutput)
    await nextTick()
    expect(api?.waveformBatch.value?.itemCount).toBe(2)

    api?.configure(4)
    expect(client.configure).toHaveBeenCalledWith(1000, 4)

    api?.requestVisibleRange(4, 1, 2, 300)
    expect(client.requestVisibleRange).toHaveBeenCalledWith(4, 1, 2, 300)
    wrapper.unmount()
    expect(client.dispose).toHaveBeenCalledOnce()
  })

  it('surfaces worker errors independently of connection state', async () => {
    let options: StreamClientOptions | undefined
    const client: BinaryStreamClient = {
      start: vi.fn(), stop: vi.fn(), reset: vi.fn(),
      configure: vi.fn(),
      requestVisibleRange: vi.fn(), dispose: vi.fn(),
    }
    let api: ReturnType<typeof useBinaryStream> | undefined
    const wrapper = mount(defineComponent({
      setup() {
        api = useBinaryStream('systemview', {
          capacity: 10,
          channelCount: 1,
          createClient: next => { options = next; return client },
        })
        return () => null
      },
    }))

    options?.onWorkerMessage?.({ type: 'error', code: 'INVALID_FRAME', message: 'bad layout' })
    await nextTick()
    expect(api?.error.value).toBe('bad layout')
    expect(api?.state.value.phase).toBe('stopped')
    wrapper.unmount()
  })
})
