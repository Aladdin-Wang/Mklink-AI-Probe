import { mount, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest'
import { reactive } from 'vue'
import App from '../App.vue'
import router from '../router'
import type { JobAction, JobRequest, PackOperationResponse } from '../types/onlineFlash'
import DashboardView from './DashboardView.vue'
import FlashLogPanel from '../components/online-flash/FlashLogPanel.vue'
import FirmwareWorkspace from '../components/online-flash/FirmwareWorkspace.vue'
import actionBarSource from '../components/online-flash/FlashActionBar.vue?raw'

async function onlineFlashView() {
  const path = './OnlineFlashView.vue'
  return (await import(/* @vite-ignore */ path)).default
}

async function onlineFlashApi() {
  const path = '../composables/useOnlineFlashApi'
  return (await import(/* @vite-ignore */ path)).useOnlineFlashApi()
}

async function onlineFlashApiModule() {
  const path = '../composables/useOnlineFlashApi'
  return import(/* @vite-ignore */ path)
}

vi.mock('../composables/useMklinkApi', () => ({
  useMklinkApi: () => ({
    deviceStatus: reactive({ connected: true }),
    startStatusPolling: vi.fn(),
    stopStatusPolling: vi.fn(),
    flashDevice: vi.fn(),
    resetDevice: vi.fn(),
    eraseDevice: vi.fn(),
    haltDevice: vi.fn(),
    resumeDevice: vi.fn(),
  }),
}))

vi.mock('../composables/useBackendHealth', () => ({
  useBackendHealth: () => ({ startHealthPolling: vi.fn(), stopHealthPolling: vi.fn() }),
}))

vi.mock('../composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}))

vi.mock('../composables/useResourceStatus', () => ({
  useResourceStatus: () => ({ refresh: vi.fn(), getBridgeOwner: () => '' }),
}))

class FakeEventSource {
  static instances: FakeEventSource[] = []
  readonly listeners = new Map<string, Array<(event: Event) => void>>()
  closed = false

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this)
  }

  addEventListener(name: string, listener: (event: Event) => void) {
    const listeners = this.listeners.get(name) ?? []
    listeners.push(listener)
    this.listeners.set(name, listeners)
  }

  emit(name: string, data: unknown) {
    if (this.closed) return
    const event = new MessageEvent(name, { data: JSON.stringify(data) })
    for (const listener of this.listeners.get(name) ?? []) listener(event)
  }

  emitNativeError() {
    if (this.closed) return
    const event = new Event('error')
    for (const listener of this.listeners.get('error') ?? []) listener(event)
  }

  close() {
    this.closed = true
  }
}

const dashStub = { template: '<div />', props: ['deviceConnected'] }

describe('online flash navigation and workspace', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn(), removeItem: vi.fn(), clear: vi.fn() })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const value = url.endsWith('/packs/status')
        ? { last_error: null, index_available: false, target_count: 0 }
        : []
      return new Response(JSON.stringify(value), { status: 200 })
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('registers the hash-router online flash route', () => {
    const route = router.getRoutes().find(candidate => candidate.name === 'online-flash')

    expect(route?.path).toBe('/online-flash')
  })

  it('shows 在线烧录 after 仪表盘 in the top navigation and navigates to it', async () => {
    await router.push('/config')
    await router.isReady()
    const wrapper = mount(App, {
      global: {
        plugins: [router],
        stubs: { RouterView: true, StatusBar: true, ToastContainer: true },
      },
    })

    const labels = wrapper.findAll('.nav-tab').map(tab => tab.text())
    expect(labels).toEqual(['配置', '仪表盘', '在线烧录'])

    await wrapper.findAll('.nav-tab')[2].trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('online-flash'))
    wrapper.unmount()
  })

  it('renames the legacy dashboard tab to exactly 脱机烧录', async () => {
    await router.push('/dashboard')
    const wrapper = shallowMount(DashboardView, {
      global: {
        plugins: [router],
        stubs: {
          RttViewTab: dashStub,
          HardFaultTab: dashStub,
          SymbolsTab: dashStub,
          MemoryTab: dashStub,
          SuperWatchTab: dashStub,
          SerialMonitorTab: dashStub,
          ModbusTab: dashStub,
          VofaTab: dashStub,
          SystemViewTab: dashStub,
        },
      },
    })
    try {
      const labels = wrapper.findAll('.tab-btn').map(tab => tab.text())
      expect(labels).toContain('脱机烧录')
      expect(labels).not.toContain('烧录')
    } finally {
      wrapper.unmount()
    }
  })

  it('mounts the stable four-zone workspace landmarks', async () => {
    const wrapper = mount(await onlineFlashView())

    expect(wrapper.find('.online-flash-grid').exists()).toBe(true)
    expect(wrapper.find('aside[data-zone="settings"]').exists()).toBe(true)
    expect(wrapper.find('main[data-zone="firmware"]').exists()).toBe(true)
    expect(wrapper.find('aside[data-zone="flash-map"]').exists()).toBe(true)
    expect(wrapper.find('section[data-zone="logs"]').exists()).toBe(true)
  })

  it('renders the firmware workspace as the only main landmark', async () => {
    await router.push('/online-flash')
    const wrapper = mount(App, {
      global: {
        plugins: [router],
        stubs: { StatusBar: true, ToastContainer: true },
      },
    })
    try {
      await vi.waitFor(() => expect(wrapper.find('main[data-zone="firmware"]').exists()).toBe(true))
      expect(wrapper.findAll('main')).toHaveLength(1)
    } finally {
      wrapper.unmount()
    }
  })
})

