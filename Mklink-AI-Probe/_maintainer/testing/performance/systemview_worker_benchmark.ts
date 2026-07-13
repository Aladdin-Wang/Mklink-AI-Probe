import { performance } from 'node:perf_hooks'
import { StreamType } from '../../../gui/src/lib/stream/protocol'
import {
  StreamDecoder,
  type WorkerOutput,
} from '../../../gui/src/workers/streamDecoder.worker'

const RECORD_BYTES = 48
const FRAME_HEADER_BYTES = 36
const BATCH_EVENTS = 500

function payload(firstTick: bigint, eventCount: number): Uint8Array {
  const bytes = new Uint8Array(eventCount * RECORD_BYTES)
  const view = new DataView(bytes.buffer)
  for (let index = 0; index < eventCount; index++) {
    const offset = index * RECORD_BYTES
    view.setUint8(offset, index % 2 === 0 ? 4 : 5)
    view.setUint8(offset + 1, 0x01)
    view.setUint32(offset + 4, 1 + ((index >>> 1) % 32), true)
    view.setBigUint64(offset + 8, firstTick + BigInt(index), true)
  }
  return bytes
}

function frame(sequence: bigint, eventCount: number, body: Uint8Array): ArrayBuffer {
  const buffer = new ArrayBuffer(FRAME_HEADER_BYTES + body.byteLength)
  const bytes = new Uint8Array(buffer)
  const view = new DataView(buffer)
  bytes.set([0x4d, 0x4b, 0x53, 0x54])
  view.setUint8(4, 1)
  view.setUint8(5, StreamType.SYSTEMVIEW)
  view.setUint8(7, FRAME_HEADER_BYTES)
  view.setUint32(8, StreamType.SYSTEMVIEW, true)
  view.setBigUint64(12, sequence, true)
  view.setBigUint64(20, BigInt(Math.trunc(performance.now() * 1_000_000)), true)
  view.setUint32(28, eventCount, true)
  view.setUint32(32, body.byteLength, true)
  bytes.set(body, FRAME_HEADER_BYTES)
  return buffer
}

async function main(): Promise<void> {
  const duration = Number(process.argv[2] || 60)
  const rate = Number(process.argv[3] || 50_000)
  const capacity = Number(process.argv[4] || 100_000)
  const pixelWidth = Number(process.argv[5] || 800)
  if (![duration, rate, capacity, pixelWidth].every(Number.isFinite)) {
    throw new TypeError('duration, rate, capacity and pixel width must be finite')
  }

  let errors = 0
  let acceptedFrames = 0
  let bufferedEvents = 0
  let visibleRequests = 0
  let maxVisibleIntervals = 0
  let maxVisibleCandidates = 0
  const decoder = new StreamDecoder((message: WorkerOutput) => {
    if (message.type === 'error') errors += 1
    if (message.type === 'telemetry') {
      acceptedFrames = message.acceptedFrames
      bufferedEvents = message.bufferedSamples
    }
    if (message.type === 'systemview-visible') {
      visibleRequests += 1
      maxVisibleIntervals = Math.max(maxVisibleIntervals, message.intervalCount)
      maxVisibleCandidates = Math.max(maxVisibleCandidates, message.candidateIntervalCount)
    }
  })
  decoder.handle({ type: 'configure', capacity, channelCount: 1 })

  const origin = 9_007_199_254_740_993n
  let tick = origin
  let sequence = 1n
  let producedEvents = 0
  const targetEvents = Math.ceil(duration * rate)
  const batchPeriodMs = BATCH_EVENTS / rate * 1_000
  const renderPeriodMs = 1_000 / 30
  const started = performance.now()
  let nextBatchAt = started
  let nextVisibleAt = started
  const baselineHeap = process.memoryUsage().heapUsed
  let peakHeap = baselineHeap

  while (producedEvents < targetEvents) {
    const now = performance.now()
    while (producedEvents < targetEvents && now >= nextBatchAt) {
      const count = Math.min(BATCH_EVENTS, targetEvents - producedEvents)
      decoder.handle({
        type: 'frame',
        buffer: frame(sequence, count, payload(tick, count)),
        connectionGeneration: 1,
        frameTicket: Number(sequence),
      })
      sequence += 1n
      tick += BigInt(count)
      producedEvents += count
      nextBatchAt = started + producedEvents / rate * 1_000
    }
    if (now >= nextVisibleAt && producedEvents) {
      const latest = Number(tick - origin - 1n)
      decoder.handle({
        type: 'visible-range', requestId: visibleRequests + 1,
        start: Math.max(0, latest - rate), end: latest, pixelWidth,
      })
      nextVisibleAt += renderPeriodMs
    }
    peakHeap = Math.max(peakHeap, process.memoryUsage().heapUsed)
    const waitMs = Math.max(0, Math.min(5, nextBatchAt - performance.now()))
    await new Promise(resolve => setTimeout(resolve, waitMs))
  }

  const elapsed = (performance.now() - started) / 1_000
  const endHeap = process.memoryUsage().heapUsed
  console.log(JSON.stringify({
    duration_requested: duration,
    elapsed,
    rate_requested: rate,
    measured_events_per_second: producedEvents / elapsed,
    produced_events: producedEvents,
    accepted_frames: acceptedFrames,
    buffered_events: bufferedEvents,
    visible_requests: visibleRequests,
    max_visible_candidates: maxVisibleCandidates,
    max_visible_intervals: maxVisibleIntervals,
    interval_output_limit: pixelWidth * 2,
    errors,
    baseline_heap_bytes: baselineHeap,
    peak_heap_bytes: peakHeap,
    end_heap_bytes: endHeap,
  }, null, 0))
}

main().catch(error => {
  console.error(JSON.stringify({ error: error instanceof Error ? error.message : String(error) }))
  process.exitCode = 1
})
