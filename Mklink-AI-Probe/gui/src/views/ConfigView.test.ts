import { flushPromises, mount } from '@vue/test-utils'
import { readonly, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const deviceStatus = {
    connected: false,
    state: 'disconnected',
    mcu: null,
    idcode: null,
    port: null,
    axf: { loaded: false },
  }

  return {
    deviceStatus,
    api: {
      listPorts: vi.fn(),
      discoverPort: vi.fn(),
      getConfig: vi.fn(),
      updateConfig: vi.fn(),
      connectDevice: vi.fn(),
      disconnectDevice: vi.fn(),
      parseAxf: vi.fn(),
      probeFirmwareCheck: vi.fn(),
    },
    wsConnect: vi.fn(),
    wsDisconnect: vi.fn(),
    toastError: vi.fn(),
    toastSuccess: vi.fn(),
    loadDesktopSettings: vi.fn(),
    saveDesktopSettings: vi.fn(),
    pickSymbolFile: vi.fn(),
    pickMapFile: vi.fn(),
  }
})

vi.mock('../composables/useMklinkApi', () => ({
  useMklinkApi: () => ({ deviceStatus: readonly(ref(mocks.deviceStatus)), ...mocks.api }),
}))

vi.mock('../composables/useMklinkWs', () => ({
  useMklinkWs: () => ({
    wsConnected: ref(false),
    connect: mocks.wsConnect,
    disconnect: mocks.wsDisconnect,
  }),
}))

vi.mock('../composables/useToast', () => ({
  useToast: () => ({ error: mocks.toastError, success: mocks.toastSuccess }),
}))

vi.mock('../lib/desktopSettings', () => ({
  loadDesktopSettings: mocks.loadDesktopSettings,
  saveDesktopSettings: mocks.saveDesktopSettings,
}))

vi.mock('../lib/filePicker', () => ({
  pickSymbolFile: mocks.pickSymbolFile,
  pickMapFile: mocks.pickMapFile,
}))