describe('useOnlineFlashApi', () => {
  beforeEach(() => {
    FakeEventSource.instances = []
    vi.stubGlobal('fetch', vi.fn())
    vi.stubGlobal('EventSource', FakeEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('does not make a request until a client method is called', async () => {
    await onlineFlashApi()

    expect(fetch).not.toHaveBeenCalled()
  })

  it('encodes target search filters in the request URL', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('[]', { status: 200 }))
    const api = await onlineFlashApi()

    await api.searchTargets('hpm 53', { vendor: 'HPMicro & Co', installed: true, limit: 7 })

    const [url, options] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/online-flash/targets?q=hpm+53&vendor=HPMicro+%26+Co&installed=true&limit=7')
    expect(new Headers(options?.headers).get('Content-Type')).toBe('application/json')
  })

  it('uses multipart FormData without forcing a JSON content type', async () => {
    vi.mocked(fetch).mockImplementation(async () => new Response('{}', { status: 200 }))
    const api = await onlineFlashApi()
    const pack = new File(['pack'], 'device.pack')
    const image = new File(['firmware'], 'firmware.bin')

    await api.importPack(pack)
    await api.inspectImage(image, 'HPM5300', 0x1000)

    const [importUrl, importOptions] = vi.mocked(fetch).mock.calls[0]
    const [inspectUrl, inspectOptions] = vi.mocked(fetch).mock.calls[1]
    expect(importUrl).toBe('/api/online-flash/packs/import')
    expect(inspectUrl).toBe('/api/online-flash/images/inspect')
    expect(importOptions?.body).toBeInstanceOf(FormData)
    expect(inspectOptions?.body).toBeInstanceOf(FormData)
    expect(new Headers(importOptions?.headers).has('Content-Type')).toBe(false)
    expect(new Headers(inspectOptions?.headers).has('Content-Type')).toBe(false)
  })

  it('forwards preview abort signals to fetch', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('{}', { status: 200 }))
    const controller = new AbortController()
    const api = await onlineFlashApi()

    await api.previewImage('image', 0, 4096, controller.signal)

    expect(vi.mocked(fetch).mock.calls[0][1]?.signal).toBe(controller.signal)
  })

  it('posts job JSON and addresses job endpoints', async () => {
    vi.mocked(fetch).mockImplementation(async () => new Response('{}', { status: 200 }))
    const api = await onlineFlashApi()
    const request = {
      actions: ['connect', 'disconnect'],
      probe_id: 'probe/1',
      target_part: 'HPM5300',
    }

    await api.createJob(request)
    await api.getActiveJob()
    await api.getJob('job/1')
    await api.stopJob('job/1')

    expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toEqual([
      '/api/online-flash/jobs',
      '/api/online-flash/jobs/active',
      '/api/online-flash/jobs/job%2F1',
      '/api/online-flash/jobs/job%2F1/stop',
    ])
    expect(vi.mocked(fetch).mock.calls[0][1]).toEqual(expect.objectContaining({
      method: 'POST',
      body: JSON.stringify(request),
    }))
    expectTypeOf<JobRequest['actions'][number]>().toEqualTypeOf<JobAction>()
  })

  it('preserves structured API conflict details', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({
      detail: { code: 'PROBE_BUSY', owner: 'ai-session', resource: 'TARGET_DEBUG' },
    }), { status: 409, statusText: 'Conflict' }))
    const { OnlineFlashApiError, useOnlineFlashApi } = await onlineFlashApiModule()

    const error = await useOnlineFlashApi().listProbes().catch((value: unknown) => value)

    expect(error).toBeInstanceOf(OnlineFlashApiError)
    expect(error).toMatchObject({
      status: 409,
      code: 'PROBE_BUSY',
      owner: 'ai-session',
      resource: 'TARGET_DEBUG',
      detail: { code: 'PROBE_BUSY', owner: 'ai-session', resource: 'TARGET_DEBUG' },
    })
    expect(error.message).toBe('PROBE_BUSY: TARGET_DEBUG is owned by ai-session')
  })

  it('formats nested API details as stable JSON instead of object coercion', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({
      detail: { validation: { reason: 'invalid', field: 'base_address' } },
    }), { status: 422, statusText: 'Unprocessable Entity' }))
    const { OnlineFlashApiError, useOnlineFlashApi } = await onlineFlashApiModule()

    const error = await useOnlineFlashApi().listProbes().catch((value: unknown) => value)

    expect(error).toBeInstanceOf(OnlineFlashApiError)
    expect(error.message).toBe('{"validation":{"field":"base_address","reason":"invalid"}}')
  })

  it('returns consumable adapter and default-worker Pack variants', async () => {
    const fixtures = [
      {
        result: { status: 'installed', part_number: 'STM32F103RC' },
        events: [{ type: 'progress', progress: 0.5 }],
      },
      {
        result: { status: 'installed', pack_id: 'Keil.STM32F1xx_DFP', version: '2.4.1' },
        events: [{ type: 'progress', current: 1, total: 2 }],
      },
      {
        result: { status: 'updated' },
        events: [{ type: 'log', message: 'updated' }],
      },
      {
        result: { status: 'updated', target_count: 42 },
        events: [],
      },
    ] satisfies PackOperationResponse[]
    const pending = [...fixtures]
    vi.mocked(fetch).mockImplementation(async () => (
      new Response(JSON.stringify(pending.shift()), { status: 200 })
    ))
    const api = await onlineFlashApi()

    const responses = [
      await api.installPack('STM32F103RC'),
      await api.installPack('STM32F103RC'),
      await api.updatePackIndex(),
      await api.updatePackIndex(),
    ]

    expect(responses.map(consumePackResponse)).toEqual([
      ['0.5', 'STM32F103RC'],
      ['1/2', 'Keil.STM32F1xx_DFP@2.4.1'],
      ['updated', 'updated'],
      ['42'],
    ])
  })

  it('filters replayed sequences and closes synchronously after a terminal event', async () => {
    const onEvent = vi.fn()
    const subscription = (await onlineFlashApi()).subscribeJob('job/1', 12, onEvent)
    const source = FakeEventSource.instances[0]
    const progress = {
      job_id: 'job/1', sequence: 13, timestamp: 1, event: 'progress', message: '',
      state: null, progress: 0.5,
    }
    const terminal = {
      job_id: 'job/1', sequence: 14, timestamp: 2, event: 'state', message: '',
      state: 'succeeded', progress: 1,
    }

    expect(source.url).toBe('/api/online-flash/jobs/job%2F1/events?after=12')
    source.emit('progress', progress)
    source.emit('progress', progress)
    source.emit('state', terminal)
    source.emit('progress', { ...progress, sequence: 15 })
    expect(onEvent).toHaveBeenCalledTimes(2)
    expect(onEvent).toHaveBeenNthCalledWith(1, progress)
    expect(onEvent).toHaveBeenNthCalledWith(2, terminal)
    expect(source.closed).toBe(true)

    subscription.close()
    expect(source.closed).toBe(true)
  })

  it('closes after a server error event without enabling native reconnect', async () => {
    const onEvent = vi.fn()
    const subscription = (await onlineFlashApi()).subscribeJob('job/1', 0, onEvent)
    const eventSource = FakeEventSource.instances[0]

    eventSource.emit('error', { code: 'UNKNOWN_ERROR', message: 'event stream failed' })

    expect(onEvent).toHaveBeenCalledWith({ code: 'UNKNOWN_ERROR', message: 'event stream failed' })
    expect(eventSource.closed).toBe(true)
    expect(eventSource.listeners.get('error')).toHaveLength(1)
    subscription.close()
  })

  it('closes and reports a native connection error exactly once', async () => {
    const onEvent = vi.fn()
    const onError = vi.fn()
    ;(await onlineFlashApi()).subscribeJob('job/1', 7, onEvent, onError)
    const source = FakeEventSource.instances[0]

    source.emitNativeError()
    source.emitNativeError()

    expect(source.closed).toBe(true)
    expect(source.listeners.get('error')).toHaveLength(1)
    expect(onEvent).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError).toHaveBeenCalledWith({
      code: 'STREAM_ERROR',
      message: 'Event stream connection failed',
    })
  })
})

