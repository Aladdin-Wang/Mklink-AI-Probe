import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, it, expect, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ device: null as any }))
vi.mock('../composables/useMklinkApi', () => ({ useMklinkApi: () => ({ deviceStatus: mocks.device }) }))
vi.mock('../composables/useBackendHealth', () => ({ useBackendHealth: () => ({ backendState: 'alive', backendPort: 8766, isTauri: false }) }))
vi.mock('../composables/useLanguage', () => ({ tr: (zh: string) => zh }))
import StatusBar from './StatusBar.vue'

describe('probe recovery status', () => {
  it('shows connection state and IDCODE without the detected MCU family label', () => {
    mocks.device = ref({ connected: true, state: 'connected', mcu: 'STM32F10x', idcode: '0x1ba01477' })
    const wrapper = mount(StatusBar)
    expect(wrapper.text()).toContain('已连接')
    expect(wrapper.text()).toContain('0x1ba01477')
    expect(wrapper.text()).toContain('后端正常 · 8766')
    expect(wrapper.text()).not.toContain('STM32F10x')
    wrapper.unmount()
  })
  it.each([
    ['waiting', false, '等待下载器恢复'],
    ['reconnecting', false, '正在恢复连接'],
    ['failed', false, '恢复失败，请重新连接'],
    ['expired', false, '已断开'],
    ['restored', true, '已连接'],
  ])('%s', (state, connected, label) => {
    mocks.device = ref({ connected, connection_recovery: { state } })
    const wrapper = mount(StatusBar)
    expect(wrapper.text()).toContain(label)
    wrapper.unmount()
  })
  it('distinguishes restored USB from capture requiring manual reload', () => {
    mocks.device = ref({ connected: true, connection_recovery: { state: 'restored', errors: ['firmware changed'] } })
    const wrapper = mount(StatusBar)
    expect(wrapper.text()).toContain('连接已恢复，采集待确认')
    expect(wrapper.find('[title]').attributes('title')).toBe('firmware changed')
    wrapper.unmount()
  })
})
