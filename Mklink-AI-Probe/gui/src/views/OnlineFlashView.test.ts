import { mount, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import App from '../App.vue'
import router from '../router'
import DashboardView from './DashboardView.vue'

async function onlineFlashView() {
  const path = './OnlineFlashView.vue'
  return (await import(/* @vite-ignore */ path)).default
}

async function onlineFlashApi() {
  const path = '../composables/useOnlineFlashApi'
  return (await import(/* @vite-ignore */ path)).useOnlineFlashApi()
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
  readonly listeners = new Map<string, Array<(event: MessageEvent) => void>>()
  closed = false

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this)
  }

  addEventListener(name: string, listener: (event: MessageEvent) => void) {
    const listeners = this.listeners.get(name) ?? []
    listeners.push(listener)
    this.listeners.set(name, listeners)
  }

  emit(name: string, data: unknown) {
    const event = new MessageEvent(name, { data: JSON.stringify(data) })
    for (const listener of this.listeners.get(name) ?? []) listener(event)
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

    const labels = wrapper.findAll('.tab-btn').map(tab => tab.text())
    expect(labels).toContain('脱机烧录')
    expect(labels).not.toContain('烧录')
  })

  it('mounts the stable four-zone workspace landmarks', async () => {
    const wrapper = mount(await onlineFlashView())

    expect(wrapper.get('.online-flash-grid').exists()).toBe(true)
    expect(wrapper.get('aside[data-zone="settings"]').exists()).toBe(true)
    expect(wrapper.get('main[data-zone="firmware"]').exists()).toBe(true)
    expect(wrapper.get('aside[data-zone="flash-map"]').exists()).toBe(true)
    expect(wrapper.get('section[data-zone="logs"]').exists()).toBe(true)
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
  })

  it('subscribes after a sequence, parses named events and can close the stream', async () => {
    const onEvent = vi.fn()
    const subscription = (await onlineFlashApi()).subscribeJob('job/1', 12, onEvent)
    const source = FakeEventSource.instances[0]
    const payload = {
      job_id: 'job/1', sequence: 13, timestamp: 1, event: 'progress', message: '',
      state: null, progress: 0.5,
    }

    expect(source.url).toBe('/api/online-flash/jobs/job%2F1/events?after=12')
    source.emit('progress', payload)
    source.emit('error', { code: 'UNKNOWN_ERROR', message: 'event stream failed' })
    expect(onEvent).toHaveBeenNthCalledWith(1, payload)
    expect(onEvent).toHaveBeenNthCalledWith(2, { code: 'UNKNOWN_ERROR', message: 'event stream failed' })

    subscription.close()
    expect(source.closed).toBe(true)
  })
})