function consumePackResponse(response: PackOperationResponse): string[] {
  const events = response.events.map(event => {
    if (event.type === 'log') return event.message
    if ('progress' in event) return String(event.progress)
    return `${event.current}/${event.total}`
  })
  const result = response.result
  if (result.status === 'installed') {
    if ('part_number' in result) return [...events, result.part_number]
    return [...events, `${result.pack_id}@${result.version}`]
  }
  return [...events, 'target_count' in result ? String(result.target_count) : 'updated']
}

const probeFixture = {
  unique_id: 'mklink-1', vendor_name: 'MuseLab', product_name: 'MKLink',
  description: 'MKLink CMSIS-DAP', vid: 0x34b7, pid: 0x0001, serial_number: 'ABC',
}

const installedTarget = {
  part_number: 'HPM5300', vendor: 'HPMicro', pack_id: 'HPMicro.HPM_SDK',
  pack_version: '1.0.0', installed: true, source: 'installed',
}

function viewFetch(targets = [installedTarget]) {
  return vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input)
    const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200 })
    if (url.endsWith('/probes')) return json([probeFixture])
    if (url.includes('/targets?')) return json(targets)
    if (url.endsWith('/packs/status')) return json({ last_error: null, index_available: true, target_count: targets.length })
    if (url.endsWith('/packs/install')) return json({
      result: { status: 'installed', part_number: JSON.parse(String(options?.body)).part_number },
      events: [{ type: 'progress', progress: 1 }],
    })
    if (url.endsWith('/images/inspect')) return json({
      image_id: 'image-1', file_name: 'firmware.bin', format: 'bin', size: 32,
      sha256: 'abc123', start: 0x80000000, end: 0x80000020,
      segments: [{ start: 0x80000000, end: 0x80000020 }], base_address: 0x80000000,
    })
    if (url.includes('/preview?')) return json({
      address: 0x80000000, length: 32, data_base64: btoa('\x41'.repeat(32)), present: Array(32).fill(true),
    })
    if (url.endsWith('/jobs') && options?.method === 'POST') return json({
      job_id: 'job-1',
      job: {
        job_id: 'job-1', state: 'queued', actions: ['program'], image_id: 'image-1',
        created_at: 1, updated_at: 1, probe_id: 'mklink-1', target_part: 'HPM5300',
        frequency: 1000000, connect_mode: 'halt', reset_mode: 'default', file_path: null,
        image_format: 'bin', image_start: 0x80000000, image_end: 0x80000020,
        image_size: 32, image_sha256: 'abc123', current_action: null, stage_progress: 0,
        total_progress: 0, speed_bytes_per_second: 0, elapsed_seconds: 0,
        error_code: null, error_message: null,
      },
    })
    if (url.endsWith('/jobs/job-1/stop')) return json({ state: 'stopping', job_id: 'job-1' })
    throw new Error(`Unexpected request: ${url}`)
  })
}

