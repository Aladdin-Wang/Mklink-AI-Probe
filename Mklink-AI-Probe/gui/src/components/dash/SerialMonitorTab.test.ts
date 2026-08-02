import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SerialMonitorTab from './SerialMonitorTab.vue'

const mocks = vi.hoisted(() => ({
  listPorts: vi.fn(),
  toastError: vi.fn(),
  terminalWrites: [] as string[],
  terminalClears: 0,
  terminalInput: null as null | ((data: string) => void),
}))

vi.mock('../../composables/useMklinkApi', () => ({
  useMklinkApi: () => ({ listPorts: mocks.listPorts }),
}))

vi.mock('../../composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: mocks.toastError, info: vi.fn() }),
}))

vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    options: Record<string, unknown>

    constructor(options: Record<string, unknown>) {
      this.options = { disableStdin: options.disableStdin }
    }

    loadAddon() {}
    open() {}
    onData(callback: (data: string) => void) {
      mocks.terminalInput = callback
      return { dispose() {} }
    }
    clear() { mocks.terminalClears += 1 }
    write(text: string) { mocks.terminalWrites.push(text) }
    focus() {}
    dispose() {}
  },
}))

vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }))

class FakeEventSource {
  static instances: FakeEventSource[] = []
  static CLOSED = 2
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  readyState = 1
  url: string

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  close() { this.readyState = FakeEventSource.CLOSED }
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent)
  }
}

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>()
  get length(): number { return this.values.size }
  clear(): void { this.values.clear() }
  getItem(key: string): string | null { return this.values.get(key) ?? null }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null }
  removeItem(key: string): void { this.values.delete(key) }
  setItem(key: string, value: string): void { this.values.set(key, value) }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function runningStatus() {
  return {
    running: true,
    ports: { TEST_UART: 'open' },
    config: [{ port: 'TEST_UART', baudrate: 230400, databits: 8, stopbits: 1, parity: 'N' }],
    stats: { rx_count: 0, tx_count: 0, rx_bytes: 0, tx_bytes: 0, bytes_per_sec: 0 },
  }
}

describe('SerialMonitorTab', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', new MemoryStorage())
    FakeEventSource.instances.length = 0
    mocks.listPorts.mockReset().mockResolvedValue([
      { device: 'TEST_UART', description: 'USB UART', is_mklink: false },
    ])
    mocks.toastError.mockReset()
    mocks.terminalWrites.length = 0
    mocks.terminalClears = 0
    mocks.terminalInput = null
    vi.stubGlobal('EventSource', FakeEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('runs without an MKLink connection and does not stop the backend when unmounted', async () => {
    let status = { ...runningStatus(), running: false, ports: {}, config: [] }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/dash/serial/status')) return jsonResponse(status)
      if (url.endsWith('/api/dash/serial/start')) {
        status = runningStatus()
        return jsonResponse({ status: 'started' })
      }
      if (url.endsWith('/api/dash/serial/send')) return jsonResponse({ ok: true })
      throw new Error(`Unexpected request: ${url} ${init?.method || 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(SerialMonitorTab)
    await vi.waitFor(() => expect(wrapper.text()).toContain('USB UART'))

    expect(wrapper.text()).not.toContain('请先连接设备')
    await wrapper.get('.btn-primary').trigger('click')
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))

    const stream = FakeEventSource.instances[0]
    stream.emit({
      event: 'terminal', direction: 'RX',
      data_base64: btoa('\u001b[31mprompt> '),
    })
    expect(mocks.terminalWrites.join('')).toContain('\u001b[31mprompt> ')
    const writesAfterRx = mocks.terminalWrites.length
    stream.emit({ event: 'terminal', direction: 'TX', data_base64: btoa('local echo') })
    expect(mocks.terminalWrites).toHaveLength(writesAfterRx)

    mocks.terminalInput?.('help\r')
    await vi.waitFor(() => {
      const send = fetchMock.mock.calls.find(call => String(call[0]).endsWith('/api/dash/serial/send'))
      expect(send).toBeTruthy()
      expect(JSON.parse(String(send?.[1]?.body))).toEqual({
        port: 'TEST_UART', data: '68656c700d', hex: true,
      })
    })

    wrapper.unmount()
    expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith('/api/dash/serial/stop'))).toBe(false)
    expect(stream.readyState).toBe(FakeEventSource.CLOSED)
  })

  it('reconnects to an existing serial session and clears only the visible mode', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/dash/serial/status')) return jsonResponse(runningStatus())
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(SerialMonitorTab)
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const stream = FakeEventSource.instances[0]
    stream.emit({
      event: 'data', timestamp: '12:00:00.000', direction: 'RX',
      raw_hex: '4F4B0A', ascii: 'OK\n',
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('4F4B0A')

    await wrapper.get('[data-testid="serial-terminal-mode"]').trigger('click')
    await wrapper.get('.clear-action').trigger('click')
    expect(mocks.terminalClears).toBeGreaterThan(0)
    await wrapper.get('[data-testid="serial-log-mode"]').trigger('click')
    expect(wrapper.text()).toContain('4F4B0A')
    expect((wrapper.get('select').element as HTMLSelectElement).value).toBe('TEST_UART')

    wrapper.unmount()
  })
})
