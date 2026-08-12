import { IS_TAURI } from './runtimeEndpoint'

const RETRY_DELAY_MS = 1000

export function browserSessionSocketUrl(
  location: Pick<Location, 'host' | 'protocol'> = window.location,
  clientId: string,
): string {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${location.host}/ws/browser-session?client_id=${encodeURIComponent(clientId)}`
}

function createClientId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `mklink-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function startBrowserSessionLease(enabled = !IS_TAURI): () => void {
  if (!enabled) return () => undefined

  const clientId = createClientId()
  let socket: WebSocket | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let stopped = false

  const connect = () => {
    if (stopped) return
    socket = new WebSocket(browserSessionSocketUrl(window.location, clientId))
    socket.addEventListener('close', event => {
      socket = null
      if (stopped || event.code === 1008) return
      retryTimer = setTimeout(connect, RETRY_DELAY_MS)
    })
  }

  const stop = () => {
    if (stopped) return
    stopped = true
    window.removeEventListener('pagehide', stop)
    if (retryTimer !== null) clearTimeout(retryTimer)
    socket?.close(1000, 'browser page closed')
    socket = null
    navigator.sendBeacon?.(
      '/api/browser-session/release',
      new Blob([JSON.stringify({ client_id: clientId })], { type: 'application/json' }),
    )
  }

  window.addEventListener('pagehide', stop)
  connect()
  return stop
}