async function chooseFirmware(wrapper: ReturnType<typeof mount>, name = 'firmware.bin') {
  const input = wrapper.get('[data-testid="firmware-input"]')
  Object.defineProperty(input.element, 'files', {
    configurable: true,
    value: [new File(['firmware'], name)],
  })
  await input.trigger('change')
}

async function readyAndStart(wrapper: ReturnType<typeof mount>) {
  await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
  await wrapper.get('[data-testid="target-HPM5300"]').trigger('click')
  await chooseFirmware(wrapper)
  await wrapper.get('[data-testid="bin-base"]').setValue('0x80000000')
  await wrapper.get('[data-testid="inspect-image"]').trigger('click')
  await vi.waitFor(() => expect(wrapper.get('[data-testid="start-job"]').attributes('disabled')).toBeUndefined())
  await wrapper.get('[data-testid="start-job"]').trigger('click')
  await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
}

describe('online flash task workspace behavior', () => {
  beforeEach(() => {
    FakeEventSource.instances = []
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear(),
    })
    vi.stubGlobal('fetch', viewFetch())
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('rejects an invalid BIN base and keeps start disabled until server inspection succeeds', async () => {
    const wrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
    await wrapper.get('[data-testid="target-HPM5300"]').trigger('click')
    await chooseFirmware(wrapper)
    await wrapper.get('[data-testid="bin-base"]').setValue('80000000')

    expect(wrapper.get('[data-testid="base-error"]').text()).toContain('0x')
    expect(wrapper.get('[data-testid="start-job"]').attributes('disabled')).toBeDefined()

    await wrapper.get('[data-testid="bin-base"]').setValue('0x80000000')
    await wrapper.get('[data-testid="inspect-image"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.get('[data-testid="start-job"]').attributes('disabled')).toBeUndefined())
    wrapper.unmount()
  })

  it('aborts and ignores an in-flight inspection when the BIN base changes', async () => {
    const fallback = viewFetch()
    let inspectionSignal: AbortSignal | null = null
    let resolveInspection!: (response: Response) => void
    const pendingInspection = new Promise<Response>(resolve => { resolveInspection = resolve })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).endsWith('/images/inspect')) {
        inspectionSignal = options?.signal ?? null
        return pendingInspection
      }
      return fallback(input, options)
    }))
    const wrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
    await wrapper.get('[data-testid="target-HPM5300"]').trigger('click')
    await chooseFirmware(wrapper)
    await wrapper.get('[data-testid="bin-base"]').setValue('0x80000000')
    await wrapper.get('[data-testid="inspect-image"]').trigger('click')
    await vi.waitFor(() => expect(inspectionSignal).not.toBeNull())

    await wrapper.get('[data-testid="bin-base"]').setValue('0x80001000')
    expect(inspectionSignal?.aborted).toBe(true)
    resolveInspection(new Response(JSON.stringify({
      image_id: 'stale-image', file_name: 'firmware.bin', format: 'bin', size: 32,
      sha256: 'stale', start: 0x80000000, end: 0x80000020,
      segments: [{ start: 0x80000000, end: 0x80000020 }], base_address: 0x80000000,
    }), { status: 200 }))
    await Promise.resolve()
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-testid="start-job"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('stale-image')
    wrapper.unmount()
  })

  it('aborts a deferred inspection before unmount cleanup can start preview work', async () => {
    const fallback = viewFetch()
    let inspectionSignal: AbortSignal | null = null
    let resolveInspection!: (response: Response) => void
    const pending = new Promise<Response>(resolve => { resolveInspection = resolve })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).endsWith('/images/inspect')) { inspectionSignal = options?.signal ?? null; return pending }
      return fallback(input, options)
    }))
    const wrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
    await wrapper.get('[data-testid="target-HPM5300"]').trigger('click')
    await chooseFirmware(wrapper)
    await wrapper.get('[data-testid="inspect-image"]').trigger('click')
    await vi.waitFor(() => expect(inspectionSignal).not.toBeNull())

    wrapper.unmount()
    expect(inspectionSignal?.aborted).toBe(true)
    resolveInspection(new Response(JSON.stringify({
      image_id: 'late', file_name: 'firmware.bin', format: 'bin', size: 32, sha256: 'late',
      start: 0x80000000, end: 0x80000020, segments: [], base_address: 0x80000000,
    }), { status: 200 }))
    for (let index = 0; index < 20; index += 1) await Promise.resolve()
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/preview?'))).toHaveLength(0)
  })

  it('does not trust an install response when refreshed exact target remains uninstalled', async () => {
    const missing = { ...installedTarget, installed: false, source: 'index' }
    vi.stubGlobal('fetch', viewFetch([missing]))
    const wrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))

    await wrapper.get('[data-testid="target-HPM5300"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('安装后索引仍未确认'))

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('下载'))
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/packs/install'))).toBe(true)
    expect(wrapper.get('[data-testid="pack-status"]').text()).toContain('未就绪')
    expect(wrapper.get('[data-testid="start-job"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('debounces target searches without relying on real-time sleeps', async () => {
    vi.useFakeTimers()
    const wrapper = mount(await onlineFlashView())
    const initialSearchCount = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/targets?')).length

    await wrapper.get('input[aria-label="搜索器件"]').setValue('HPM 53')
    await vi.advanceTimersByTimeAsync(299)
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('q=HPM+53'))).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(1)

    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('q=HPM+53'))).toHaveLength(1)
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/targets?')).length).toBe(initialSearchCount + 1)
    wrapper.unmount()
  })

  it('commits only the latest target search response', async () => {
    vi.useFakeTimers()
    const fallback = viewFetch()
    let resolveInitial!: (response: Response) => void
    let initialSignal: AbortSignal | null = null
    const initial = new Promise<Response>(resolve => { resolveInitial = resolve })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input)
      if (url.includes('/targets?q=')) {
        const query = new URL(url, 'http://local').searchParams.get('q')
        if (!query) { initialSignal = options?.signal ?? null; return initial }
        return Promise.resolve(new Response(JSON.stringify([{ ...installedTarget, part_number: 'NEW-TARGET' }]), { status: 200 }))
      }
      return fallback(input, options)
    }))
    const wrapper = mount(await onlineFlashView())
    await wrapper.get('input[aria-label="搜索器件"]').setValue('new')
    await vi.advanceTimersByTimeAsync(300)
    await vi.waitFor(() => expect(wrapper.text()).toContain('NEW-TARGET'))
    expect(initialSignal?.aborted).toBe(true)
    resolveInitial(new Response(JSON.stringify([{ ...installedTarget, part_number: 'OLD-TARGET' }]), { status: 200 }))
    for (let index = 0; index < 10; index += 1) await Promise.resolve()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('NEW-TARGET')
    expect(wrapper.text()).not.toContain('OLD-TARGET')
    wrapper.unmount()
  })

  it('locks Pack install and cancel operations against duplicate clicks', async () => {
    const missing = { ...installedTarget, installed: false, source: 'index' }
    const fallback = viewFetch([missing])
    let resolveInstall!: (response: Response) => void
    let resolveCancel!: (response: Response) => void
    const install = new Promise<Response>(resolve => { resolveInstall = resolve })
    const cancel = new Promise<Response>(resolve => { resolveCancel = resolve })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/packs/install')) return install
      if (url.endsWith('/packs/cancel')) return cancel
      return fallback(input, options)
    }))
    const wrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
    const target = wrapper.get('[data-testid="target-HPM5300"]')
    await target.trigger('click'); await target.trigger('click')
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/packs/install'))).toHaveLength(1)
    expect(target.attributes('disabled')).toBeDefined()
    const cancelButton = wrapper.get('[data-testid="pack-cancel"]')
    await cancelButton.trigger('click'); await cancelButton.trigger('click')
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/packs/cancel'))).toHaveLength(1)
    expect(cancelButton.attributes('disabled')).toBeDefined()
    resolveCancel(new Response(JSON.stringify({ status: 'cancelled' }), { status: 200 }))
    for (let index = 0; index < 5; index += 1) await Promise.resolve()
    expect(target.attributes('disabled')).toBeDefined()
    expect(cancelButton.attributes('disabled')).toBeDefined()
    resolveInstall(new Response(JSON.stringify({ result: { status: 'installed', part_number: 'HPM5300' }, events: [] }), { status: 200 }))
    wrapper.unmount()
  })

  it('replays from sequence zero, deduplicates logs, and explicitly reconnects after a stream error', async () => {
    const wrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
    await wrapper.get('[data-testid="target-HPM5300"]').trigger('click')
    await chooseFirmware(wrapper)
    await wrapper.get('[data-testid="bin-base"]').setValue('0x80000000')
    await wrapper.get('[data-testid="inspect-image"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.get('[data-testid="start-job"]').attributes('disabled')).toBeUndefined())
    await wrapper.get('[data-testid="start-job"]').trigger('click')
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const source = FakeEventSource.instances[0]
    const log = { job_id: 'job-1', sequence: 1, timestamp: 1, event: 'log', message: 'programming', state: null, progress: null }

    expect(source.url).toContain('after=0')
    source.emit('log', log)
    source.emit('log', log)
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('[data-testid="log-line"]').filter(line => line.text().includes('programming'))).toHaveLength(1)

    source.emitNativeError()
    await wrapper.vm.$nextTick()
    await wrapper.get('[data-testid="reconnect-stream"]').trigger('click')
    expect(FakeEventSource.instances[1].url).toContain('after=1')
    wrapper.unmount()
  })

  it('makes a server-named SSE error reconnectable from the last sequence', async () => {
    const wrapper = mount(await onlineFlashView())
    await readyAndStart(wrapper)
    const source = FakeEventSource.instances[0]
    source.emit('log', { job_id: 'job-1', sequence: 7, timestamp: 1, event: 'log', message: 'checkpoint', state: null, progress: null })
    source.emit('error', { code: 'BACKEND_LOST', message: 'worker stream ended' })
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('BACKEND_LOST')
    await wrapper.get('[data-testid="reconnect-stream"]').trigger('click')
    expect(FakeEventSource.instances[1].url).toContain('after=7')
    wrapper.unmount()
  })

  it('keeps the newest viewport rows when preview requests resolve out of order', async () => {
    const fallback = viewFetch()
    let resolveOld!: (response: Response) => void
    let resolveNew!: (response: Response) => void
    const oldPage = new Promise<Response>(resolve => { resolveOld = resolve })
    const newPage = new Promise<Response>(resolve => { resolveNew = resolve })
    const previewResponse = (character: string, address: number) => new Response(JSON.stringify({
      address, length: 4096, data_base64: btoa(character.repeat(4096)), present: Array(4096).fill(true),
    }), { status: 200 })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/images/inspect')) return Promise.resolve(new Response(JSON.stringify({
        image_id: 'large-image', file_name: 'firmware.bin', format: 'bin', size: 16384,
        sha256: 'large', start: 0x80000000, end: 0x80004000,
        segments: [{ start: 0x80000000, end: 0x80004000 }], base_address: 0x80000000,
      }), { status: 200 }))
      if (url.includes('/preview?')) {
        const offset = Number(new URL(url, 'http://local').searchParams.get('offset'))
        if (offset === 0) return Promise.resolve(previewResponse('A', 0x80000000))
        if (offset === 4096) return oldPage
        if (offset === 8192) return newPage
      }
      return fallback(input, options)
    }))
    const wrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
    await wrapper.get('[data-testid="target-HPM5300"]').trigger('click')
    await chooseFirmware(wrapper)
    await wrapper.get('[data-testid="inspect-image"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('AAAAAAAA'))
    const scroller = wrapper.get('.hex-scroll')
    Object.defineProperty(scroller.element, 'clientHeight', { configurable: true, value: 200 })
    Object.defineProperty(scroller.element, 'scrollTop', { configurable: true, writable: true, value: 6000 })
    await scroller.trigger('scroll')
    ;(scroller.element as HTMLElement).scrollTop = 12000
    await scroller.trigger('scroll')

    resolveNew(previewResponse('N', 0x80002000))
    await vi.waitFor(() => expect(wrapper.text()).toContain('NNNNNNNN'))
    resolveOld(previewResponse('O', 0x80001000))
    for (let index = 0; index < 100; index += 1) await Promise.resolve()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('NNNNNNNN')
    expect(wrapper.text()).not.toContain('OOOOOOOO')
    wrapper.unmount()
  })

  it('submits canonical actions and keeps connect/disconnect mandatory', async () => {
    const wrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
    await wrapper.get('[data-testid="target-HPM5300"]').trigger('click')
    await chooseFirmware(wrapper)
    await wrapper.get('[data-testid="inspect-image"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.get('[data-testid="start-job"]').attributes('disabled')).toBeUndefined())
    const choices = wrapper.findAll('.action-choices label')
    expect(choices[0].get('input').attributes('disabled')).toBeDefined()
    expect(choices.at(-1)?.get('input').attributes('disabled')).toBeDefined()
    await choices[1].get('input').setValue(false)
    await choices[3].get('input').setValue(false)
    await choices[1].get('input').setValue(true)
    await choices[3].get('input').setValue(true)
    await wrapper.get('[data-testid="start-job"]').trigger('click')
    await vi.waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/jobs'))).toBe(true))
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith('/jobs'))

    expect(JSON.parse(String(call?.[1]?.body)).actions).toEqual(['connect', 'erase', 'program', 'verify', 'reset', 'disconnect'])
    wrapper.unmount()
  })

  it('does not let a late stop response overwrite an SSE success terminal', async () => {
    const fallback = viewFetch()
    let resolveStop!: (response: Response) => void
    const pendingStop = new Promise<Response>(resolve => { resolveStop = resolve })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => (
      String(input).endsWith('/jobs/job-1/stop') ? pendingStop : fallback(input, options)
    )))
    const wrapper = mount(await onlineFlashView())
    await readyAndStart(wrapper)
    await wrapper.get('[data-testid="stop-job"]').trigger('click')
    FakeEventSource.instances[0].emit('state', {
      job_id: 'job-1', sequence: 9, timestamp: 2, event: 'state', message: '', state: 'succeeded', progress: 1,
    })
    await vi.waitFor(() => expect(wrapper.get('[data-testid="job-state"]').text()).toContain('SUCCEEDED'))
    resolveStop(new Response(JSON.stringify({ state: 'stopped', job_id: 'job-1' }), { status: 200 }))
    for (let index = 0; index < 10; index += 1) await Promise.resolve()
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-testid="job-state"]').text()).toContain('SUCCEEDED')
    expect(wrapper.find('.waiting').exists()).toBe(false)
    wrapper.unmount()
  })

  it('restores the previous job state after a failed stop so stop can be retried', async () => {
    const fallback = viewFetch()
    let stopAttempts = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).endsWith('/jobs/job-1/stop')) {
        stopAttempts += 1
        return Promise.resolve(new Response(JSON.stringify({ detail: 'stop failed' }), { status: 500, statusText: 'fail' }))
      }
      return fallback(input, options)
    }))
    const wrapper = mount(await onlineFlashView())
    await readyAndStart(wrapper)
    await wrapper.get('[data-testid="stop-job"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.get('[data-testid="job-state"]').text()).toContain('QUEUED'))
    expect(wrapper.get('[data-testid="stop-job"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="stop-job"]').trigger('click')
    await vi.waitFor(() => expect(stopAttempts).toBe(2))
    wrapper.unmount()
  })

  it('uses a synchronous creating-job latch for normal and chip-erase starts', async () => {
    const fallback = viewFetch()
    let resolveJob!: (response: Response) => void
    const pendingJob = new Promise<Response>(resolve => { resolveJob = resolve })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => (
      String(input).endsWith('/jobs') && options?.method === 'POST' ? pendingJob : fallback(input, options)
    )))
    const wrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
    await wrapper.get('[data-testid="target-HPM5300"]').trigger('click')
    await chooseFirmware(wrapper)
    await wrapper.get('[data-testid="inspect-image"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.get('[data-testid="start-job"]').attributes('disabled')).toBeUndefined())
    const start = wrapper.get('[data-testid="start-job"]')
    await start.trigger('click'); await start.trigger('click')
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/jobs'))).toHaveLength(1)
    expect(start.attributes('disabled')).toBeDefined()
    resolveJob(new Response(JSON.stringify({ job_id: 'job-1', job: { state: 'queued' } }), { status: 200 }))
    wrapper.unmount()

    let resolveErase!: (response: Response) => void
    const pendingErase = new Promise<Response>(resolve => { resolveErase = resolve })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, options?: RequestInit) => (
      String(input).endsWith('/jobs') && options?.method === 'POST' ? pendingErase : fallback(input, options)
    )))
    FakeEventSource.instances = []
    const eraseWrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(eraseWrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
    await eraseWrapper.get('[data-testid="target-HPM5300"]').trigger('click')
    const chipErase = eraseWrapper.get('[data-testid="chip-erase"]')
    await chipErase.trigger('click'); await chipErase.trigger('click')
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/jobs'))).toHaveLength(1)
    resolveErase(new Response(JSON.stringify({ job_id: 'erase', job: { state: 'queued' } }), { status: 200 }))
    eraseWrapper.unmount()
  })

  it('survives localStorage quota errors and reports a non-sensitive warning', async () => {
    vi.stubGlobal('localStorage', {
      getItem: () => null,
      setItem: () => { throw new DOMException('quota details', 'QuotaExceededError') },
    })
    const wrapper = mount(await onlineFlashView())
    await wrapper.get('[data-testid="frequency"]').setValue('4000000')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('本地设置未保存')
    expect(wrapper.text()).not.toContain('quota details')
    expect(wrapper.get('[data-testid="frequency"]').element).toHaveProperty('value', '4000000')
    wrapper.unmount()
  })

  it('does not mirror total job progress into stage progress', async () => {
    const wrapper = mount(await onlineFlashView())
    await readyAndStart(wrapper)
    FakeEventSource.instances[0].emit('progress', {
      job_id: 'job-1', sequence: 3, timestamp: 2, event: 'progress', message: '', state: 'programming', progress: 0.4,
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-testid="total-progress"]').attributes('value')).toBe('0.4')
    expect(wrapper.get('[data-testid="stage-progress"]').attributes('value')).toBe('1')
    FakeEventSource.instances[0].emit('state', {
      job_id: 'job-1', sequence: 4, timestamp: 3, event: 'state', message: '', state: 'verifying', progress: null,
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-testid="stage-progress"]').attributes('value')).toBe('0')
    wrapper.unmount()
  })

  it('shows STOPPING and waits for a terminal event after stop', async () => {
    const wrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
    await wrapper.get('[data-testid="target-HPM5300"]').trigger('click')
    await chooseFirmware(wrapper)
    await wrapper.get('[data-testid="bin-base"]').setValue('0x80000000')
    await wrapper.get('[data-testid="inspect-image"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.get('[data-testid="start-job"]').attributes('disabled')).toBeUndefined())
    await wrapper.get('[data-testid="start-job"]').trigger('click')
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))

    await wrapper.get('[data-testid="stop-job"]').trigger('click')
    expect(wrapper.get('[data-testid="job-state"]').text()).toContain('STOPPING')
    expect(wrapper.text()).toContain('等待探针安全停止')
    expect(wrapper.get('[data-testid="stop-job"]').attributes('disabled')).toBeDefined()
    expect(FakeEventSource.instances[0].closed).toBe(false)

    FakeEventSource.instances[0].emit('state', {
      job_id: 'job-1', sequence: 2, timestamp: 2, event: 'state', message: '', state: 'stopped', progress: 1,
    })
    await vi.waitFor(() => expect(wrapper.get('[data-testid="job-state"]').text()).toContain('已停止'))
    wrapper.unmount()
  })

  it('persists settings but never File data or an opaque image snapshot', async () => {
    const wrapper = mount(await onlineFlashView())
    await wrapper.get('[data-testid="frequency"]').setValue('4000000')
    await chooseFirmware(wrapper)
    const stored = localStorage.getItem('mklink.onlineFlash.settings') ?? ''

    expect(stored).toContain('4000000')
    expect(stored).not.toContain('firmware')
    expect(stored).not.toContain('image_id')
    wrapper.unmount()
  })

  it('requires explicit confirmation for chip erase and keeps sectors disabled without reliable geometry', async () => {
    const wrapper = mount(await onlineFlashView())
    await vi.waitFor(() => expect(wrapper.find('[data-testid="target-HPM5300"]').exists()).toBe(true))
    await wrapper.get('[data-testid="target-HPM5300"]').trigger('click')
    await wrapper.get('[data-testid="chip-erase"]').trigger('click')

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('全片擦除'))
    expect(wrapper.get('[data-testid="select-all-sectors"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="range-erase"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('扇区几何信息不可验证')
    wrapper.unmount()
  })
})

