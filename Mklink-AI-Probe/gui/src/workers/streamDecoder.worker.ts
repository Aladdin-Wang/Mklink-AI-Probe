import {
  decodeFrame, RTT_RAW_UTF8_LINES, StreamType, SUPERWATCH_METADATA_JSON,
  SUPERWATCH_SAMPLE_MAJOR_FLOAT32, WAVEFORM_SAMPLE_MAJOR_FLOAT32, type StreamFrame,
} from '../lib/stream/protocol'
import { TypedRingBuffer } from '../lib/stream/typedRingBuffer'
import {
  safeTickDifference,
  SystemViewEventRing,
  SystemViewIntervalRing,
} from '../lib/stream/systemViewRing'

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
      type: 'rtt-lines'
      sequence: bigint
      lines: Array<{ timestampNs: bigint; level: 'raw' | 'data' | 'warning' | 'error'; text: string }>
    }
  | {
      type: 'superwatch-metadata'
      version: number
      channels: Array<Record<string, unknown> & { name: string }>
    }
  | {
      type: 'waveform-batch'
      sequence: bigint
      timestampNs: bigint
      itemCount: number
      channelCount: number
      layout: 'sample-major-float32'
      values: ArrayBuffer
      times: ArrayBuffer
    }
  | {
      type: 'render-envelope'
      mode: 'min-max-v1'
      timestampKind: 'sample-milliseconds'
      requestId: number
      pixelWidth: number
      channelCount: number
      pointCount: number
      candidateSampleCount: number
      channelOffsets: ArrayBuffer
      times: ArrayBuffer
      timeIndices: ArrayBuffer
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
      candidateIntervalCount: number
      eventCount: number
      latestTime: number
      tickOrigin: bigint
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
  t_ticks?: bigint
  t_ticks_exact?: string
  t_relative?: number
  t_us?: number
  cpu_delta_us?: number
  prio?: number
  cause?: number
  event_id?: number
}

