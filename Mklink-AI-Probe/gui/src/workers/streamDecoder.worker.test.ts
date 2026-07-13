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

function systemViewRecords(...records: Array<{
  kind: number
  taskId: number
  ticks: bigint
  timeUs: number
  deltaUs?: number
  aux0?: number
  aux1?: number
  flags?: number
  reserved?: number
}>): Uint8Array {
  const bytes = new Uint8Array(records.length * 48)
  const view = new DataView(bytes.buffer)
  records.forEach((record, index) => {
    const offset = index * 48
    view.setUint8(offset, record.kind)
    view.setUint8(offset + 1, record.flags ?? 0x07)
    view.setUint16(offset + 2, record.reserved ?? 0, true)
    view.setUint32(offset + 4, record.taskId, true)
    view.setBigUint64(offset + 8, record.ticks, true)
    view.setFloat64(offset + 16, record.timeUs, true)
    view.setFloat64(offset + 24, record.deltaUs ?? 0, true)
    view.setFloat64(offset + 32, record.aux0 ?? 0, true)
    view.setFloat64(offset + 40, record.aux1 ?? 0, true)
  })
  return bytes
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
  it('decodes SystemView records and returns only prefiltered visible intervals', () => {
    const { decoder, messages, transfers } = setup()
    decoder.handle({ type: 'configure', capacity: 8, channelCount: 1 })
    decoder.handle({
      type: 'frame',
      buffer: frame(1n, 4, systemViewRecords(
        { kind: 4, taskId: 1, ticks: 10n, timeUs: 10 },
        { kind: 5, taskId: 1, ticks: 20n, timeUs: 20 },
        { kind: 4, taskId: 2, ticks: 30n, timeUs: 30 },
        { kind: 5, taskId: 2, ticks: 50n, timeUs: 50 },
      ), StreamType.SYSTEMVIEW),
      connectionGeneration: 1,
      frameTicket: 1,
    })
    decoder.handle({ type: 'visible-range', requestId: 9, start: 25, end: 55, pixelWidth: 400 })

    const visible = messages.at(-1)
    expect(visible).toMatchObject({
      type: 'systemview-visible', requestId: 9, intervalCount: 1, eventCount: 2,
    })
    if (visible?.type !== 'systemview-visible') throw new Error('expected SystemView visible data')
    expect(Array.from(new Uint32Array(visible.taskIds))).toEqual([2])
    expect(Array.from(new Float64Array(visible.starts))).toEqual([30])
    expect(Array.from(new Float64Array(visible.ends))).toEqual([50])
    expect(transfers.at(-1)).toEqual([
      visible.taskIds, visible.starts, visible.ends, visible.startTicks, visible.endTicks,
    ])
  })

  it('rejects malformed SystemView record payloads', () => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 8, channelCount: 1 })
    decoder.handle({
      type: 'frame', buffer: frame(1n, 1, new Uint8Array(47), StreamType.SYSTEMVIEW),
      connectionGeneration: 1, frameTicket: 1,
    })
    expect(messages.at(-1)).toMatchObject({ type: 'error', code: 'INVALID_FRAME' })
  })

  it.each([
    { name: 'unknown kind', kind: 30, flags: 0x07, reserved: 0 },
    { name: 'unknown flags', kind: 4, flags: 0x80, reserved: 0 },
    { name: 'reserved bytes', kind: 4, flags: 0x07, reserved: 1 },
  ])('rejects $name in fixed SystemView records', ({ kind, flags, reserved }) => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 8, channelCount: 1 })
    decoder.handle({
      type: 'frame',
      buffer: frame(1n, 1, systemViewRecords({
        kind, flags, reserved, taskId: 1, ticks: 1n, timeUs: 1,
      }), StreamType.SYSTEMVIEW),
      connectionGeneration: 1, frameTicket: 1,
    })
    expect(messages.at(-1)).toMatchObject({ type: 'error', code: 'INVALID_FRAME' })
  })

  it.each(
    ([0, 0x07] as const).flatMap(flags =>
      ([16, 24, 32, 40] as const).flatMap(slotOffset =>
        [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY].map(value => ({
          flags, slotOffset, value,
        })),
      ),
    ),
  )('rejects non-finite slot $slotOffset with flags $flags atomically', ({ flags, slotOffset, value }) => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 8, channelCount: 1 })
    const payload = systemViewRecords(
      { kind: 4, taskId: 1, ticks: 1n, timeUs: 1 },
      { kind: 5, taskId: 1, ticks: 2n, timeUs: 2, flags },
    )
    new DataView(payload.buffer).setFloat64(48 + slotOffset, value, true)
    decoder.handle({
      type: 'frame', buffer: frame(1n, 2, payload, StreamType.SYSTEMVIEW),
      connectionGeneration: 1, frameTicket: 1,
    })
    expect(messages.at(-1)).toMatchObject({ type: 'error', code: 'INVALID_FRAME' })
    decoder.handle({ type: 'visible-range', requestId: 1, start: 0, end: 10, pixelWidth: 100 })
    expect(messages.at(-1)).toMatchObject({ type: 'render-envelope', sampleCount: 0 })
  })

  it('splits task intervals around nested ISR execution and resumes after outer exit', () => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 16, channelCount: 1 })
    decoder.handle({
      type: 'frame',
      buffer: frame(1n, 7, systemViewRecords(
        { kind: 4, taskId: 7, ticks: 10n, timeUs: 10 },
        { kind: 2, taskId: 15, ticks: 20n, timeUs: 20 },
        { kind: 2, taskId: 16, ticks: 22n, timeUs: 22 },
        { kind: 3, taskId: 0, ticks: 24n, timeUs: 24 },
        { kind: 3, taskId: 0, ticks: 30n, timeUs: 30 },
        { kind: 5, taskId: 7, ticks: 40n, timeUs: 40 },
        { kind: 17, taskId: 0, ticks: 41n, timeUs: 41 },
      ), StreamType.SYSTEMVIEW),
      connectionGeneration: 1, frameTicket: 1,
    })
    decoder.handle({ type: 'visible-range', requestId: 1, start: 0, end: 50, pixelWidth: 400 })
    const visible = messages.at(-1)
    if (visible?.type !== 'systemview-visible') throw new Error('expected SystemView visible data')
    expect(Array.from(new Uint32Array(visible.taskIds))).toEqual([7, 7])
    expect(Array.from(new Float64Array(visible.starts))).toEqual([10, 30])
    expect(Array.from(new Float64Array(visible.ends))).toEqual([20, 40])
  })

  it('breaks interval pairing across a dropped batch and reset clears pending context', () => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 8, channelCount: 1 })
    decoder.handle({
      type: 'frame', buffer: frame(1n, 1, systemViewRecords(
        { kind: 4, taskId: 1, ticks: 10n, timeUs: 10 },
      ), StreamType.SYSTEMVIEW), connectionGeneration: 1, frameTicket: 1,
    })
    decoder.handle({
      type: 'frame', buffer: frame(3n, 2, systemViewRecords(
        { kind: 5, taskId: 1, ticks: 20n, timeUs: 20 },
        { kind: 4, taskId: 2, ticks: 30n, timeUs: 30 },
      ), StreamType.SYSTEMVIEW), connectionGeneration: 1, frameTicket: 2,
    })
    decoder.handle({ type: 'visible-range', requestId: 1, start: 0, end: 35, pixelWidth: 400 })
    expect(messages.at(-1)).toMatchObject({ type: 'systemview-visible', intervalCount: 0 })

    decoder.handle({ type: 'reset' })
    decoder.handle({
      type: 'frame', buffer: frame(1n, 1, systemViewRecords(
        { kind: 5, taskId: 2, ticks: 40n, timeUs: 40 },
      ), StreamType.SYSTEMVIEW), connectionGeneration: 1, frameTicket: 3,
    })
    decoder.handle({ type: 'visible-range', requestId: 2, start: 0, end: 50, pixelWidth: 400 })
    const visible = messages.at(-1)
    expect(visible).toMatchObject({ type: 'systemview-visible', intervalCount: 0 })
  })

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
