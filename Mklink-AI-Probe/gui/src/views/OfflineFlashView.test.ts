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

  it('only triggers a deployed V4 script after screen-selection confirmation', async () => {
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

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('factory-download.py'))
    expect(offlineMocks.trigger).toHaveBeenCalledOnce()
  })
})
