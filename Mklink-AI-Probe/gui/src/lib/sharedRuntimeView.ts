import { API_BASE } from './runtimeEndpoint'

/** Presence only: closing a window never changes hardware ownership. */
export function startSharedRuntimeView(): () => void {
  const clientId = crypto.randomUUID()
  let stopped = false
  const send = (release = false) => fetch(`${API_BASE}/api/runtime/control/view`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId, release }), keepalive: release,
  }).catch(() => undefined)
  void send()
  const timer = setInterval(() => { if (!stopped) void send() }, 10000)
  const stop = () => {
    if (stopped) return
    stopped = true
    clearInterval(timer)
    window.removeEventListener('pagehide', stop)
    void send(true)
  }
  window.addEventListener('pagehide', stop)
  return stop
}
