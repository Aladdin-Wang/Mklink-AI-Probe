import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mountReplayButton } from '../../../mklink/static/superwatch_replay.js'

class FakeWorker {
  static instances: FakeWorker[] = []
  onmessage: ((event: { data: any }) => void) | null = null
  onerror: (() => void) | null = null
  postMessage = vi.fn()
  terminate = vi.fn()
  constructor() { FakeWorker.instances.push(this) }
  send(data: any) { this.onmessage?.({ data }) }
}
let dispose: () => void, control: (action: string) => void, viewer: any
function element<T extends HTMLElement>(selector: string) { return document.querySelector(selector) as T }
function upload() {
  const input = element<HTMLInputElement>('[data-testid=replay-file]')
  Object.defineProperty(input, 'files', { value: [new File(['timestamp,a\n0,1'], 'test.csv')], configurable: true })
  input.dispatchEvent(new Event('change'))
  return FakeWorker.instances.at(-1)!
}
function respond(worker: FakeWorker) {
  const request = worker.postMessage.mock.calls.at(-1)![0]
  worker.send({ type: 'view', id: request.id, position: request.position, width: 800, channels: [{ name: 'a', points: [[0, 1]], latest: 1 }] })
}
function loaded(worker: FakeWorker, duration = 60) {
  worker.send({ type: 'loaded', rows: 100, duration, channels: [{ name: 'a', count: 100 }] }); respond(worker)
}
describe('inline replay controls and lifetime', () => {
  beforeEach(() => {
    FakeWorker.instances = []
    vi.stubGlobal('Worker', FakeWorker)
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
    viewer = {
      beginReplay: vi.fn((_meta, callback) => { control = callback; return true }),
      endReplay: vi.fn(), setReplayPosition: vi.fn(), renderReplayView: vi.fn(),
      getBinaryVisibleRange: vi.fn(() => ({ start: 0, end: 10000, pixelWidth: 800 })),
    }
    ;(window as any).__waveformViewers = { SuperWatch: viewer }
    document.body.innerHTML = '<div class="waveform-viewer"><div class="watch-toolbar-row"><div class="host"></div></div><canvas id="chart"></canvas></div>'
    dispose = mountReplayButton(element('.host'), { language: 'en' })
  })
  afterEach(() => { dispose(); vi.restoreAllMocks(); vi.unstubAllGlobals(); document.body.innerHTML = '' })
  it('uses the original chart without a dialog or another canvas and makes no device requests', () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    const worker = upload(); loaded(worker)
    expect(document.querySelector('dialog')).toBeNull()
    expect(document.querySelectorAll('canvas')).toHaveLength(1)
    expect(viewer.renderReplayView).toHaveBeenCalledOnce()
    expect(element('.sw-replay-inline').previousElementSibling?.className).toBe('watch-toolbar-row')
    expect(fetch).not.toHaveBeenCalled()
  })
  it('routes original Start/Pause/Stop controls to playback and preserves inspection viewport', () => {
    const worker = upload(); loaded(worker)
    control('play'); expect(element('.sw-replay-inline').dataset.playbackState).toBe('playing')
    control('inspect'); expect(element('.sw-replay-inline').dataset.playbackState).toBe('paused')
    expect(viewer.setReplayPosition).toHaveBeenLastCalledWith(0, false, false)
    control('toggle'); expect(element('.sw-replay-inline').dataset.playbackState).toBe('playing')
    control('stop'); expect(element('.sw-replay-inline').dataset.playbackState).toBe('paused')
  })
  it('discards an obsolete seek frame and then renders the requested history range', () => {
    const worker = upload(); loaded(worker)
    const slider = element<HTMLInputElement>('[data-testid=replay-seek]')
    slider.value = '40'; slider.dispatchEvent(new Event('input'))
    slider.value = '2.5'; slider.dispatchEvent(new Event('input'))
    respond(worker)
    expect(viewer.renderReplayView).toHaveBeenCalledOnce()
    expect(worker.postMessage.mock.calls.at(-1)![0].position).toBe(2.5)
    respond(worker)
    expect(viewer.renderReplayView).toHaveBeenCalledTimes(2)
    expect(element('[data-testid=replay-time]').textContent).toBe('2.500 / 60.000 s')
  })
  it('returns to live and ignores obsolete worker results, including reimport of the same file', () => {
    const first = upload(); loaded(first)
    element<HTMLButtonElement>('[data-action=live]').click()
    expect(first.terminate).toHaveBeenCalledOnce()
    expect(element('.sw-replay-inline').hidden).toBe(true)
    const second = upload(); first.send({ type: 'loaded', duration: 5, channels: [] }); loaded(second)
    expect(viewer.beginReplay).toHaveBeenCalledTimes(2)
    expect(element<HTMLInputElement>('[data-testid=replay-file]').value).toBe('')
  })
  it('releases the worker and restores live mode after a parse failure or unmount', () => {
    const worker = upload(); loaded(worker)
    worker.send({ type: 'error', message: 'Line 3: invalid timestamp' })
    expect(element('.sw-replay-message').textContent).toContain('Line 3')
    expect(worker.terminate).toHaveBeenCalledOnce()
    const second = upload(); loaded(second); dispose()
    expect(second.terminate).toHaveBeenCalledOnce()
    expect(document.querySelector('.sw-replay-inline')).toBeNull()
  })
  it('handles a single-timestamp log without starting a playback loop', () => {
    const worker = upload(); loaded(worker, 0); control('play')
    expect(element('.sw-replay-inline').dataset.playbackState).toBe('ended')
  })
})
