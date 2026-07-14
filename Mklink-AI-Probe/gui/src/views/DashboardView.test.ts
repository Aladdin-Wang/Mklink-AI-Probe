import { shallowMount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { readFileSync } from 'node:fs'
import DashboardView from './DashboardView.vue'

const routerMock = vi.hoisted(() => ({
  query: {} as Record<string, string>,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: routerMock.query }),
}))

vi.mock('../composables/useMklinkApi', () => ({
  useMklinkApi: () => ({
    deviceStatus: reactive({ connected: true }),
    flashDevice: vi.fn(),
    resetDevice: vi.fn(),
    eraseDevice: vi.fn(),
    haltDevice: vi.fn(),
    resumeDevice: vi.fn(),
  }),
}))

vi.mock('../composables/useToast', () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  }),
}))

vi.mock('../composables/useResourceStatus', () => ({
  useResourceStatus: () => ({
    refresh: vi.fn(),
    getBridgeOwner: () => '',
  }),
}))

const dashStub = { template: '<div />', props: ['deviceConnected'] }

describe('DashboardView layout classes', () => {
  afterEach(() => {
    routerMock.query = {}
  })

  it('does not use the full-screen clipped card layout for RTOS Trace', async () => {
    const wrapper = shallowMount(DashboardView, {
      global: {
        stubs: {
          RttViewTab: dashStub,
          HardFaultTab: dashStub,
          SymbolsTab: dashStub,
          MemoryTab: dashStub,
          SuperWatchTab: dashStub,
          SerialMonitorTab: dashStub,
          ModbusTab: dashStub,
          VofaTab: dashStub,
          SystemViewTab: { template: '<div class="sv-tab" />', props: ['deviceConnected'] },
        },
      },
    })

    const systemViewTab = wrapper.findAll('button').find(button => button.text() === 'RTOS Trace')
    expect(systemViewTab).toBeTruthy()
    await systemViewTab!.trigger('click')

    const cardClasses = wrapper.get('.card').classes()
    expect(cardClasses).toContain('card-systemview')
    expect(cardClasses).not.toContain('card-full')
  })

  it('keeps the RTOS Trace card scrollable when content is taller than the viewport', () => {
    const source = readFileSync('src/views/DashboardView.vue', 'utf8')

    expect(source).toMatch(/\.dash-root\s*\{[^}]*min-height:\s*0/s)
    expect(source).toMatch(/\.card-systemview\s*\{[^}]*flex:\s*1\s+1\s+auto/s)
    expect(source).toMatch(/\.card-systemview\s*\{[^}]*min-height:\s*0/s)
    expect(source).toMatch(/\.card-systemview\s*\{[^}]*max-height:\s*100%/s)
    expect(source).toMatch(/\.card-systemview\s*\{[^}]*overflow-y:\s*auto/s)
    expect(source).toMatch(/\.card-systemview\s*\{[^}]*scrollbar-gutter:\s*stable/s)
    expect(source).not.toMatch(/\.card-systemview\s*\{[^}]*calc\(100vh/s)
  })

  it('does not trap ordinary wheel scrolling inside the SystemView timeline', () => {
    const source = readFileSync('src/components/dash/SystemViewTab.vue', 'utf8')

    expect(source).toMatch(/\.sv-canvas-wrap\s*\{[^}]*overflow:\s*visible/s)
    expect(source).not.toMatch(/\.sv-canvas-wrap\s*\{[^}]*overflow:\s*auto/s)
  })

  it('lets the SystemView timeline reserve enough height for CPU bars', () => {
    const source = readFileSync('src/components/dash/SystemViewTab.vue', 'utf8')

    expect(source).toMatch(/\.sv-gantt-section\s*\{[^}]*flex:\s*0\s+0\s+auto/s)
  })

  it('keeps live SystemView legend and CPU rows from changing the page height', () => {
    const source = readFileSync('src/components/dash/SystemViewTab.vue', 'utf8')

    expect(source).toMatch(/\.sv-legend\s*\{[^}]*height:\s*28px/s)
    expect(source).toMatch(/\.sv-legend\s*\{[^}]*overflow-y:\s*auto/s)
    expect(source).toMatch(/\.sv-vcpu\s*\{[^}]*height:\s*96px/s)
    expect(source).toMatch(/\.sv-vcpu\s*\{[^}]*overflow-y:\s*auto/s)
  })

  it('uses the binary SystemView stream with bounded render and table cadences', () => {
    const source = readFileSync('src/components/dash/SystemViewTab.vue', 'utf8')

    expect(source).toMatch(/useBinaryStream\('systemview'/)
    expect(source).toMatch(/new RenderScheduler/)
    expect(source).toMatch(/TABLE_UPDATE_INTERVAL_MS\s*=\s*200/)
    expect(source).not.toMatch(/passthroughEvents:\s*\['status',\s*'batch'\]/)
    expect(source).not.toMatch(/pendingLiveEvents/)
    expect(source).toContain('dp.isr_names')
    expect(source).toContain('isr_name:')
    expect(source).toMatch(/event\.kind === 'task_info'/)
  })

  it('can open directly on the RTOS Trace tab from the route query', () => {
    routerMock.query = { tab: 'systemview' }

    const wrapper = shallowMount(DashboardView, {
      global: {
        stubs: {
          RttViewTab: dashStub,
          HardFaultTab: dashStub,
          SymbolsTab: dashStub,
          MemoryTab: dashStub,
          SuperWatchTab: dashStub,
          SerialMonitorTab: dashStub,
          ModbusTab: dashStub,
          VofaTab: dashStub,
          SystemViewTab: { template: '<div class="sv-tab" />', props: ['deviceConnected'] },
        },
      },
    })

    expect(wrapper.get('.card').classes()).toContain('card-systemview')
  })

  it('can open directly on the SuperWatch tab from the route query', () => {
    routerMock.query = { tab: 'superwatch' }

    const wrapper = shallowMount(DashboardView, {
      global: {
        stubs: {
          RttViewTab: dashStub,
          HardFaultTab: dashStub,
          SymbolsTab: dashStub,
          MemoryTab: dashStub,
          SuperWatchTab: { template: '<div class="superwatch-route-probe" />', props: ['deviceConnected'] },
          SerialMonitorTab: dashStub,
          ModbusTab: dashStub,
          VofaTab: dashStub,
          SystemViewTab: dashStub,
        },
      },
    })

    expect(wrapper.find('.superwatch-route-probe').exists()).toBe(true)
  })

  it('reconnects SystemView control and binary streams when opening a running trace', () => {
    const source = readFileSync('src/components/dash/SystemViewTab.vue', 'utf8')

    expect(source).toContain('async function reconnectRunningTrace')
    expect(source).toContain('dash.getStatus()')
    expect(source).toMatch(/if\s*\(status\?\.running\)/)
    expect(source).toContain('connectStatus()')
    expect(source).toContain('binaryStream.start()')
  })

  it('stops both SystemView transports when the tab unmounts', () => {
    const source = readFileSync('src/components/dash/SystemViewTab.vue', 'utf8')
    const cleanup = source.slice(source.indexOf('onUnmounted(() => {'), source.indexOf('\n})', source.indexOf('onUnmounted(() => {')))

    expect(cleanup).toContain('disconnectStatus()')
    expect(cleanup).toContain('binaryStream.stop()')
    expect(cleanup).toContain('cancelPendingConnect()')
    expect(cleanup).toContain('renderScheduler?.dispose()')
    expect(cleanup).toContain('tlInstance?.destroy()')
  })
})