describe('online flash component quality', () => {
  it('virtualizes 5000 log lines and can scroll from early to middle history', async () => {
    const lines = Array.from({ length: 5000 }, (_, index) => `line-${index}`)
    const wrapper = mount(FlashLogPanel, { props: { lines, streamDisconnected: false } })
    const viewport = wrapper.get('[data-testid="log-viewport"]')
    Object.defineProperty(viewport.element, 'clientHeight', { configurable: true, value: 135 })
    expect(wrapper.findAll('[data-testid="log-line"]').length).toBeLessThan(40)
    expect(wrapper.text()).toContain('line-0')
    ;(viewport.element as HTMLElement).scrollTop = 2500 * 18
    await viewport.trigger('scroll')
    expect(wrapper.text()).toContain('line-2500')
    expect(wrapper.findAll('[data-testid="log-line"]').length).toBeLessThan(40)
  })

  it('opens the visually hidden file input from a keyboard-focusable trigger', async () => {
    const wrapper = mount(FirmwareWorkspace, { props: {
      file: null, baseAddress: '', baseError: '', inspection: null, rows: [],
      paddingTop: 0, paddingBottom: 0, loading: false, error: '',
    } })
    const input = wrapper.get('[data-testid="firmware-input"]')
    const click = vi.spyOn(input.element as HTMLInputElement, 'click')
    const trigger = wrapper.get('[data-testid="firmware-trigger"]')
    expect(trigger.attributes('tabindex')).toBe('0')
    expect(input.classes()).toContain('visually-hidden')
    await trigger.trigger('keydown', { key: 'Enter' })
    expect(click).toHaveBeenCalledTimes(1)
  })

  it('wraps the action bar controls for narrow layouts', () => {
    expect(actionBarSource).toContain('flex-wrap:wrap')
    expect(actionBarSource).toContain('max-width:100%')
  })
})
