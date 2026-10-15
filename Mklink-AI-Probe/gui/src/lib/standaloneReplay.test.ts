import fs from 'node:fs'
import { expect, it, vi } from 'vitest'

it('keeps standalone CLI playback in its original canvas and isolates the target controls', () => {
  vi.useFakeTimers()
  vi.stubGlobal('CONFIG', { mode: 'SuperWatch', lang: 'en', maxPoints: 100 })
  vi.stubGlobal('t', (key: string) => key)
  vi.stubGlobal('applyI18n', () => {})
  vi.stubGlobal('EventSource', class { addEventListener() {} close() {} })
  const fetch = vi.fn(async () => ({ json: async () => ({ state: 'stopped' }) }))
  vi.stubGlobal('fetch', fetch)
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(new Proxy({}, { get: (_, key) =>
    key === 'measureText' ? () => ({ width: 10 }) : key === 'createLinearGradient' ? () => ({ addColorStop() {} }) : () => {},
  }) as any)
  document.body.innerHTML = fs.readFileSync('../mklink/_rtt_viewer_template.html', 'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '').replace(/<link\b[^>]*>/g, '')
  try {
    new Function(fs.readFileSync('../mklink/static/rtt_viewer.js', 'utf8') + '\nwindow.__standaloneProbe = {processPoint, applyChannelMetadata, fields: () => FIELDS};').call(window)
    const api = (window as any).__waveformViewers.SuperWatch
    const probe = (window as any).__standaloneProbe
    const canvas = document.querySelector('#chart')
    const control = vi.fn()
    api.beginReplay({ duration: 10, channels: [{ name: 'log' }] }, control)
    api.setReplayPosition(5, false, true)
    api.renderReplayView({ channels: [{ name: 'log', points: [[0, 1], [5, 2]] }] })
    probe.processPoint({ _t: 100, live: 99 })
    probe.applyChannelMetadata({ nextLive: { type: 'float' } })
    expect(Object.keys(probe.fields())).toEqual(['log'])
    expect(probe.fields().log.ringBuf.count).toBe(2)
    const calls = fetch.mock.calls.length
    ;(document.querySelector('#btn-start') as HTMLButtonElement).click()
    ;(document.querySelector('#btn-pause') as HTMLButtonElement).click()
    ;(document.querySelector('#btn-stop') as HTMLButtonElement).click()
    expect(control.mock.calls.map(call => call[0])).toEqual(['play', 'toggle', 'stop'])
    expect(fetch).toHaveBeenCalledTimes(calls)
    expect(document.querySelector('#chart')).toBe(canvas)
    api.endReplay()
    expect(Object.keys(probe.fields())).toContain('nextLive')
  } finally {
    vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); document.body.innerHTML = ''
  }
})
