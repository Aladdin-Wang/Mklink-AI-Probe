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
let dispose: () => void
function element<T extends HTMLElement>(selector: string) { return document.querySelector(selector) as T }
function click(action: string) { element<HTMLButtonElement>(`[data-action=${action}]`).click() }
function upload() {
  const input = element<HTMLInputElement>('[data-testid=replay-file]')
  Object.defineProperty(input, 'files', { value: [new File(['timestamp,a\n0,1'], 'test.csv')], configurable: true })
  input.dispatchEvent(new Event('change'))
  return FakeWorker.instances.at(-1)!
}
function loaded(worker: FakeWorker, duration = 10) {
  worker.send({ type: 'loaded', rows: 100, values: 100, duration, channels: [{ name: 'a', count: 100 }] })
  const request = worker.postMessage.mock.calls.at(-1)![0]
  worker.send({ type: 'view', id: request.id, start: 0, end: 10, position: 0, channels: [{ name: 'a', points: [[0, 1]], latest: 1 }] })
}
describe('replay controls and lifetime', () => {
  beforeEach(() => {
    FakeWorker.instances = []
    vi.stubGlobal('Worker', FakeWorker)
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(new Proxy({}, { get: () => vi.fn() }) as any)
    document.body.innerHTML = '<div class="host"></div>'
    dispose = mountReplayButton(element('.host'), { language: 'en' })
    element<HTMLButtonElement>('[data-testid=open-superwatch-replay]').click()
  })
  afterEach(() => { dispose(); vi.restoreAllMocks(); vi.unstubAllGlobals(); document.body.innerHTML = '' })
  it('imports without any device request and seeks backwards to the requested position', () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    const worker = upload(); loaded(worker)
    click('overview')
    const slider = element<HTMLInputElement>('[data-testid=replay-seek]')
    slider.value = '2.5'; slider.dispatchEvent(new Event('input'))
    expect(element('[data-testid=replay-time]').textContent).toBe('2.500 / 10.000 s')
    const inFlight = worker.postMessage.mock.calls.at(-1)![0]
    worker.send({ type: 'view', id: inFlight.id, start: 0, end: 10, position: 10, channels: [] })
    expect(worker.postMessage.mock.calls.at(-1)![0].position).toBe(2.5)
    expect(fetch).not.toHaveBeenCalled()
  })
  it('cancels loading, ignores obsolete worker results and accepts the same file again', () => {
    const first = upload(); click('cancel')
    first.send({ type: 'loaded', duration: 10, rows: 5, channels: [] })
    expect(element<HTMLButtonElement>('[data-action=play]').disabled).toBe(true)
    expect(first.terminate).toHaveBeenCalledOnce()
    const second = upload(); loaded(second)
    expect(element<HTMLButtonElement>('[data-action=play]').disabled).toBe(false)
    expect(element<HTMLInputElement>('[data-testid=replay-file]').value).toBe('')
  })
  it('reports parse errors and releases the worker without retaining prior data', () => {
    const worker = upload(); loaded(worker)
    worker.send({ type: 'error', message: 'Line 3: invalid timestamp' })
    expect(element('.sw-replay-message').textContent).toContain('Line 3')
    expect(element<HTMLButtonElement>('[data-action=play]').disabled).toBe(true)
    expect(worker.terminate).toHaveBeenCalledOnce()
  })
  it('handles a single-timestamp log and restart without an animation loop', () => {
    const worker = upload(); loaded(worker, 0)
    click('restart')
    expect(element('.sw-replay').dataset.playbackState).toBe('ended')
    expect(element('[data-testid=replay-time]').textContent).toBe('0.000 / 0.000 s')
  })
  it('isolates keyboard shortcuts and closes with Escape semantics', () => {
    const liveShortcut = vi.fn(); document.addEventListener('keydown', liveShortcut)
    const worker = upload(); loaded(worker)
    element('[data-action=play]').dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }))
    expect(liveShortcut).not.toHaveBeenCalled()
    element('.sw-replay').dispatchEvent(new Event('cancel', { cancelable: true }))
    expect(document.querySelector('.sw-replay')).toBeNull()
    expect(worker.terminate).toHaveBeenCalledOnce()
    document.removeEventListener('keydown', liveShortcut)
  })
  it('disposes an open dialog and its worker when the parent viewer unmounts', () => {
    const worker = upload(); dispose()
    expect(worker.terminate).toHaveBeenCalledOnce()
    expect(document.querySelector('dialog')).toBeNull()
    expect(document.querySelector('[data-testid=open-superwatch-replay]')).toBeNull()
  })
})
