import { ref, shallowRef, readonly, onUnmounted } from 'vue'
import type { DataPoint } from '../types/mklink'
import { API_BASE } from '../lib/runtimeEndpoint'

interface EventSourceOptions {
  passthroughEvents?: string[]
  maxPoints?: number
}

type StreamDataPoint = DataPoint & { _streamSeq?: number }

export function useEventSource(url: string, options: EventSourceOptions = {}) {
  const data = shallowRef<StreamDataPoint[]>([])
  const connected = ref(false)
  const error = ref<string | null>(null)

  let es: EventSource | null = null
  let streamSeq = 0
  const maxPoints = options.maxPoints ?? 500
  const passthroughEvents = new Set(options.passthroughEvents ?? [])

  function withSeq(point: DataPoint): StreamDataPoint {
    return { ...point, _streamSeq: ++streamSeq }
  }

  function pushDataPoint(point: DataPoint) {
    const next = [...data.value, withSeq(point)]
    data.value = next.length > maxPoints ? next.slice(-maxPoints) : next
  }

  function connect() {
    disconnect()
    streamSeq = 0
    data.value = []
    error.value = null

    es = new EventSource(`${API_BASE}${url}`)

    es.onopen = () => {
      connected.value = true
      error.value = null
    }

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data)
        if (
          parsed.event === 'data' ||
          parsed.event === 'raw' ||
          passthroughEvents.has(parsed.event)
        ) {
          pushDataPoint(parsed)
        } else if (parsed.event === 'history') {
          // Initial history replay
          const points = parsed.points || []
          data.value = points.slice(-maxPoints).map((point: DataPoint) => withSeq(point))
        } else if (parsed.event === 'error') {
          error.value = parsed.message
        } else if (parsed.event === 'stopped') {
          connected.value = false
        }
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      connected.value = false
      if (es?.readyState === EventSource.CLOSED) {
        error.value = 'Connection closed'
      }
    }
  }

  function disconnect() {
    if (es) {
      es.close()
      es = null
    }
    connected.value = false
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    data: readonly(data),
    connected: readonly(connected),
    error: readonly(error),
    connect,
    disconnect,
  }
}
