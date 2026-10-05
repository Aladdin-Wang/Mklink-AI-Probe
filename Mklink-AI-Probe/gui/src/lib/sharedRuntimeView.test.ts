import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startSharedRuntimeView } from './sharedRuntimeView'

class Socket {
  static all: Socket[] = []
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
