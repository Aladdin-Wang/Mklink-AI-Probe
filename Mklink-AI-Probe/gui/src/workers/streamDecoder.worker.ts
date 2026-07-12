import { decodeFrame, StreamType } from '../lib/stream/protocol'
import { TypedRingBuffer } from '../lib/stream/typedRingBuffer'

export type WorkerInput =
  | { type: 'configure'; capacity: number; channelCount: number }
  | {
      type: 'frame'
      buffer: ArrayBuffer
      connectionGeneration: number
      frameTicket: number
    }
  | { type: 'visible-range'; requestId: number; start: number; end: number; pixelWidth: number }
  | { type: 'reset' }

export interface StreamTelemetry {
  readonly type: 'telemetry'
  readonly acceptedFrames: number
  readonly acceptedConnectionGeneration: number | null
  readonly acceptedFrameTicket: number | null
  readonly bufferedSamples: number
  readonly transportDroppedBatches: number
  readonly backendDroppedBatches: number
  readonly backendDroppedItems: number
  readonly backendDroppedBytes: number
  readonly lastSequence: bigint | null
}

export type WorkerOutput =
  | { type: 'channels'; channelCount: number }
  | StreamTelemetry
  | {
      type: 'render-envelope'
      mode: 'raw-visible'
      timestampKind: 'batch-milliseconds'
      requestId: number
      pixelWidth: number
      channelCount: number
      sampleCount: number
      times: ArrayBuffer
      values: ArrayBuffer
    }
  | {
      type: 'error'
      code: 'INVALID_CONFIG' | 'NOT_CONFIGURED' | 'INVALID_FRAME' | 'INVALID_RANGE'
      message: string
      connectionGeneration?: number
      frameTicket?: number
    }

type PostOutput = (message: WorkerOutput, transfer?: Transferable[]) => void

interface BackendDrops {
  dropped_batches?: unknown
  dropped_items?: unknown
  dropped_bytes?: unknown
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
    ? value
    : null
}

export class StreamDecoder {
  private readonly post: PostOutput
  private ring: TypedRingBuffer | null = null
  private lastDataSequence: bigint | null = null
  private transportDroppedBatches = 0
  private backendDroppedBatches = 0
  private backendDroppedItems = 0
  private backendDroppedBytes = 0
  private acceptedFrames = 0

  constructor(post: PostOutput) {
    this.post = post
  }

  handle(message: WorkerInput): void {
    switch (message.type) {
      case 'configure':
        this.configure(message.capacity, message.channelCount)
        break
      case 'frame':
        this.receiveFrame(
          message.buffer,
          message.connectionGeneration,
          message.frameTicket,
        )
        break
      case 'visible-range':
        this.visibleRange(message)
        break
      case 'reset':
        this.reset()
        break
    }
  }

  private configure(capacity: number, channelCount: number): void {
    try {
      this.ring = new TypedRingBuffer(capacity, channelCount)
      this.clearTelemetry()
      this.post({ type: 'channels', channelCount })
      this.post(this.telemetry())
    } catch (error) {
      this.error('INVALID_CONFIG', error)
    }
  }

  private receiveFrame(
    buffer: ArrayBuffer,
    connectionGeneration: number,
    frameTicket: number,
  ): void {
    if (!this.ring) {
      this.post({ type: 'error', code: 'NOT_CONFIGURED', message: 'configure the worker before frames' })
      return
    }
    try {
      if (
        !Number.isSafeInteger(connectionGeneration)
        || connectionGeneration <= 0
        || !Number.isSafeInteger(frameTicket)
        || frameTicket <= 0
      ) {
        throw new RangeError('frame connection generation and ticket must be positive integers')
      }
      const decoded = decodeFrame(buffer)
      if (decoded.streamType === StreamType.CONTROL) {
        this.updateBackendDrops(decoded.payload)
      } else {
        this.appendNumericFrame(decoded.sequence, decoded.timestampNs, decoded.itemCount, decoded.payload)
      }
      this.acceptedFrames += 1
      this.post(this.telemetry(connectionGeneration, frameTicket))
    } catch (error) {
      this.error('INVALID_FRAME', error, connectionGeneration, frameTicket)
    }
  }

