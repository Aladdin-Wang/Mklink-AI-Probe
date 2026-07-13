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
  | {
      type: 'systemview-visible'
      requestId: number
      intervalCount: number
      eventCount: number
      latestTime: number
      taskIds: ArrayBuffer
      starts: ArrayBuffer
      ends: ArrayBuffer
      startTicks: ArrayBuffer
      endTicks: ArrayBuffer
      events: SystemViewEvent[]
    }

export interface SystemViewEvent {
  kind: string
  task_id?: number
  isr_id?: number
  t_ticks?: number
  t_us?: number
  cpu_delta_us?: number
  prio?: number
  cause?: number
  event_id?: number
}

interface SystemViewInterval {
  taskId: number
  start: number
  end: number
  startTick: bigint
  endTick: bigint
}

const SYSTEMVIEW_RECORD_SIZE = 48
const SYSTEMVIEW_HAS_TICKS = 0x01
const SYSTEMVIEW_HAS_TIME_US = 0x02
const SYSTEMVIEW_HAS_DELTA_US = 0x04
const SYSTEMVIEW_KIND_NAMES: Record<number, string> = {
  1: 'overflow', 2: 'isr_enter', 3: 'isr_exit', 4: 'task_start_exec',
  5: 'task_stop_exec', 6: 'task_start_ready', 7: 'task_stop_ready',
  8: 'task_create', 9: 'task_info', 10: 'trace_start', 11: 'trace_stop',
  12: 'systime_cycles', 13: 'systime_us', 14: 'sysdesc', 15: 'user_start',
  16: 'user_stop', 17: 'idle', 18: 'isr_to_scheduler', 19: 'timer_enter',
  20: 'timer_exit', 21: 'stack_info', 22: 'moduledesc', 24: 'init',
  23: 'raw',
  25: 'name_resource', 26: 'print_formatted', 27: 'nummodules',
  28: 'end_call', 29: 'task_terminate',
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
  private capacity = 0
  private systemViewMode = false
  private systemViewEvents: SystemViewEvent[] = []
  private systemViewIntervals: SystemViewInterval[] = []
  private currentTask: { taskId: number; start: number; tick: bigint } | null = null
  private suspendedTask: { taskId: number } | null = null
  private isrDepth = 0
  private latestSystemViewTime = 0

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
      this.capacity = capacity
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
      } else if (decoded.streamType === StreamType.SYSTEMVIEW) {
        this.appendSystemViewFrame(decoded.sequence, decoded.itemCount, decoded.payload)
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

  private noteDataSequence(sequence: bigint): void {
    if (this.lastDataSequence !== null && sequence > this.lastDataSequence + 1n) {
      this.transportDroppedBatches += Number(sequence - this.lastDataSequence - 1n)
    }
    this.lastDataSequence = sequence
  }

  private appendSystemViewFrame(sequence: bigint, itemCount: number, payload: ArrayBuffer): void {
    if (payload.byteLength !== itemCount * SYSTEMVIEW_RECORD_SIZE) {
      throw new RangeError('SystemView payload must contain fixed 48-byte records')
    }
    const view = new DataView(payload)
    const decodedEvents: Array<{ event: SystemViewEvent; ticks: bigint }> = []
    for (let offset = 0; offset < payload.byteLength; offset += SYSTEMVIEW_RECORD_SIZE) {
      const kindId = view.getUint8(offset)
      const kind = SYSTEMVIEW_KIND_NAMES[kindId]
      const flags = view.getUint8(offset + 1)
      if (!kind || (flags & ~(SYSTEMVIEW_HAS_TICKS | SYSTEMVIEW_HAS_TIME_US | SYSTEMVIEW_HAS_DELTA_US)) !== 0
        || view.getUint16(offset + 2, true) !== 0) {
        throw new RangeError('malformed SystemView record')
      }
      const contextId = view.getUint32(offset + 4, true)
      const ticks = view.getBigUint64(offset + 8, true)
      const timeUs = view.getFloat64(offset + 16, true)
      const deltaUs = view.getFloat64(offset + 24, true)
      const aux0 = view.getFloat64(offset + 32, true)
      const aux1 = view.getFloat64(offset + 40, true)
      if (((flags & SYSTEMVIEW_HAS_TIME_US) && !Number.isFinite(timeUs))
        || ((flags & SYSTEMVIEW_HAS_DELTA_US) && !Number.isFinite(deltaUs))
        || !Number.isFinite(aux0) || !Number.isFinite(aux1)) {
        throw new RangeError('SystemView numeric fields must be finite')
      }
      const event: SystemViewEvent = { kind }
      if (flags & SYSTEMVIEW_HAS_TICKS) event.t_ticks = Number(ticks)
      if (flags & SYSTEMVIEW_HAS_TIME_US) event.t_us = timeUs
      if (flags & SYSTEMVIEW_HAS_DELTA_US) event.cpu_delta_us = deltaUs
      if ([4, 5, 6, 7, 8, 9, 21, 29].includes(kindId)) event.task_id = contextId
      if (kindId === 2) event.isr_id = contextId
      if (kindId === 9) event.prio = Math.trunc(aux0)
      if (kindId === 7) event.cause = Math.trunc(aux0)
      if (kindId === 23) {
        event.kind = `raw_${contextId}`
        event.event_id = contextId
      }
      decodedEvents.push({ event, ticks })
    }
    const previousSequence = this.lastDataSequence
    this.noteDataSequence(sequence)
    if (previousSequence !== null && sequence > previousSequence + 1n) {
      this.abandonSystemViewContext()
    }
    this.systemViewMode = true
    for (const decoded of decodedEvents) {
      this.ingestSystemViewEvent(decoded.event, decoded.ticks)
    }
    this.trimSystemViewBuffers()
  }

  private ingestSystemViewEvent(event: SystemViewEvent, ticks: bigint): void {
    const time = event.t_us ?? event.t_ticks ?? 0
    this.latestSystemViewTime = Math.max(this.latestSystemViewTime, time)
    if (event.kind === 'task_start_exec' && event.task_id !== undefined) {
      this.suspendedTask = null
      this.isrDepth = 0
      this.closeCurrentSystemViewInterval(time, ticks)
      this.currentTask = { taskId: event.task_id, start: time, tick: ticks }
    } else if (
      (event.kind === 'task_stop_exec' || event.kind === 'task_stop_ready')
      && event.task_id === this.currentTask?.taskId
    ) {
      this.closeCurrentSystemViewInterval(time, ticks)
      if (this.suspendedTask?.taskId === event.task_id) this.suspendedTask = null
    } else if (event.kind === 'isr_enter') {
      if (this.isrDepth === 0 && this.currentTask) {
        this.suspendedTask = { taskId: this.currentTask.taskId }
        this.closeCurrentSystemViewInterval(time, ticks)
      }
      this.isrDepth += 1
    } else if (event.kind === 'isr_exit') {
      if (this.isrDepth > 0) this.isrDepth -= 1
      if (this.isrDepth === 0 && this.suspendedTask) {
        this.currentTask = { taskId: this.suspendedTask.taskId, start: time, tick: ticks }
        this.suspendedTask = null
      }
    } else if (event.kind === 'isr_to_scheduler' || event.kind === 'overflow') {
      this.abandonSystemViewContext()
    } else if (event.kind === 'idle') {
      this.closeCurrentSystemViewInterval(time, ticks)
      this.suspendedTask = null
      this.isrDepth = 0
    }
    this.systemViewEvents.push(event)
  }

  private closeCurrentSystemViewInterval(end: number, endTick: bigint): void {
    const current = this.currentTask
    if (current && end > current.start) {
      this.systemViewIntervals.push({
        taskId: current.taskId,
        start: current.start,
        end,
        startTick: current.tick,
        endTick,
      })
    }
    this.currentTask = null
  }

  private abandonSystemViewContext(): void {
    this.currentTask = null
    this.suspendedTask = null
    this.isrDepth = 0
  }

  private trimSystemViewBuffers(): void {
    if (this.systemViewEvents.length > this.capacity) {
      this.systemViewEvents.splice(0, this.systemViewEvents.length - this.capacity)
    }
    if (this.systemViewIntervals.length > this.capacity) {
      this.systemViewIntervals.splice(0, this.systemViewIntervals.length - this.capacity)
    }
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
    if (this.systemViewMode) {
      this.systemViewVisibleRange(message)
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

  private systemViewVisibleRange(message: Extract<WorkerInput, { type: 'visible-range' }>): void {
    const visible = this.systemViewIntervals.filter(
      interval => interval.end >= message.start && interval.start <= message.end,
    )
    const taskIds = new Uint32Array(visible.length)
    const starts = new Float64Array(visible.length)
    const ends = new Float64Array(visible.length)
    const startTicks = new BigUint64Array(visible.length)
    const endTicks = new BigUint64Array(visible.length)
    visible.forEach((interval, index) => {
      taskIds[index] = interval.taskId
      starts[index] = interval.start
      ends[index] = interval.end
      startTicks[index] = interval.startTick
      endTicks[index] = interval.endTick
    })
    const events = this.systemViewEvents.filter(event => {
      const time = event.t_us ?? event.t_ticks ?? 0
      return time >= message.start && time <= message.end
    })
    const output: Extract<WorkerOutput, { type: 'systemview-visible' }> = {
      type: 'systemview-visible',
      requestId: message.requestId,
      intervalCount: visible.length,
      eventCount: events.length,
      latestTime: this.latestSystemViewTime,
      taskIds: taskIds.buffer,
      starts: starts.buffer,
      ends: ends.buffer,
      startTicks: startTicks.buffer,
      endTicks: endTicks.buffer,
      events: events.slice(-120),
    }
    this.post(output, [
      output.taskIds, output.starts, output.ends, output.startTicks, output.endTicks,
    ])
  }

  private reset(): void {
    this.ring?.reset()
    this.systemViewMode = false
    this.systemViewEvents = []
    this.systemViewIntervals = []
    this.currentTask = null
    this.suspendedTask = null
    this.isrDepth = 0
    this.latestSystemViewTime = 0
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
      bufferedSamples: this.systemViewMode ? this.systemViewEvents.length : (this.ring?.length ?? 0),
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