const SYSTEMVIEW_RECORD_SIZE = 48
const MAX_WAVEFORM_CHANNELS = 64
const RTT_LINE_HEADER_SIZE = 13
const RTT_LEVEL_NAMES = ['raw', 'data', 'warning', 'error'] as const
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
  private systemViewMode = false
  private systemViewEvents: SystemViewEventRing<SystemViewEvent> | null = null
  private systemViewIntervals: SystemViewIntervalRing | null = null
  private currentTask: { taskId: number; tick: bigint } | null = null
  private suspendedTask: { taskId: number } | null = null
  private isrDepth = 0
  private tickOrigin: bigint | null = null
  private latestSystemViewTick = 0n
  private lastNumericTimestampMs: number | null = null
  private lastNumericSpacingMs: number | null = null
  private timeIndexScratch: Int32Array | null = null
  private superwatchMetadataVersion = 0

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
      this.timeIndexScratch = new Int32Array(capacity)
      this.systemViewEvents = new SystemViewEventRing<SystemViewEvent>(capacity)
      this.systemViewIntervals = new SystemViewIntervalRing(capacity)
      this.systemViewMode = false
      this.currentTask = null
      this.suspendedTask = null
      this.isrDepth = 0
      this.tickOrigin = null
      this.latestSystemViewTick = 0n
      this.lastNumericTimestampMs = null
      this.lastNumericSpacingMs = null
      this.superwatchMetadataVersion = 0
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
      } else if (decoded.streamType === StreamType.WAVEFORM) {
        this.acceptWaveformFrame(decoded)
      } else if (decoded.streamType === StreamType.RTT_RAW) {
        this.acceptRttRawFrame(decoded)
      } else if (decoded.streamType === StreamType.SUPERWATCH) {
        this.acceptSuperWatchFrame(decoded)
      } else {
        throw new RangeError('unsupported stream frame type')
      }
      this.acceptedFrames += 1
      this.post(this.telemetry(connectionGeneration, frameTicket))
    } catch (error) {
      this.error('INVALID_FRAME', error, connectionGeneration, frameTicket)
    }
  }

  private requireNextSequence(sequence: bigint, label: string): void {
    if (sequence <= 0n || (this.lastDataSequence !== null && sequence <= this.lastDataSequence)) {
      throw new RangeError(`${label} sequence must increase strictly`)
    }
  }

  private commitSequence(sequence: bigint): void {
    if (this.lastDataSequence !== null && sequence > this.lastDataSequence + 1n) {
      this.transportDroppedBatches += Number(sequence - this.lastDataSequence - 1n)
    }
    this.lastDataSequence = sequence
  }

  private acceptRttRawFrame(decoded: StreamFrame): void {
    if (decoded.flags !== RTT_RAW_UTF8_LINES) {
      throw new RangeError('RTT_RAW payload must use UTF-8 line records')
    }
    this.requireNextSequence(decoded.sequence, 'RTT_RAW')
    const bytes = new Uint8Array(decoded.payload)
    const view = new DataView(decoded.payload)
    const decoder = new TextDecoder('utf-8', { fatal: true })
    const lines: Array<{
      timestampNs: bigint; level: 'raw' | 'data' | 'warning' | 'error'; text: string
    }> = []
    let offset = 0
    for (let index = 0; index < decoded.itemCount; index++) {
      if (bytes.byteLength - offset < RTT_LINE_HEADER_SIZE) {
        throw new RangeError('truncated RTT line metadata')
      }
      const timestampNs = view.getBigUint64(offset, true)
      const level = RTT_LEVEL_NAMES[view.getUint8(offset + 8)]
      const length = view.getUint32(offset + 9, true)
      offset += RTT_LINE_HEADER_SIZE
      if (!level || length > bytes.byteLength - offset) {
        throw new RangeError('invalid RTT line metadata')
      }
      const text = decoder.decode(bytes.subarray(offset, offset + length))
      offset += length
      lines.push({ timestampNs, level, text })
    }
    if (offset !== bytes.byteLength) throw new RangeError('RTT line payload has trailing bytes')
    this.commitSequence(decoded.sequence)
    this.post({ type: 'rtt-lines', sequence: decoded.sequence, lines })
  }

  private acceptSuperWatchFrame(decoded: StreamFrame): void {
    this.requireNextSequence(decoded.sequence, 'SuperWatch')
    if (decoded.flags === SUPERWATCH_METADATA_JSON) {
      if (decoded.itemCount !== 0) throw new RangeError('SuperWatch metadata item count must be zero')
      const document = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(decoded.payload)) as {
        version?: unknown; channels?: unknown
      }
      if (!Number.isSafeInteger(document.version) || (document.version as number) <= this.superwatchMetadataVersion
        || !Array.isArray(document.channels) || document.channels.length > MAX_WAVEFORM_CHANNELS) {
        throw new RangeError('invalid or stale SuperWatch metadata')
      }
      const names = new Set<string>()
      const channels = document.channels.map(channel => {
        if (!channel || typeof channel !== 'object' || Array.isArray(channel)) {
          throw new TypeError('SuperWatch channel metadata must be objects')
        }
        const clone = { ...(channel as Record<string, unknown>) }
        if (typeof clone.name !== 'string' || !clone.name.trim() || names.has(clone.name)) {
          throw new RangeError('SuperWatch channel names must be unique non-empty strings')
        }
        names.add(clone.name)
        return clone as Record<string, unknown> & { name: string }
      })
      const version = document.version as number
      const currentRing = this.ring as TypedRingBuffer
      const nextCount = Math.max(1, channels.length)
      const nextRing = new TypedRingBuffer(currentRing.capacity, nextCount)
      this.ring = nextRing
      this.superwatchMetadataVersion = version
      this.lastNumericTimestampMs = null
      this.lastNumericSpacingMs = null
      this.commitSequence(decoded.sequence)
      if (nextCount !== currentRing.channelCount) this.post({ type: 'channels', channelCount: nextCount })
      this.post({ type: 'superwatch-metadata', version, channels })
      return
    }
    if (decoded.flags !== SUPERWATCH_SAMPLE_MAJOR_FLOAT32 || this.superwatchMetadataVersion <= 0) {
      throw new RangeError('SuperWatch samples require current metadata and sample-major Float32')
    }
    const ring = this.ring as TypedRingBuffer
    const expectedBytes = decoded.itemCount * ring.channelCount * Float32Array.BYTES_PER_ELEMENT
    if (decoded.itemCount <= 0 || decoded.payload.byteLength !== expectedBytes) {
      throw new RangeError('SuperWatch payload does not match metadata channel alignment')
    }
    const values = new Float32Array(decoded.payload)
    for (let index = 0; index < values.length; index++) {
      if (!Number.isFinite(values[index])) throw new RangeError('SuperWatch samples must be finite')
    }
    const timestampMs = Number(decoded.timestampNs) / 1_000_000
    if (!Number.isFinite(timestampMs)) throw new RangeError('SuperWatch timestamp is outside numeric range')
    const timing = this.buildMonotonicTimes(timestampMs, decoded.itemCount)
    ring.appendBatch(timing.times, values)
    this.lastNumericTimestampMs = timing.lastTimestamp
    this.lastNumericSpacingMs = timing.spacing
    this.commitSequence(decoded.sequence)
    const output: Extract<WorkerOutput, { type: 'waveform-batch' }> = {
      type: 'waveform-batch', sequence: decoded.sequence,
      timestampNs: decoded.timestampNs, itemCount: decoded.itemCount,
      channelCount: ring.channelCount, layout: 'sample-major-float32',
      values: decoded.payload, times: timing.times.buffer as ArrayBuffer,
    }
    this.post(output, [output.values, output.times])
  }

  private acceptWaveformFrame(decoded: StreamFrame): void {
    const currentRing = this.ring as TypedRingBuffer
    if (decoded.flags !== 0 && decoded.flags !== WAVEFORM_SAMPLE_MAJOR_FLOAT32) {
      throw new RangeError('VOFA waveform payload must be sample-major Float32')
    }
    if (decoded.sequence <= 0n || (
      this.lastDataSequence !== null && decoded.sequence <= this.lastDataSequence
    )) {
      throw new RangeError('VOFA sequence must increase strictly')
    }

    let channelCount = currentRing.channelCount
    if (decoded.itemCount > 0) {
      const sampleBytes = decoded.itemCount * Float32Array.BYTES_PER_ELEMENT
      if (decoded.payload.byteLength % sampleBytes !== 0) {
        throw new RangeError('VOFA payload is not aligned to complete Float32 samples')
      }
      channelCount = decoded.payload.byteLength / sampleBytes
      if (
        !Number.isSafeInteger(channelCount)
        || channelCount <= 0
        || channelCount > MAX_WAVEFORM_CHANNELS
      ) {
        throw new RangeError('VOFA payload channel count is outside the supported range')
      }
    } else if (decoded.payload.byteLength !== 0) {
      throw new RangeError('empty VOFA batches must not contain payload bytes')
    }
    const expectedBytes = decoded.itemCount * channelCount * Float32Array.BYTES_PER_ELEMENT
    if (decoded.payload.byteLength !== expectedBytes) {
      throw new RangeError('VOFA payload length does not match its sample and channel counts')
    }
    const values = new Float32Array(decoded.payload)
    for (let index = 0; index < values.length; index += 1) {
      if (!Number.isFinite(values[index])) {
        throw new RangeError('VOFA payload values must all be finite')
      }
    }
    const batchMilliseconds = Number(decoded.timestampNs) / 1_000_000
    if (!Number.isFinite(batchMilliseconds)) {
      throw new RangeError('VOFA batch timestamp is outside the numeric range')
    }
    const timing = this.buildMonotonicTimes(batchMilliseconds, decoded.itemCount)
    const nextRing = channelCount === currentRing.channelCount
      ? currentRing
      : new TypedRingBuffer(currentRing.capacity, channelCount)

    // Commit only after the entire frame, its dynamic configuration, values,
    // sequence, and timestamps have validated successfully.
    nextRing.appendBatch(timing.times, values)
    const channelChanged = nextRing !== currentRing
    if (channelChanged) {
      this.ring = nextRing
      this.post({ type: 'channels', channelCount })
    }
    if (this.lastDataSequence !== null && decoded.sequence > this.lastDataSequence + 1n) {
      this.transportDroppedBatches += Number(decoded.sequence - this.lastDataSequence - 1n)
    }
    this.lastDataSequence = decoded.sequence
    this.lastNumericTimestampMs = timing.lastTimestamp
    this.lastNumericSpacingMs = timing.spacing
    const output: Extract<WorkerOutput, { type: 'waveform-batch' }> = {
      type: 'waveform-batch',
      sequence: decoded.sequence,
      timestampNs: decoded.timestampNs,
      itemCount: decoded.itemCount,
      channelCount,
      layout: 'sample-major-float32',
      values: decoded.payload,
      times: timing.times.buffer as ArrayBuffer,
    }
    this.post(output, [output.values, output.times])
  }

  private buildMonotonicTimes(
    batchMilliseconds: number,
    itemCount: number,
  ): { times: Float64Array; lastTimestamp: number | null; spacing: number | null } {
    const times = new Float64Array(itemCount)
    if (itemCount === 0) {
      return {
        times,
        lastTimestamp: this.lastNumericTimestampMs,
        spacing: this.lastNumericSpacingMs,
      }
    }
    const previous = this.lastNumericTimestampMs
    const ulpStep = Math.max(
      0.000001,
      Math.abs(previous ?? batchMilliseconds) * Number.EPSILON * 4,
    )
    let spacing = ulpStep
    let first = batchMilliseconds - spacing * (itemCount - 1)
    if (previous !== null) {
      const observed = (batchMilliseconds - previous) / itemCount
      if (observed > 0) {
        const pauseSafeMaximum = this.lastNumericSpacingMs === null
          ? observed
          : Math.max(ulpStep, this.lastNumericSpacingMs * 4)
        spacing = Math.max(ulpStep, Math.min(observed, pauseSafeMaximum))
        first = batchMilliseconds - spacing * (itemCount - 1)
        if (first <= previous) first = previous + spacing
      } else {
        spacing = Math.max(ulpStep, this.lastNumericSpacingMs ?? ulpStep)
        first = previous + spacing
      }
    }
    for (let index = 0; index < itemCount; index += 1) {
      const candidate = first + spacing * index
      times[index] = index === 0 || candidate > times[index - 1]
        ? candidate
        : times[index - 1] + ulpStep
    }
    return { times, lastTimestamp: times[itemCount - 1], spacing }
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
      if (![timeUs, deltaUs, aux0, aux1].every(Number.isFinite)) {
        throw new RangeError('SystemView numeric fields must be finite')
      }
      const event: SystemViewEvent = { kind }
      if (flags & SYSTEMVIEW_HAS_TICKS) {
        event.t_ticks = ticks
        event.t_ticks_exact = ticks.toString()
      }
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
    if (decodedEvents.length && this.tickOrigin === null) {
      this.tickOrigin = decodedEvents[0].ticks
    }
    for (const decoded of decodedEvents) {
      this.ingestSystemViewEvent(decoded.event, decoded.ticks)
    }
  }

  private ingestSystemViewEvent(event: SystemViewEvent, ticks: bigint): void {
    if (ticks > this.latestSystemViewTick) this.latestSystemViewTick = ticks
    if (event.kind === 'task_start_exec' && event.task_id !== undefined) {
      this.suspendedTask = null
      this.isrDepth = 0
      this.closeCurrentSystemViewInterval(ticks)
      this.currentTask = { taskId: event.task_id, tick: ticks }
    } else if (
      (event.kind === 'task_stop_exec' || event.kind === 'task_stop_ready')
      && event.task_id === this.currentTask?.taskId
    ) {
      this.closeCurrentSystemViewInterval(ticks)
      if (this.suspendedTask?.taskId === event.task_id) this.suspendedTask = null
    } else if (event.kind === 'isr_enter') {
      if (this.isrDepth === 0 && this.currentTask) {
        this.suspendedTask = { taskId: this.currentTask.taskId }
        this.closeCurrentSystemViewInterval(ticks)
      }
      this.isrDepth += 1
    } else if (event.kind === 'isr_exit') {
      if (this.isrDepth > 0) this.isrDepth -= 1
      if (this.isrDepth === 0 && this.suspendedTask) {
        this.currentTask = { taskId: this.suspendedTask.taskId, tick: ticks }
        this.suspendedTask = null
      }
    } else if (event.kind === 'isr_to_scheduler' || event.kind === 'overflow') {
      this.abandonSystemViewContext()
    } else if (event.kind === 'idle') {
      this.closeCurrentSystemViewInterval(ticks)
      this.suspendedTask = null
      this.isrDepth = 0
    }
    this.systemViewEvents?.append(event, ticks)
  }

  private closeCurrentSystemViewInterval(endTick: bigint): void {
    const current = this.currentTask
    if (current && endTick > current.tick) {
      this.systemViewIntervals?.append(current.taskId, current.tick, endTick)
    }
    this.currentTask = null
  }

  private abandonSystemViewContext(): void {
    this.currentTask = null
    this.suspendedTask = null
    this.isrDepth = 0
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
    const selection = this.ring.selectMinMaxEnvelope(
      message.start, message.end, message.pixelWidth,
    )
    const selectedLogical = selection.logicalIndices.subarray(0, selection.pointCount)
    const timeIndexByLogical = this.timeIndexScratch as Int32Array
    let firstLogical = this.ring.length
    let lastLogical = -1
    for (let point = 0; point < selectedLogical.length; point += 1) {
      const logical = selectedLogical[point]
      timeIndexByLogical[logical] = -1
      firstLogical = Math.min(firstLogical, logical)
      lastLogical = Math.max(lastLogical, logical)
    }
    let uniqueCount = 0
    for (let logical = firstLogical; logical <= lastLogical; logical += 1) {
      if (timeIndexByLogical[logical] === -1) {
        timeIndexByLogical[logical] = ++uniqueCount
      }
    }
    const times = new Float64Array(uniqueCount)
    for (let logical = firstLogical; logical <= lastLogical; logical += 1) {
      const oneBasedTimeIndex = timeIndexByLogical[logical]
      if (oneBasedTimeIndex > 0) {
        times[oneBasedTimeIndex - 1] = this.ring.timeAt(logical)
      }
    }
    const timeIndices = new Uint32Array(selection.pointCount)
    const values = new Float32Array(selection.pointCount)
    for (let channel = 0; channel < this.ring.channelCount; channel += 1) {
      const first = selection.channelOffsets[channel]
      const afterLast = selection.channelOffsets[channel + 1]
      for (let point = first; point < afterLast; point += 1) {
        const logical = selectedLogical[point]
        timeIndices[point] = timeIndexByLogical[logical] - 1
        values[point] = this.ring.valueAt(logical, channel)
      }
    }
    for (let point = 0; point < selectedLogical.length; point += 1) {
      timeIndexByLogical[selectedLogical[point]] = 0
    }
    const output: Extract<WorkerOutput, { type: 'render-envelope' }> = {
      type: 'render-envelope',
      mode: 'min-max-v1',
      timestampKind: 'sample-milliseconds',
      requestId: message.requestId,
      pixelWidth: message.pixelWidth,
      channelCount: this.ring.channelCount,
      pointCount: selection.pointCount,
      candidateSampleCount: selection.candidateSampleCount,
      channelOffsets: selection.channelOffsets.buffer as ArrayBuffer,
      times: times.buffer,
      timeIndices: timeIndices.buffer,
      values: values.buffer,
    }
    this.post(output, [
      output.channelOffsets, output.times, output.timeIndices, output.values,
    ])
  }

  private systemViewVisibleRange(message: Extract<WorkerInput, { type: 'visible-range' }>): void {
    const origin = this.tickOrigin ?? 0n
    const rangeStart = origin + BigInt(Math.floor(message.start))
    const rangeEnd = origin + BigInt(Math.floor(message.end))
    const intervalRing = this.systemViewIntervals as SystemViewIntervalRing
    const selection = intervalRing.selectEnvelope(rangeStart, rangeEnd, message.pixelWidth)
    const taskIds = new Uint32Array(selection.count)
    const starts = new Float64Array(selection.count)
    const ends = new Float64Array(selection.count)
    const startTicks = new BigUint64Array(selection.count)
    const endTicks = new BigUint64Array(selection.count)
    for (let outputIndex = 0; outputIndex < selection.count; outputIndex++) {
      const logical = selection.logicalIndices[outputIndex]
      const startTick = intervalRing.startTickAt(logical)
      const endTick = intervalRing.endTickAt(logical)
      taskIds[outputIndex] = intervalRing.taskIdAt(logical)
      starts[outputIndex] = safeTickDifference(startTick, origin)
      ends[outputIndex] = safeTickDifference(endTick, origin)
      startTicks[outputIndex] = startTick
      endTicks[outputIndex] = endTick
    }

    const eventRing = this.systemViewEvents as SystemViewEventRing<SystemViewEvent>
    const firstEvent = eventRing.lowerBound(rangeStart)
    const afterLastEvent = eventRing.upperBound(rangeEnd)
    const eventCount = afterLastEvent - firstEvent
    const outputFirst = Math.max(firstEvent, afterLastEvent - 120)
    const events: SystemViewEvent[] = []
    for (let logical = outputFirst; logical < afterLastEvent; logical++) {
      const tick = eventRing.tickAt(logical)
      events.push({
        ...eventRing.eventAt(logical),
        t_ticks: tick,
        t_ticks_exact: tick.toString(),
        t_relative: safeTickDifference(tick, origin),
      })
    }
    const output: Extract<WorkerOutput, { type: 'systemview-visible' }> = {
      type: 'systemview-visible',
      requestId: message.requestId,
      intervalCount: selection.count,
      candidateIntervalCount: selection.candidateCount,
      eventCount,
      latestTime: safeTickDifference(this.latestSystemViewTick, origin),
      tickOrigin: origin,
      taskIds: taskIds.buffer,
      starts: starts.buffer,
      ends: ends.buffer,
      startTicks: startTicks.buffer,
      endTicks: endTicks.buffer,
      events,
    }
    this.post(output, [
      output.taskIds, output.starts, output.ends, output.startTicks, output.endTicks,
    ])
  }

  private reset(): void {
    this.ring?.reset()
    this.systemViewMode = false
    this.systemViewEvents?.clear()
    this.systemViewIntervals?.clear()
    this.currentTask = null
    this.suspendedTask = null
    this.isrDepth = 0
    this.tickOrigin = null
    this.latestSystemViewTick = 0n
    this.lastNumericTimestampMs = null
    this.lastNumericSpacingMs = null
    this.superwatchMetadataVersion = 0
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
      bufferedSamples: this.systemViewMode ? (this.systemViewEvents?.length ?? 0) : (this.ring?.length ?? 0),
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