  private appendNumericFrame(
    sequence: bigint,
    timestampNs: bigint,
    itemCount: number,
    payload: ArrayBuffer,
  ): void {
    const ring = this.ring as TypedRingBuffer
    const expectedBytes = itemCount * ring.channelCount * Float32Array.BYTES_PER_ELEMENT
    if (payload.byteLength !== expectedBytes) {
      throw new RangeError(
        `numeric payload must be sample-major (${itemCount} samples x ${ring.channelCount} channels)`,
      )
    }
    if (this.lastDataSequence !== null && sequence > this.lastDataSequence + 1n) {
      const gap = sequence - this.lastDataSequence - 1n
      this.transportDroppedBatches += Number(gap)
    }
    this.lastDataSequence = sequence

    const batchMilliseconds = Number(timestampNs) / 1_000_000
    const timestamps = new Float64Array(itemCount)
    timestamps.fill(batchMilliseconds)
    // V1 has only one batch timestamp. Equal per-sample keys preserve order in
    // the ring without inventing a sampling period; producers may extend the
    // protocol with real sample timing later.
    ring.appendBatch(timestamps, new Float32Array(payload))
  }

  private updateBackendDrops(payload: ArrayBuffer): void {
    const parsed = JSON.parse(new TextDecoder().decode(payload)) as BackendDrops
    const batches = nonNegativeInteger(parsed.dropped_batches)
    const items = nonNegativeInteger(parsed.dropped_items)
    const bytes = nonNegativeInteger(parsed.dropped_bytes)
    if (batches === null || items === null || bytes === null) {
      throw new TypeError('CONTROL drop counters must be non-negative integers')
    }
    // Hub counters are cumulative. max() avoids regressions from a stale
    // heartbeat while keeping backend loss independent of transport gaps.
    this.backendDroppedBatches = Math.max(this.backendDroppedBatches, batches)
    this.backendDroppedItems = Math.max(this.backendDroppedItems, items)
    this.backendDroppedBytes = Math.max(this.backendDroppedBytes, bytes)
  }

  private visibleRange(message: Extract<WorkerInput, { type: 'visible-range' }>): void {
    if (!this.ring) {
      this.post({ type: 'error', code: 'NOT_CONFIGURED', message: 'configure the worker before ranges' })
      return
    }
    if (
      !Number.isFinite(message.start)
      || !Number.isFinite(message.end)
      || message.end < message.start
      || !Number.isInteger(message.pixelWidth)
      || message.pixelWidth <= 0
    ) {
      this.post({ type: 'error', code: 'INVALID_RANGE', message: 'visible range or pixel width is invalid' })
      return
    }
    const visibleLength = this.ring.visibleRangeLength(message.start, message.end)
    const times = new Float64Array(visibleLength)
    const values = new Float32Array(visibleLength * this.ring.channelCount)
    const count = this.ring.copyVisibleRange(message.start, message.end, { times, values })
    const output: Extract<WorkerOutput, { type: 'render-envelope' }> = {
      type: 'render-envelope',
      mode: 'raw-visible',
      timestampKind: 'batch-milliseconds',
      requestId: message.requestId,
      pixelWidth: message.pixelWidth,
      channelCount: this.ring.channelCount,
      sampleCount: count,
      times: times.buffer,
      values: values.buffer,
    }
    this.post(output, [output.times, output.values])
  }

  private reset(): void {
    this.ring?.reset()
    this.clearTelemetry()
    this.post(this.telemetry())
  }

  private clearTelemetry(): void {
    this.lastDataSequence = null
    this.transportDroppedBatches = 0
    this.backendDroppedBatches = 0
    this.backendDroppedItems = 0
    this.backendDroppedBytes = 0
    this.acceptedFrames = 0
  }

  private telemetry(
    acceptedConnectionGeneration: number | null = null,
    acceptedFrameTicket: number | null = null,
  ): StreamTelemetry {
    return {
      type: 'telemetry',
      acceptedFrames: this.acceptedFrames,
      acceptedConnectionGeneration,
      acceptedFrameTicket,
      bufferedSamples: this.ring?.length ?? 0,
      transportDroppedBatches: this.transportDroppedBatches,
      backendDroppedBatches: this.backendDroppedBatches,
      backendDroppedItems: this.backendDroppedItems,
      backendDroppedBytes: this.backendDroppedBytes,
      lastSequence: this.lastDataSequence,
    }
  }

  private error(
    code: Extract<WorkerOutput, { type: 'error' }>['code'],
    error: unknown,
    connectionGeneration?: number,
    frameTicket?: number,
  ): void {
    this.post({
      type: 'error',
      code,
      message: error instanceof Error ? error.message : String(error),
      ...(connectionGeneration === undefined ? {} : { connectionGeneration }),
      ...(frameTicket === undefined ? {} : { frameTicket }),
    })
  }
}

const scope = globalThis as typeof globalThis & {
  postMessage?: (message: WorkerOutput, transfer?: Transferable[]) => void
  onmessage?: ((event: MessageEvent<WorkerInput>) => void) | null
}

if (typeof document === 'undefined' && typeof scope.postMessage === 'function') {
  const decoder = new StreamDecoder((message, transfer = []) => scope.postMessage?.(message, transfer))
  scope.onmessage = event => decoder.handle(event.data)
}
