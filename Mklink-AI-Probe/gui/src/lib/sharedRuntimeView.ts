import { API_BASE } from './runtimeEndpoint'

/** Presence only: closing a window never changes hardware ownership. */
export function startSharedRuntimeView(): () => void {
  let clientId: string | null = null
  let timer: ReturnType<typeof setInterval> | undefined
  let stopped = false
  const send = (id: string, release = false) => fetch(`${API_BASE}/api/runtime/control/view`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: id, release }), keepalive: release,
  }).catch(() => undefined)
  const resume = () => {
    if (stopped || clientId !== null) return
    // A delayed release from before navigation must not remove the restored view.
    const id = crypto.randomUUID()
    clientId = id
    void send(id)
    timer = setInterval(() => { void send(id) }, 10000)
  }
  const suspend = () => {
    clearInterval(timer)
    timer = undefined
    if (clientId === null) return
    const id = clientId
    clientId = null
    void send(id, true)
  }
  const stop = () => {
    if (stopped) return
    stopped = true
    window.removeEventListener('pagehide', hide)
    window.removeEventListener('pageshow', show)
    suspend()
  }
  const hide = (event: PageTransitionEvent) => { event.persisted ? suspend() : stop() }
  const show = (event: PageTransitionEvent) => { if (event.persisted) resume() }
  window.addEventListener('pagehide', hide)
  window.addEventListener('pageshow', show)
  resume()
  return stop
}
