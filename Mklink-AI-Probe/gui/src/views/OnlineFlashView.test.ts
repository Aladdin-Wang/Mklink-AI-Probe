import { mount, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest'
import { reactive } from 'vue'
import App from '../App.vue'
import router from '../router'
import type { JobAction, JobRequest, PackOperationResponse } from '../types/onlineFlash'
import DashboardView from './DashboardView.vue'

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
