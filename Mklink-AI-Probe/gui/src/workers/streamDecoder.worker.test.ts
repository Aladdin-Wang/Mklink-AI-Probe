import { describe, expect, it, vi } from 'vitest'
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
  flags = 0,
): ArrayBuffer {
  const buffer = new ArrayBuffer(36 + payload.byteLength)
  const bytes = new Uint8Array(buffer)
  bytes.set([0x4d, 0x4b, 0x53, 0x54])
  const view = new DataView(buffer)
  view.setUint8(4, 1)
  view.setUint8(5, streamType)
  view.setUint8(6, flags)
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

function systemViewTaskPairs(firstTask: number, pairCount: number, firstTick: bigint): Uint8Array {
  const bytes = new Uint8Array(pairCount * 2 * 48)
  const view = new DataView(bytes.buffer)
  for (let pair = 0; pair < pairCount; pair++) {
    for (let edge = 0; edge < 2; edge++) {
      const offset = (pair * 2 + edge) * 48
      const tick = firstTick + BigInt(pair * 2 + edge)
      view.setUint8(offset, edge === 0 ? 4 : 5)
      view.setUint8(offset + 1, 0x01)
      view.setUint32(offset + 4, firstTask + pair, true)
      view.setBigUint64(offset + 8, tick, true)
    }
  }
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
  it('emits each VOFA sample-major batch as a transferable typed envelope', () => {
    const { decoder, messages, transfers } = setup()
    decoder.handle({ type: 'configure', capacity: 16, channelCount: 2 })
    decoder.handle({
      type: 'frame',
      buffer: frame(
        7n, 3, floats(1, 10, 2, 20, 3, 30),
        StreamType.WAVEFORM, 5_000_000n, 0x01,
      ),
      connectionGeneration: 1,
      frameTicket: 1,
    })

    const batch = messages.find(message => message.type === 'waveform-batch')
    if (batch?.type !== 'waveform-batch') throw new Error('expected waveform batch')
    expect(batch).toMatchObject({
      sequence: 7n,
      timestampNs: 5_000_000n,
      itemCount: 3,
      channelCount: 2,
      layout: 'sample-major-float32',
    })
    expect(Array.from(new Float32Array(batch.values))).toEqual([1, 10, 2, 20, 3, 30])
    const times = new Float64Array((batch as any).times)
    expect(times).toHaveLength(3)
    expect(times[0]).toBeLessThan(times[1])
    expect(times[1]).toBeLessThan(times[2])
    expect(transfers[messages.indexOf(batch)]).toEqual([batch.values, (batch as any).times])
  })

  it.each([0x02, 0x03])(
    'rejects unknown VOFA layout flags 0x%s before mutating the typed ring',
    flags => {
      const { decoder, messages } = setup()
      decoder.handle({ type: 'configure', capacity: 16, channelCount: 1 })
      decoder.handle({
        type: 'frame',
        buffer: frame(1n, 1, floats(9), StreamType.WAVEFORM, 1_000_000n, flags),
        connectionGeneration: 1,
        frameTicket: 1,
      })
      expect(messages.at(-1)).toMatchObject({ type: 'error', code: 'INVALID_FRAME' })

      decoder.handle({
        type: 'visible-range', requestId: 1, start: 0, end: 10, pixelWidth: 10,
      })
      expect(messages.at(-1)).toMatchObject({ type: 'render-envelope', pointCount: 0 })
    },
  )

  it('uses VOFA frame metadata to reconfigure a changed channel count', () => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 16, channelCount: 1 })
    decoder.handle({
      type: 'frame',
      buffer: frame(
        1n, 2, floats(1, 10, 2, 20), StreamType.WAVEFORM,
        1_000_000n, 0x01,
      ),
      connectionGeneration: 1,
      frameTicket: 1,
    })

    const batch = messages.find(message => message.type === 'waveform-batch')
    expect(batch).toMatchObject({ type: 'waveform-batch', channelCount: 2, itemCount: 2 })
    expect(messages).toContainEqual({ type: 'channels', channelCount: 2 })
    expect(messages.at(-1)).toMatchObject({ type: 'telemetry', bufferedSamples: 2 })
  })

  it.each([
    {
      name: 'unknown flags',
      invalid: () => frame(2n, 1, floats(9), StreamType.WAVEFORM, 2_000_000n, 0x03),
    },
    {
      name: 'misaligned length',
      invalid: () => frame(2n, 2, floats(9), StreamType.WAVEFORM, 2_000_000n, 0x01),
    },
    {
      name: 'more than 64 channels',
      invalid: () => frame(
        2n, 1, floats(...Array.from({ length: 65 }, (_, index) => index)),
        StreamType.WAVEFORM, 2_000_000n, 0x01,
      ),
    },
    {
      name: 'non-finite dynamic channel payload',
      invalid: () => frame(2n, 1, floats(9, Number.NaN), StreamType.WAVEFORM, 2_000_000n, 0x01),
    },
    {
      name: 'duplicate sequence',
      invalid: () => frame(1n, 1, floats(9), StreamType.WAVEFORM, 2_000_000n, 0x01),
    },
  ])('rejects $name before changing sequence, configuration, telemetry, or ring', ({ invalid }) => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 16, channelCount: 1 })
    decoder.handle({
      type: 'frame', buffer: frame(
        1n, 2, floats(1, 2), StreamType.WAVEFORM, 1_000_000n, 0x01,
      ), connectionGeneration: 1, frameTicket: 1,
    })
    const telemetryBefore = messages.filter(message => message.type === 'telemetry').at(-1)
    const channelMessagesBefore = messages.filter(message => message.type === 'channels').length

    decoder.handle({
      type: 'frame', buffer: invalid(), connectionGeneration: 1, frameTicket: 2,
    })

    expect(messages.at(-1)).toMatchObject({ type: 'error', code: 'INVALID_FRAME' })
    expect(messages.filter(message => message.type === 'telemetry').at(-1)).toEqual(telemetryBefore)
    expect(messages.filter(message => message.type === 'channels')).toHaveLength(channelMessagesBefore)
    decoder.handle({ type: 'visible-range', requestId: 90, start: -1, end: 10, pixelWidth: 10 })
    const visible = messages.at(-1) as any
    expect(visible).toMatchObject({
      type: 'render-envelope', mode: 'min-max-v1', channelCount: 1, pointCount: 2,
    })
    expect(Array.from(new Float32Array(visible.values))).toEqual([1, 2])
  })

  it('assigns strictly monotonic sample times across repeated timestamps, gaps, and wrap', () => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 4, channelCount: 1 })
    const emittedTimes: number[] = []
    const send = (sequence: bigint, timestampNs: bigint, values: number[]) => {
      decoder.handle({
        type: 'frame', buffer: frame(
          sequence, values.length, floats(...values), StreamType.WAVEFORM, timestampNs, 0x01,
        ), connectionGeneration: 1, frameTicket: Number(sequence),
      })
      const batch = messages.filter(message => message.type === 'waveform-batch').at(-1) as any
      emittedTimes.push(...new Float64Array(batch.times))
    }
    send(1n, 1_000_000n, [1, 2])
    send(2n, 1_000_000n, [3, 4])
    send(3n, 100_000_000_000n, [5, 6])
    send(4n, 100_001_000_000n, [7, 8])

    expect(emittedTimes.every((time, index) => index === 0 || time > emittedTimes[index - 1]))
      .toBe(true)
    decoder.handle({
      type: 'visible-range', requestId: 91,
      start: emittedTimes[0], end: emittedTimes.at(-1)!, pixelWidth: 10,
    })
    const visible = messages.at(-1) as any
    const selectedTimes = new Float64Array(visible.times)
    expect(Array.from(selectedTimes).every(
      (time, index) => index === 0 || time > selectedTimes[index - 1],
    )).toBe(true)
  })

  it('bounds a 200k x 8 numeric visible envelope to two points per pixel and channel', () => {
    const { decoder, messages } = setup()
    const channelCount = 8
    const sampleCount = 200_000
    const batchSamples = 2_000
    decoder.handle({ type: 'configure', capacity: sampleCount, channelCount })
    for (let base = 0; base < sampleCount; base += batchSamples) {
      const values = new Float32Array(batchSamples * channelCount)
      for (let sample = 0; sample < batchSamples; sample += 1) {
        for (let channel = 0; channel < channelCount; channel += 1) {
          values[sample * channelCount + channel] = Math.sin((base + sample) / (channel + 1))
        }
      }
      const sequence = BigInt(base / batchSamples + 1)
      decoder.handle({
        type: 'frame', buffer: frame(
          sequence, batchSamples, new Uint8Array(values.buffer), StreamType.WAVEFORM,
          BigInt(base + batchSamples) * 1_000_000n, 0x01,
        ), connectionGeneration: 1, frameTicket: Number(sequence),
      })
    }
    decoder.handle({
      type: 'visible-range', requestId: 92, start: 0, end: sampleCount, pixelWidth: 320,
    })

    const visible = messages.at(-1) as any
    expect(visible).toMatchObject({
      type: 'render-envelope', mode: 'min-max-v1', channelCount,
      candidateSampleCount: sampleCount,
    })
    expect(visible.pointCount).toBeLessThanOrEqual(2 * 320 * channelCount)
    expect(new Uint32Array(visible.channelOffsets)).toHaveLength(channelCount + 1)
    expect(new Uint32Array(visible.timeIndices)).toHaveLength(visible.pointCount)
    expect(new Float32Array(visible.values)).toHaveLength(visible.pointCount)
    expect(new Float64Array(visible.times).length).toBeLessThanOrEqual(visible.pointCount)
  }, 15_000)
  it('preserves ticks above Number.MAX_SAFE_INTEGER and exposes relative plot coordinates', () => {
    const { decoder, messages } = setup()
    const origin = 9_007_199_254_740_993n
    decoder.handle({ type: 'configure', capacity: 8, channelCount: 1 })
    decoder.handle({
      type: 'frame',
      buffer: frame(1n, 2, systemViewRecords(
        { kind: 4, taskId: 7, ticks: origin, timeUs: 0, flags: 0x01 },
        { kind: 5, taskId: 7, ticks: origin + 10n, timeUs: 0, flags: 0x01 },
      ), StreamType.SYSTEMVIEW),
      connectionGeneration: 1, frameTicket: 1,
    })
    decoder.handle({ type: 'visible-range', requestId: 1, start: 0, end: 20, pixelWidth: 100 })

    const visible = messages.at(-1)
    if (visible?.type !== 'systemview-visible') throw new Error('expected SystemView visible data')
    expect(visible.tickOrigin).toBe(origin)
    expect(visible.latestTime).toBe(10)
    expect(Array.from(new Float64Array(visible.starts))).toEqual([0])
    expect(Array.from(new Float64Array(visible.ends))).toEqual([10])
    expect(Array.from(new BigUint64Array(visible.startTicks))).toEqual([origin])
    expect(Array.from(new BigUint64Array(visible.endTicks))).toEqual([origin + 10n])
    expect(visible.events[0]).toMatchObject({
      t_ticks: origin, t_ticks_exact: origin.toString(), t_relative: 0,
    })
  })

  it('bounds interval envelopes to two records per pixel and scans only visible candidates', () => {
    const { decoder, messages } = setup()
    decoder.handle({ type: 'configure', capacity: 4_000, channelCount: 1 })
    decoder.handle({
      type: 'frame', buffer: frame(
        1n, 2_000, systemViewTaskPairs(1, 1_000, 1_000n), StreamType.SYSTEMVIEW,
      ), connectionGeneration: 1, frameTicket: 1,
    })
    decoder.handle({ type: 'visible-range', requestId: 2, start: 1_800, end: 2_000, pixelWidth: 10 })

    const visible = messages.at(-1)
    expect(visible).toMatchObject({ type: 'systemview-visible' })
    if (visible?.type !== 'systemview-visible') throw new Error('expected SystemView visible data')
    expect(visible.candidateIntervalCount).toBeLessThanOrEqual(102)
    expect(visible.intervalCount).toBeLessThanOrEqual(20)
  })

  it('keeps full-capacity append O(1) without Array.splice during 500 more batches', () => {
    const { decoder, messages } = setup()
    const splice = vi.spyOn(Array.prototype, 'splice')
    let spliceCalls = 0
    decoder.handle({ type: 'configure', capacity: 100_000, channelCount: 1 })
    let sequence = 1n
    let tick = 1n
    const started = performance.now()
    try {
      for (let batch = 0; batch < 200; batch++) {
        const payload = systemViewTaskPairs(1, 250, tick)
        decoder.handle({
          type: 'frame', buffer: frame(sequence++, 500, payload, StreamType.SYSTEMVIEW),
          connectionGeneration: 1, frameTicket: Number(sequence),
        })
        tick += 500n
      }
      for (let batch = 0; batch < 500; batch++) {
        const payload = systemViewTaskPairs(1, 250, tick)
        decoder.handle({
          type: 'frame', buffer: frame(sequence++, 500, payload, StreamType.SYSTEMVIEW),
          connectionGeneration: 1, frameTicket: Number(sequence),
        })
        tick += 500n
      }
    } finally {
      spliceCalls = splice.mock.calls.length
      splice.mockRestore()
    }
    expect(spliceCalls).toBe(0)
    expect(performance.now() - started).toBeLessThan(5_000)
    expect(messages.at(-1)).toMatchObject({ type: 'telemetry', bufferedSamples: 100_000 })
    const latestOffset = Number(tick - 1n - 1n)
    decoder.handle({
      type: 'visible-range', requestId: 99,
      start: latestOffset - 100, end: latestOffset, pixelWidth: 10,
    })
    const visible = messages.at(-1)
    if (visible?.type !== 'systemview-visible') throw new Error('expected SystemView visible data')
    expect(visible.candidateIntervalCount).toBeLessThanOrEqual(52)
    expect(visible.intervalCount).toBeLessThanOrEqual(20)
  }, 10_000)

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
    decoder.handle({ type: 'visible-range', requestId: 9, start: 15, end: 45, pixelWidth: 400 })

    const visible = messages.at(-1)
    expect(visible).toMatchObject({
      type: 'systemview-visible', requestId: 9, intervalCount: 1, eventCount: 2,
    })
    if (visible?.type !== 'systemview-visible') throw new Error('expected SystemView visible data')
    expect(Array.from(new Uint32Array(visible.taskIds))).toEqual([2])
    expect(Array.from(new Float64Array(visible.starts))).toEqual([20])
    expect(Array.from(new Float64Array(visible.ends))).toEqual([40])
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
    expect(messages.at(-1)).toMatchObject({ type: 'render-envelope', pointCount: 0 })
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
    expect(Array.from(new Float64Array(visible.starts))).toEqual([0, 20])
    expect(Array.from(new Float64Array(visible.ends))).toEqual([10, 30])
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
    decoder.handle({ type: 'visible-range', requestId: 7, start: 0, end: 5, pixelWidth: 320 })

    const envelope = messages.at(-1)
    expect(envelope).toMatchObject({
      type: 'render-envelope',
      mode: 'min-max-v1',
      requestId: 7,
      pixelWidth: 320,
      channelCount: 2,
      pointCount: 4,
      candidateSampleCount: 3,
      timestampKind: 'sample-milliseconds',
    })
    if (envelope?.type !== 'render-envelope') throw new Error('expected envelope')
    expect(Array.from(new Uint32Array(envelope.channelOffsets))).toEqual([0, 2, 4])
    expect(Array.from(new Float64Array(envelope.times))).toEqual([4.999998, 5])
    expect(Array.from(new Uint32Array(envelope.timeIndices))).toEqual([0, 1, 0, 1])
    expect(Array.from(new Float32Array(envelope.values))).toEqual([1, 3, 10, 30])
    expect(transfers.at(-1)).toEqual([
      envelope.channelOffsets, envelope.times, envelope.timeIndices, envelope.values,
    ])
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
