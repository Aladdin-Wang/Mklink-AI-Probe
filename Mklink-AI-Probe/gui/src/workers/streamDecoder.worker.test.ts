import { describe, expect, it } from 'vitest'
import { StreamType } from '../lib/stream/protocol'
import {
  StreamDecoder,
  type WorkerOutput,
} from './streamDecoder.worker'

function frame(
  sequence: bigint,
  itemCount: number,
  payload: Uint8Array,
  streamType = StreamType.WAVEFORM,
  timestampNs = 1_000_000_000n,
): ArrayBuffer {
  const buffer = new ArrayBuffer(36 + payload.byteLength)
  const bytes = new Uint8Array(buffer)
  bytes.set([0x4d, 0x4b, 0x53, 0x54])
  const view = new DataView(buffer)
  view.setUint8(4, 1)
  view.setUint8(5, streamType)
  view.setUint8(7, 36)
  view.setUint32(8, streamType, true)
  view.setBigUint64(12, sequence, true)
  view.setBigUint64(20, timestampNs, true)
  view.setUint32(28, itemCount, true)
  view.setUint32(32, payload.byteLength, true)
  bytes.set(payload, 36)
  return buffer
}

function floats(...values: number[]): Uint8Array {
  return new Uint8Array(Float32Array.from(values).buffer)
}

function setup() {
  const messages: WorkerOutput[] = []
  const transfers: Transferable[][] = []
  const decoder = new StreamDecoder((message, transfer = []) => {
    messages.push(message)
    transfers.push(transfer)
  })
  return { decoder, messages, transfers }
}

describe('StreamDecoder worker controller', () => {
  it('configures channels and decodes sample-major multi-channel frames', () => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 8, channelCount: 2 })
    decoder.handle({
      type: 'frame', buffer: frame(1n, 2, floats(1, 101, 2, 102)),
      connectionGeneration: 7, frameTicket: 11,
    })

    expect(messages[0]).toEqual({ type: 'channels', channelCount: 2 })
    expect(messages.at(-1)).toMatchObject({
      type: 'telemetry',
      bufferedSamples: 2,
      acceptedFrames: 1,
      acceptedConnectionGeneration: 7,
      acceptedFrameTicket: 11,
      transportDroppedBatches: 0,
      backendDroppedBatches: 0,
    })
  })

  it('reports only visible typed data and transfers its ArrayBuffers', () => {
    const { decoder, messages, transfers } = setup()
    decoder.handle({ type: 'configure', capacity: 8, channelCount: 2 })
    decoder.handle({
      type: 'frame',
      buffer: frame(1n, 3, floats(1, 10, 2, 20, 3, 30), StreamType.WAVEFORM, 5_000_000n),
      connectionGeneration: 1,
      frameTicket: 1,
    })
    decoder.handle({ type: 'visible-range', requestId: 7, start: 5, end: 5, pixelWidth: 320 })

    const envelope = messages.at(-1)
    expect(envelope).toMatchObject({
      type: 'render-envelope',
      mode: 'raw-visible',
      requestId: 7,
      pixelWidth: 320,
      channelCount: 2,
      sampleCount: 3,
      timestampKind: 'batch-milliseconds',
    })
    if (envelope?.type !== 'render-envelope') throw new Error('expected envelope')
    expect(Array.from(new Float64Array(envelope.times))).toEqual([5, 5, 5])
    expect(Array.from(new Float32Array(envelope.values))).toEqual([1, 10, 2, 20, 3, 30])
    expect(transfers.at(-1)).toEqual([envelope.times, envelope.values])
  })

  it('keeps transport sequence gaps separate from backend-reported drops', () => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 8, channelCount: 1 })
    decoder.handle({
      type: 'frame', buffer: frame(10n, 1, floats(1)),
      connectionGeneration: 1, frameTicket: 1,
    })
    decoder.handle({
      type: 'frame', buffer: frame(13n, 1, floats(2)),
      connectionGeneration: 1, frameTicket: 2,
    })
    const control = new TextEncoder().encode(JSON.stringify({
      dropped_batches: 4,
      dropped_items: 40,
      dropped_bytes: 160,
    }))
    decoder.handle({
      type: 'frame', buffer: frame(13n, 0, control, StreamType.CONTROL),
      connectionGeneration: 1, frameTicket: 3,
    })

    expect(messages.at(-1)).toMatchObject({
      type: 'telemetry',
      transportDroppedBatches: 2,
      backendDroppedBatches: 4,
      acceptedFrames: 3,
      acceptedConnectionGeneration: 1,
      acceptedFrameTicket: 3,
      backendDroppedItems: 40,
      backendDroppedBytes: 160,
    })
  })

  it('rejects invalid configuration and numeric frame layouts as worker errors', () => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 0, channelCount: 2 })
    expect(messages.at(-1)).toMatchObject({ type: 'error', code: 'INVALID_CONFIG' })

    decoder.handle({ type: 'configure', capacity: 8, channelCount: 2 })
    decoder.handle({
      type: 'frame', buffer: frame(1n, 2, floats(1, 2, 3)),
      connectionGeneration: 1, frameTicket: 1,
    })
    expect(messages.at(-1)).toMatchObject({
      type: 'error', code: 'INVALID_FRAME',
      connectionGeneration: 1, frameTicket: 1,
    })
    expect(messages.some(message => (
      message.type === 'telemetry' && message.acceptedFrameTicket === 1
    ))).toBe(false)
  })

  it('resets buffered data and all drop telemetry while preserving configuration', () => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 8, channelCount: 1 })
    decoder.handle({
      type: 'frame', buffer: frame(1n, 1, floats(1)),
      connectionGeneration: 1, frameTicket: 1,
    })
    decoder.handle({
      type: 'frame', buffer: frame(3n, 1, floats(2)),
      connectionGeneration: 1, frameTicket: 2,
    })
    decoder.handle({ type: 'reset' })

    expect(messages.at(-1)).toMatchObject({
      type: 'telemetry',
      bufferedSamples: 0,
      acceptedFrames: 0,
      transportDroppedBatches: 0,
      backendDroppedBatches: 0,
    })
  })
})
