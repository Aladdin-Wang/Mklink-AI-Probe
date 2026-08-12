import { describe, expect, it } from 'vitest'
import { browserSessionSocketUrl, startBrowserSessionLease } from './browserSessionLease'

describe('browser session lease', () => {
  it('uses the serving backend and selects the matching WebSocket protocol', () => {
    expect(browserSessionSocketUrl(
      { protocol: 'http:', host: '127.0.0.1:8766' } as Location,
      'tab one',
    )).toBe('ws://127.0.0.1:8766/ws/browser-session?client_id=tab%20one')
    expect(browserSessionSocketUrl(
      { protocol: 'https:', host: 'probe.example' } as Location,
      'tab',
    )).toMatch(/^wss:/)
  })

  it('does nothing when browser ownership is disabled', () => {
    const stop = startBrowserSessionLease(false)
    expect(() => stop()).not.toThrow()
  })
})
