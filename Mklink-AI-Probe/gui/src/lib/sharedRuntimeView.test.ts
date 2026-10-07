import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startSharedRuntimeView } from './sharedRuntimeView'

class Socket {
  static all: Socket[] = []
  static OPEN = 1
  readyState = 1
  send = vi.fn()
  onmessage: ((event: { data: string }) => Promise<void>) | null = null
  onclose: (() => void) | null = null
  close = vi.fn(() => this.onclose?.())
  constructor(public url: string) { Socket.all.push(this) }
}
const transition = (name: string, persisted: boolean) => {
  const event = new Event(name)
  Object.defineProperty(event, 'persisted', { value: persisted })
  window.dispatchEvent(event)
}
describe('shared window transport presence', () => {
  let stop: () => void
  beforeEach(() => {
    vi.useFakeTimers(); Socket.all = []; vi.stubGlobal('WebSocket', Socket)
    stop = startSharedRuntimeView()
  })
  afterEach(() => { stop(); vi.useRealTimers(); vi.unstubAllGlobals() })
  it('presents only valid unexpired requests and acknowledges completion', async () => {
    stop()
    const present = vi.fn().mockResolvedValue(undefined)
    stop = startSharedRuntimeView(present)
    const socket = Socket.all.at(-1)!
    expect(socket.url).toContain('presentation=1')
    const message = { type: 'present', request_id: 'one', tab: 'superwatch', expires_at: Date.now() / 1000 + 3 }
    await socket.onmessage!({ data: JSON.stringify(message) })
    expect(present).toHaveBeenCalledWith('superwatch')
    expect(JSON.parse(socket.send.mock.calls[0]![0])).toEqual({ type: 'present_result', request_id: 'one', ok: true })
    for (const invalid of [null, { ...message, tab: 'https://bad' }, { ...message, expires_at: 0 }]) {
      await socket.onmessage!({ data: JSON.stringify(invalid) })
    }
    expect(present).toHaveBeenCalledTimes(1)
    stop()
    await socket.onmessage!({ data: JSON.stringify(message) })
    expect(present).toHaveBeenCalledTimes(1)
  })
  it('keeps a background window alive without a JavaScript heartbeat', () => {
    vi.advanceTimersByTime(120000)
    expect(Socket.all).toHaveLength(1)
    expect(Socket.all[0]!.close).not.toHaveBeenCalled()
  })
  it('restores bfcache with a new identity and ignores stale close', () => {
    const first = Socket.all[0]!
    transition('pagehide', true); vi.advanceTimersByTime(60000)
    expect(first.close).toHaveBeenCalledOnce()
    expect(Socket.all).toHaveLength(1)
    transition('pageshow', true); transition('pageshow', true)
    expect(Socket.all).toHaveLength(2)
    expect(Socket.all[1]!.url).not.toBe(first.url)
    first.onclose?.(); vi.advanceTimersByTime(1000)
    expect(Socket.all).toHaveLength(2)
  })
  it('reconnects only presence after a transport loss', () => {
    Socket.all[0]!.onclose?.(); vi.advanceTimersByTime(1000)
    expect(Socket.all).toHaveLength(2)
    expect(Socket.all[1]!.url).toContain('/api/runtime/control/view/')
  })
  it('keeps windows independent and stops permanently on normal pagehide', () => {
    const otherStop = startSharedRuntimeView()
    stop(); expect(Socket.all[1]!.close).not.toHaveBeenCalled()
    transition('pagehide', false); transition('pageshow', true)
    vi.advanceTimersByTime(60000)
    expect(Socket.all).toHaveLength(2)
    expect(Socket.all[1]!.close).toHaveBeenCalledOnce()
    otherStop()
  })
})
