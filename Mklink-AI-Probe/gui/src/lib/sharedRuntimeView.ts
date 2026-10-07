import { API_BASE, IS_REMOTE } from './runtimeEndpoint'

/** A transport-owned presence survives background timer throttling. */
export function startSharedRuntimeView(present?: (tab: string) => Promise<void>): () => void {
  let socket: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | undefined
  let stopped = false
  let suspended = false
  const resume = () => {
    if (stopped || suspended || socket !== null) return
    const url = new URL(IS_REMOTE ? `${API_BASE}/presence` : `${API_BASE}/api/runtime/control/view/${crypto.randomUUID()}`, window.location.href)
    if (!IS_REMOTE && present) url.searchParams.set('presentation', '1')
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    const current = new WebSocket(url.href)
    socket = current
    current.onmessage = async event => {
      if (socket !== current || stopped || suspended || IS_REMOTE || !present) return
      let message: any
      try { message = JSON.parse(event.data) } catch { return }
      if (!message || typeof message !== 'object' || message.type !== 'present' || typeof message.request_id !== 'string' ||
          !['superwatch', 'rtt', 'memory', 'symbols', 'hardfault', 'systemview'].includes(message.tab) ||
          typeof message.expires_at !== 'number' || message.expires_at * 1000 < Date.now()) return
      let ok = false
      try { await present(message.tab); ok = true } catch { /* Report failure without replay. */ }
      if (socket === current && !stopped && !suspended && current.readyState === WebSocket.OPEN) {
        current.send(JSON.stringify({ type: 'present_result', request_id: message.request_id, ok }))
      }
    }
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
