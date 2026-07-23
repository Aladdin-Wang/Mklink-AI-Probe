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
