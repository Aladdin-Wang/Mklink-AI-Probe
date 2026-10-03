import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startSharedRuntimeView } from './sharedRuntimeView'

describe('shared window presence', () => {
  let stop: () => void
  const fetchMock = vi.fn()
  const messages = () => fetchMock.mock.calls.map(call => JSON.parse(call[1].body))
  const transition = (name: string, persisted: boolean) => {
    const event = new Event(name)
    Object.defineProperty(event, 'persisted', { value: persisted })
    window.dispatchEvent(event)
  }
  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock.mockReset().mockResolvedValue(new Response())
    vi.stubGlobal('fetch', fetchMock)
    stop = startSharedRuntimeView()
  })
  afterEach(() => {
    stop()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('restores presence after bfcache without reviving the released identity', () => {
    const first = messages()[0].client_id
    transition('pagehide', true)
    vi.advanceTimersByTime(60000)
    expect(messages()).toHaveLength(2)
    expect(messages()[1]).toEqual({ client_id: first, release: true })
    transition('pageshow', true)
    const restored = messages()[2]
    expect(restored).toEqual({ client_id: expect.any(String), release: false })
    expect(restored.client_id).not.toBe(first)
    transition('pageshow', true) // Duplicate event cannot create another timer.
    vi.advanceTimersByTime(10000)
    expect(messages()).toHaveLength(4)
    expect(messages()[3]).toEqual(restored)
    expect(fetchMock.mock.calls.every(call => call[0] === '/api/runtime/control/view')).toBe(true)
  })

  it('keeps multiple windows independent and disposes permanently', () => {
    const otherStop = startSharedRuntimeView()
    const [first, second] = messages()
    expect(first.client_id).not.toBe(second.client_id)
    stop()
    transition('pageshow', true)
    vi.advanceTimersByTime(10000)
    expect(messages().at(-1)).toEqual(second)
    otherStop()
    const count = messages().length
    transition('pagehide', true)
    transition('pageshow', true)
    vi.advanceTimersByTime(60000)
    expect(messages()).toHaveLength(count)
  })

  it('does not resume after a non-cached navigation or duplicate release', () => {
    transition('pagehide', false)
    transition('pageshow', true)
    stop()
    vi.advanceTimersByTime(60000)
    expect(messages()).toHaveLength(2)
    expect(messages()[1].release).toBe(true)
  })
})
