import { API_BASE, IS_REMOTE } from './runtimeEndpoint'

/** A transport-owned presence survives background timer throttling. */
export function startSharedRuntimeView(): () => void {
  let socket: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | undefined
  let stopped = false
  let suspended = false
  const resume = () => {
    if (stopped || suspended || socket !== null) return
    const url = new URL(IS_REMOTE ? `${API_BASE}/presence` : `${API_BASE}/api/runtime/control/view/${crypto.randomUUID()}`, window.location.href)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    const current = new WebSocket(url.href)
    socket = current
    current.onclose = () => {
      if (socket !== current) return
      socket = null
      // Only presence is retried. Remote sessions require explicit reconnection.
      if (!stopped && !suspended && !IS_REMOTE) retry = setTimeout(resume, 1000)
    }
  }
  const suspend = () => {
    clearTimeout(retry)
    const current = socket
    socket = null
    current?.close()
  }
  const stop = () => {
    if (stopped) return
    stopped = true
    window.removeEventListener('pagehide', hide)
    window.removeEventListener('pageshow', show)
    suspend()
  }
  const hide = (event: PageTransitionEvent) => {
    if (event.persisted) { suspended = true; suspend() } else stop()
  }
  const show = (event: PageTransitionEvent) => {
    if (event.persisted) { suspended = false; resume() }
  }
  window.addEventListener('pagehide', hide)
  window.addEventListener('pageshow', show)
  resume()
  return stop
}