async function mountView() {
  const { default: ConfigView } = await import('./ConfigView.vue')
  const wrapper = mount(ConfigView, {
    global: {
      stubs: {
        FirmwareUpdateModal: true,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('ConfigView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.assign(mocks.deviceStatus, {
      connected: false,
      state: 'disconnected',
      mcu: null,
      idcode: null,
      port: null,
      axf: { loaded: false },
    })
    mocks.api.listPorts.mockResolvedValue([
      { device: 'COM8', description: 'MKLink', manufacturer: 'MicroLink', vid: 1, pid: 2 },
    ])
    mocks.api.discoverPort.mockResolvedValue({ port: 'COM8' })
    mocks.api.getConfig.mockResolvedValue({ com_port: 'COM7', swd_clock: '2000000' })
    mocks.api.updateConfig.mockResolvedValue({})
    mocks.api.connectDevice.mockResolvedValue({})
    mocks.api.disconnectDevice.mockResolvedValue(undefined)
    mocks.api.parseAxf.mockResolvedValue({ loaded: true, variable_count: 3 })
    mocks.api.probeFirmwareCheck.mockResolvedValue({ status: 'ok' })
    mocks.loadDesktopSettings.mockReturnValue({
      version: 1,
      symbolPath: 'C:\\saved\\app.axf',
      mapPath: 'C:\\saved\\app.map',
      rttAddress: '',
      transmitMode: 'text',
      lineEnding: '',
      sendHistory: [],
    })
    mocks.pickSymbolFile.mockResolvedValue(null)
    mocks.pickMapFile.mockResolvedValue(null)
    vi.spyOn(window, 'open').mockImplementation(() => null)
  })

  it('renders one four-section workspace with Local Device selected by default', async () => {
    const wrapper = await mountView()

    expect(wrapper.findAll('[data-testid="config-section"]')).toHaveLength(4)
    expect(wrapper.get('[data-testid="config-section-local"]').attributes('aria-current')).toBe('page')
    expect(wrapper.get('[data-testid="local-device-panel"]').exists()).toBe(true)

    const text = wrapper.text()
    expect(text).not.toContain('项目概览')
    expect(text).not.toContain('最近项目')
    expect(text).not.toContain('MCU 类型')
    expect(text).not.toContain('MCU 提示')
    expect(text).not.toContain('高级配置 (RTT)')
  })

  it('connects locally with the configured port and saved AXF path without an MCU hint', async () => {
    const wrapper = await mountView()

    await wrapper.get('[data-testid="connect-local"]').trigger('click')
    await flushPromises()

    expect(mocks.api.connectDevice).toHaveBeenCalledWith({
      port: 'COM7',
      axf: 'C:\\saved\\app.axf',
    })
    expect(mocks.api.connectDevice.mock.calls[0][0]).not.toHaveProperty('mcu')
  })

  it('keeps serial discovery, refresh, SWD saving, disconnect, and device status in Local Device', async () => {
    const wrapper = await mountView()

    await wrapper.get('[data-testid="auto-port"]').trigger('click')
    await wrapper.get('[data-testid="swd-clock"]').setValue('4000000')
    await wrapper.get('[data-testid="save-local"]').trigger('click')
    await flushPromises()

    expect(mocks.api.discoverPort).toHaveBeenCalledOnce()
    expect(mocks.api.updateConfig).toHaveBeenCalledWith(expect.objectContaining({
      com_port: 'COM8',
      swd_clock: '4000000',
    }))
    expect(wrapper.get('[data-testid="device-status"]').text()).toContain('未连接')
    expect(wrapper.get('[data-testid="disconnect-local"]').attributes('disabled')).toBeDefined()
  })

  it('restores, browses, and saves independently editable AXF/ELF and MAP paths', async () => {
    const wrapper = await mountView()
    await wrapper.get('[data-testid="config-section-files"]').trigger('click')

    expect(wrapper.get<HTMLInputElement>('[data-testid="symbol-path"]').element.value)
      .toBe('C:\\saved\\app.axf')
    expect(wrapper.get<HTMLInputElement>('[data-testid="map-path"]').element.value)
      .toBe('C:\\saved\\app.map')

    mocks.pickSymbolFile.mockResolvedValueOnce('D:\\build\\next.elf')
    await wrapper.get('[data-testid="browse-symbol"]').trigger('click')
    await flushPromises()
    expect(wrapper.get<HTMLInputElement>('[data-testid="symbol-path"]').element.value)
      .toBe('D:\\build\\next.elf')

    await wrapper.get('[data-testid="map-path"]').setValue('D:\\build\\next.map')
    await wrapper.get('[data-testid="browse-map"]').trigger('click')
    await wrapper.get('[data-testid="save-files"]').trigger('click')

    expect(mocks.saveDesktopSettings).toHaveBeenCalledWith(
      window.localStorage,
      expect.objectContaining({
        symbolPath: 'D:\\build\\next.elf',
        mapPath: 'D:\\build\\next.map',
      }),
    )
  })

  it('parses the saved AXF path when a device is connected', async () => {
    Object.assign(mocks.deviceStatus, { connected: true, state: 'halted' })
    const wrapper = await mountView()
    await wrapper.get('[data-testid="config-section-files"]').trigger('click')

    expect(wrapper.get('[data-testid="parse-symbols"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="parse-symbols"]').trigger('click')
    await flushPromises()

    expect(mocks.api.parseAxf).toHaveBeenCalledWith('C:\\saved\\app.axf')
    expect(mocks.toastSuccess).toHaveBeenCalledWith(expect.stringContaining('3'))
  })

  it('keeps remote connection and service launch controls reachable', async () => {
    const wrapper = await mountView()

    await wrapper.get('[data-testid="config-section-remote"]').trigger('click')
    await wrapper.get('[data-testid="remote-url"]').setValue('ws://10.0.0.5:8765')
    await wrapper.get('[data-testid="remote-token"]').setValue('secret')
    await wrapper.get('[data-testid="connect-remote"]').trigger('click')
    expect(mocks.wsConnect).toHaveBeenCalledWith('secret', 'ws://10.0.0.5:8765')

    await wrapper.get('[data-testid="config-section-serve"]').trigger('click')
    await wrapper.get('[data-testid="serve-host"]').setValue('0.0.0.0')
    await wrapper.get('[data-testid="serve-port"]').setValue('9000')
    await wrapper.get('[data-testid="launch-server"]').trigger('click')
    expect(window.open).toHaveBeenCalledWith('http://0.0.0.0:9000/docs', '_blank')
  })

  it('preserves the probe firmware upgrade warning', async () => {
    mocks.api.probeFirmwareCheck.mockResolvedValue({
      status: 'upgrade_required',
      instructions: 'upgrade',
      firmware_dir: 'C:\\firmware',
      recommended_uf2: null,
      all_uf2s: [],
    })

    const wrapper = await mountView()

    expect(wrapper.get('[data-testid="firmware-warning"]').text()).toContain('探针固件需要升级')
  })
})
