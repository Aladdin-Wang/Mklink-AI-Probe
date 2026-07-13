import { computed, onUnmounted, readonly, ref, shallowRef } from 'vue'
import { StreamClient } from '../lib/stream/streamClient'
import type { StreamClientOptions, StreamClientState } from '../lib/stream/streamClient'
import type { StreamTelemetry, WorkerOutput } from '../workers/streamDecoder.worker'

export type BinaryStreamName = 'systemview' | 'vofa' | 'rtt' | 'superwatch'

export interface BinaryStreamClient {
  start(): void
  stop(): void
  reset(): void
  requestVisibleRange(requestId: number, start: number, end: number, pixelWidth: number): void
  dispose(): void
}

export interface UseBinaryStreamOptions {
  readonly capacity: number
  readonly channelCount: number
  readonly token?: string
  readonly autoStart?: boolean
  readonly createClient?: (options: StreamClientOptions) => BinaryStreamClient
}

type RenderEnvelope = Extract<WorkerOutput, { type: 'render-envelope' }>
type SystemViewVisible = Extract<WorkerOutput, { type: 'systemview-visible' }>

const API_BASE = import.meta.env.VITE_MKLINK_API || ''

function streamUrl(stream: BinaryStreamName): string {
  if (API_BASE) {
    const base = new URL(API_BASE, window.location.href)
    base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:'
    base.pathname = `/ws/streams/${stream}`
    base.search = ''
    base.hash = ''
    return base.toString()
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/streams/${stream}`
}

export function useBinaryStream(
  stream: BinaryStreamName,
  options: UseBinaryStreamOptions,
) {
  const state = ref<StreamClientState>({ phase: 'stopped' })
  const telemetry = shallowRef<StreamTelemetry | null>(null)
  const channelCount = ref(options.channelCount)
  const envelope = shallowRef<RenderEnvelope | null>(null)
  const systemViewVisible = shallowRef<SystemViewVisible | null>(null)
  const error = ref<string | null>(null)

  function onState(next: StreamClientState): void {
    state.value = next
    if (next.error) error.value = next.error
  }

  function onWorkerMessage(message: WorkerOutput): void {
    switch (message.type) {
      case 'telemetry':
        telemetry.value = message
        break
      case 'channels':
        channelCount.value = message.channelCount
        break
      case 'render-envelope':
        envelope.value = message
        break
      case 'systemview-visible':
        systemViewVisible.value = message
        break
      case 'error':
        error.value = message.message
        break
    }
  }

  const createClient = options.createClient ?? (clientOptions => new StreamClient(clientOptions))
  const client = createClient({
    url: streamUrl(stream),
    token: options.token,
    capacity: options.capacity,
    channelCount: options.channelCount,
    onState,
    onWorkerMessage,
  })

  function start(): void {
    error.value = null
    client.start()
  }

  function stop(): void {
    client.stop()
  }

  function reset(): void {
    telemetry.value = null
    envelope.value = null
    systemViewVisible.value = null
    error.value = null
    client.reset()
  }

  function requestVisibleRange(
    requestId: number,
    start: number,
    end: number,
    pixelWidth: number,
  ): void {
    client.requestVisibleRange(requestId, start, end, pixelWidth)
  }

  if (options.autoStart) start()

  onUnmounted(() => client.dispose())

  return {
    state: readonly(state),
    connected: computed(() => state.value.phase === 'connected'),
    telemetry: readonly(telemetry),
    channelCount: readonly(channelCount),
    envelope: readonly(envelope),
    systemViewVisible: readonly(systemViewVisible),
    error: readonly(error),
    start,
    stop,
    reset,
    requestVisibleRange,
  }
}
