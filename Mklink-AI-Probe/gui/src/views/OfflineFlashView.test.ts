import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import OfflineFlashView from './OfflineFlashView.vue'
import router from '../router'

const offlineMocks = vi.hoisted(() => ({
  getStatus: vi.fn(),
  detectModel: vi.fn(),
  listAlgorithms: vi.fn(),
  preview: vi.fn(),
  deploy: vi.fn(),
  trigger: vi.fn(),
}))

const onlineMocks = vi.hoisted(() => ({
  searchTargets: vi.fn(),
  installPack: vi.fn(),
}))

vi.mock('../composables/useOfflineFlashApi', () => ({
  useOfflineFlashApi: () => offlineMocks,
}))

vi.mock('../composables/useOnlineFlashApi', () => ({
  useOnlineFlashApi: () => onlineMocks,
}))

describe('OfflineFlashView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    offlineMocks.getStatus.mockResolvedValue({
      available: true,
      disk_path: 'TEST_DISK',
      python_dir: 'TEST_DISK/python',
      flm_dir: 'TEST_DISK/FLM',
    })
    offlineMocks.detectModel.mockResolvedValue({ model: 'V3', version: 'V3.3.1' })
    offlineMocks.listAlgorithms.mockResolvedValue([])
    onlineMocks.searchTargets.mockResolvedValue([])
    onlineMocks.installPack.mockResolvedValue({ result: { status: 'installed' }, events: [] })
    offlineMocks.deploy.mockResolvedValue({
      status: 'deployed',
      model: 'V4',
      script_name: 'factory-download.py',
      files: ['python/factory-download.py', 'firmware.hex'],
    })
    offlineMocks.preview.mockResolvedValue({
      model: 'V4',
      script_name: 'factory-download.py',
      script: '# generated preview',
    })
    offlineMocks.trigger.mockResolvedValue({ status: 'completed', lines: ['offline download finished'] })
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  it('registers a top-level offline flash route', () => {
    const route = router.getRoutes().find(candidate => candidate.name === 'offline-flash')
    expect(route?.path).toBe('/offline-flash')
  })

  it('uses cmd.get_version result and forces the V2/V3 script name', async () => {
    const wrapper = mount(OfflineFlashView)
    await flushPromises()

    expect(offlineMocks.detectModel).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('V3.3.1')
    expect(wrapper.text()).toContain('offline_download.py')
    expect(wrapper.get('[data-testid="offline-deploy"]').attributes('disabled')).toBeDefined()
  })

  it('provides multi-file firmware selection and editable BIN address and FLM bases', () => {
    const source = readFileSync('src/views/OfflineFlashView.vue', 'utf8')

    expect(source).toContain('multiple accept=".bin,.hex"')
    expect(source).toContain('v-model="item.base_address"')
    expect(source).toContain('v-model="item.flash_base"')
    expect(source).toContain('v-model="item.ram_base"')
    expect(source).toContain('自动烧录次数')
    expect(source).toContain('SWD 速率')
  })

  it('keeps same-range algorithms from different sources selectable', async () => {
    onlineMocks.searchTargets.mockResolvedValue([{
      part_number: 'DEVICE_A', vendor: 'Vendor', pack_id: 'Vendor.Device_DFP',
      pack_version: '1.0.0', installed: true, source: 'bundle',
    }])
    offlineMocks.listAlgorithms.mockResolvedValue([
      {
        id: 'builtin', file_name: 'Device.FLM',
        flash_base: '0x08000000', ram_base: '0x20000000', source_kind: 'pack',
        source_token: 'catalog:bundle:one', origin: '内置 Pack', available: true, on_probe: false,
      },
      {
        id: 'custom', file_name: 'Device.FLM',
        flash_base: '0x08000000', ram_base: '0x20000000', source_kind: 'pack',
        source_token: 'custom:one', origin: '用户 FLM', available: true, on_probe: false,
      },
    ])
    const wrapper = mount(OfflineFlashView)
    await flushPromises()

    await wrapper.get('.target-result').trigger('click')
    await flushPromises()

    expect(wrapper.findAll('[data-testid="offline-algorithm-row"]')).toHaveLength(2)
    expect(wrapper.text()).toContain('内置 Pack')
    expect(wrapper.text()).toContain('用户 FLM')
  })

  it('triggers the deployed V4 script by its configured file name', async () => {
    offlineMocks.detectModel.mockResolvedValue({ model: 'V4', version: 'V4.3.4' })
    onlineMocks.searchTargets.mockResolvedValue([{
      part_number: 'STM32F103RC', vendor: 'STMicroelectronics', pack_id: 'Keil.STM32F1xx_DFP',
      pack_version: '2.4.1', installed: true, source: 'installed',
    }])
    offlineMocks.listAlgorithms.mockResolvedValue([{
      id: 'profile-stm32f1', file_name: 'STM32F10x_1024.FLM',
      flash_base: '0x08000000', ram_base: '0x20000000', source_kind: 'existing',
      source_token: null, origin: 'MCU profile', available: true, on_probe: true,
    }])
    const wrapper = mount(OfflineFlashView)
    await flushPromises()

    expect(wrapper.get('[data-testid="offline-trigger"]').attributes('disabled')).toBeDefined()
    await wrapper.get('.target-result').trigger('click')
    await flushPromises()
    const input = wrapper.get('input[type="file"][multiple]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['hex'], 'firmware.hex')],
    })
    await input.trigger('change')
    await wrapper.get('[data-testid="offline-deploy"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="offline-trigger"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="offline-trigger"]').trigger('click')
    await flushPromises()

    expect(confirm).not.toHaveBeenCalled()
    expect(offlineMocks.trigger).toHaveBeenCalledWith(
      'V4',
      'factory-download.py',
      expect.any(Function),
    )

    offlineMocks.detectModel.mockResolvedValue({ model: 'V3', version: 'V3.3.1' })
    const detectButton = wrapper.findAll('button').find(button => button.text() === '识别版本')
    await detectButton!.trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="offline-trigger"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('offline_download.py')
  })

  it('generates the preview automatically before deploying', async () => {
    offlineMocks.detectModel.mockResolvedValue({ model: 'V4', version: 'V4.3.4' })
    offlineMocks.preview.mockResolvedValue({
      model: 'V4',
      script_name: 'factory-download.py',
      script: '# generated preview',
    })
    onlineMocks.searchTargets.mockResolvedValue([{
      part_number: 'STM32F103RC', vendor: 'STMicroelectronics', pack_id: 'Keil.STM32F1xx_DFP',
      pack_version: '2.4.1', installed: true, source: 'installed',
    }])
    offlineMocks.listAlgorithms.mockResolvedValue([{
      id: 'profile-stm32f1', file_name: 'STM32F10x_1024.FLM',
      flash_base: '0x08000000', ram_base: '0x20000000', source_kind: 'existing',
      source_token: null, origin: 'MCU profile', available: true, on_probe: true,
    }])
    const wrapper = mount(OfflineFlashView)
    await flushPromises()
    await wrapper.get('.target-result').trigger('click')
    await flushPromises()
    const input = wrapper.get('input[type="file"][multiple]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['hex'], 'firmware.hex')],
    })
    await input.trigger('change')

    await wrapper.get('[data-testid="offline-deploy"]').trigger('click')
    await flushPromises()

    expect(offlineMocks.preview).toHaveBeenCalledOnce()
    expect(offlineMocks.preview.mock.invocationCallOrder[0]).toBeLessThan(
      offlineMocks.deploy.mock.invocationCallOrder[0],
    )
    expect(wrapper.text()).toContain('# generated preview')
  })

  it('renders trigger output while the V4 command is still running', async () => {
    offlineMocks.detectModel.mockResolvedValue({ model: 'V4', version: 'V4.3.4' })
    offlineMocks.preview.mockResolvedValue({
      model: 'V4', script_name: 'factory-download.py', script: '# preview',
    })
    offlineMocks.trigger.mockImplementation(async (_model, _script, onLine) => {
      onLine('erase started')
      await Promise.resolve()
      onLine('program finished')
      return { status: 'completed', lines: ['erase started', 'program finished'] }
    })
    onlineMocks.searchTargets.mockResolvedValue([{
      part_number: 'STM32F103RC', vendor: 'STMicroelectronics', pack_id: 'Keil.STM32F1xx_DFP',
      pack_version: '2.4.1', installed: true, source: 'installed',
    }])
    offlineMocks.listAlgorithms.mockResolvedValue([{
      id: 'profile-stm32f1', file_name: 'STM32F10x_1024.FLM',
      flash_base: '0x08000000', ram_base: '0x20000000', source_kind: 'existing',
      source_token: null, origin: 'MCU profile', available: true, on_probe: true,
    }])
    const wrapper = mount(OfflineFlashView)
    await flushPromises()
    await wrapper.get('.target-result').trigger('click')
    await flushPromises()
    const input = wrapper.get('input[type="file"][multiple]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['hex'], 'firmware.hex')],
    })
    await input.trigger('change')
    await wrapper.get('[data-testid="offline-deploy"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="offline-trigger"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('.trigger-log').text()).toContain('erase started')
    expect(wrapper.get('.trigger-log').text()).toContain('program finished')
  })

  it('configures HPM BIN download without Pack or FLM algorithms', async () => {
    offlineMocks.detectModel.mockResolvedValue({ model: 'V4', version: 'V4.3.4' })
    onlineMocks.searchTargets.mockResolvedValue([{
      part_number: 'HPM5301xEGx', vendor: 'HPMicro', pack_id: null,
      pack_version: null, installed: true, source: 'builtin',
    }])
    const wrapper = mount(OfflineFlashView)
    await flushPromises()

    await wrapper.get('.target-result').trigger('click')
    await flushPromises()
    const input = wrapper.get('input[type="file"][multiple]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['bin'], 'app.bin')],
    })
    await input.trigger('change')
    await wrapper.get('[data-testid="offline-deploy"]').trigger('click')
    await flushPromises()

    expect(onlineMocks.installPack).not.toHaveBeenCalled()
    expect(offlineMocks.listAlgorithms).not.toHaveBeenCalled()
    expect(offlineMocks.deploy).toHaveBeenCalledOnce()
    const payload = offlineMocks.deploy.mock.calls[0][0]
    expect(payload.target_part).toBe('HPM5301xEGx')
    expect(payload.board).toBe('hpm5301evklite')
    expect(payload.algorithms).toEqual([])
    expect(payload.firmwares[0].algorithm_id).toBe('')
    expect(payload.firmwares[0].base_address).toBe('0x80000400')
  })
})
