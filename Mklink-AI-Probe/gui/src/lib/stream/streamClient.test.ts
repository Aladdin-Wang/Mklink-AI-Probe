import { afterEach, describe, expect, it, vi } from 'vitest'
import { StreamClient, type StreamClientState } from './streamClient'

class FakeSocket {
  static readonly OPEN = 1
  binaryType = ''
  readyState = 0
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  readonly sent: string[] = []
  closeCalls = 0

  constructor(readonly url: string) {}

  open() {
    this.readyState = FakeSocket.OPEN
    this.onopen?.(new Event('open'))
  }

  send(value: string) {
    this.sent.push(value)
  }

  close() {
    this.closeCalls += 1
    this.readyState = 3
  }

  emitClose() {
    this.readyState = 3
    this.onclose?.(new CloseEvent('close'))
  }
}

function setup(token?: string) {
  const sockets: FakeSocket[] = []
  const worker = {
    postMessage: vi.fn(),
    terminate: vi.fn(),
    onmessage: null as ((event: MessageEvent) => void) | null,
  }
  const states: StreamClientState[] = []
  const outputs: unknown[] = []
  const client = new StreamClient({
    url: 'ws://localhost/ws/streams/vofa',
    token,
    capacity: 100,
    channelCount: 2,
    reconnectBaseMs: 100,
    reconnectMaxMs: 400,
    createWebSocket: url => {
      const socket = new FakeSocket(url)
      sockets.push(socket)
      return socket as unknown as WebSocket
    },
    worker: worker as unknown as Worker,
    onState: state => states.push(state),
    onWorkerMessage: message => outputs.push(message),
  })
  return { client, sockets, worker, states, outputs }
}

afterEach(() => vi.useRealTimers())

describe('StreamClient', () => {
  it('uses arraybuffer frames, transfers ownership to the worker, and authenticates first', () => {
    const { client, sockets, worker } = setup('secret')
    client.start()
    const socket = sockets[0]
    expect(socket.binaryType).toBe('arraybuffer')
    socket.open()
    expect(socket.sent).toEqual([JSON.stringify({ params: { token: 'secret' } })])

    const buffer = new ArrayBuffer(16)
    socket.onmessage?.(new MessageEvent('message', { data: buffer }))
    expect(worker.postMessage).toHaveBeenNthCalledWith(1, {
      type: 'configure', capacity: 100, channelCount: 2,
    })
    expect(worker.postMessage).toHaveBeenNthCalledWith(2, { type: 'frame', buffer }, [buffer])
  })

  it('reconnects with capped exponential delays without real sleeping', () => {
    vi.useFakeTimers()
    const { client, sockets, states } = setup()
    client.start()
    sockets[0].emitClose()
    expect(states.at(-1)).toMatchObject({ phase: 'reconnecting', reconnectDelayMs: 100 })
    vi.advanceTimersByTime(100)
    expect(sockets).toHaveLength(2)
    sockets[1].emitClose()
    vi.advanceTimersByTime(199)
    expect(sockets).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(sockets).toHaveLength(3)
    sockets[2].emitClose()
    vi.advanceTimersByTime(400)
    expect(sockets).toHaveLength(4)
    sockets[3].emitClose()
    vi.advanceTimersByTime(400)
    expect(sockets).toHaveLength(5)
  })

  it('does not reconnect after explicit stop', () => {
    vi.useFakeTimers()
    const { client, sockets, states } = setup()
    client.start()
    sockets[0].emitClose()
    client.stop()
    vi.runAllTimers()
    expect(sockets).toHaveLength(1)
    expect(states.at(-1)).toMatchObject({ phase: 'stopped' })
  })

  it('disposes the socket and worker exactly once and forwards worker messages', () => {
    const { client, sockets, worker, outputs } = setup()
    client.start()
    worker.onmessage?.(new MessageEvent('message', { data: { type: 'channels', channelCount: 2 } }))
    expect(outputs).toEqual([{ type: 'channels', channelCount: 2 }])

    client.dispose()
    client.dispose()
    expect(sockets[0].closeCalls).toBe(1)
    expect(worker.terminate).toHaveBeenCalledTimes(1)
    expect(() => client.start()).toThrow(/disposed/)
  })

  it('rejects non-ArrayBuffer messages instead of posting malformed frames', () => {
    const { client, sockets, worker, states } = setup()
    client.start()
    sockets[0].open()
    sockets[0].onmessage?.(new MessageEvent('message', { data: 'not binary' }))
    expect(worker.postMessage).toHaveBeenCalledTimes(1)
    expect(states.at(-1)).toMatchObject({ phase: 'error' })
  })
})
