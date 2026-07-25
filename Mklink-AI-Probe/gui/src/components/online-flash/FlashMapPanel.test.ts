import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FlashMapPanel from './FlashMapPanel.vue'

const baseProps = {
  segments: [],
  sectors: [],
  selectedAddresses: [],
  geometryReliable: false,
  canErase: false,
}

describe('FlashMapPanel', () => {
  it('shows a neutral placeholder before firmware inspection', () => {
    const wrapper = mount(FlashMapPanel, {
      props: { ...baseProps, inspectionReady: false },
    })

    expect(wrapper.text()).toContain('加载固件后显示扇区表')
    expect(wrapper.text()).not.toContain('几何未验证')
    expect(wrapper.text()).not.toContain('扇区几何信息不可验证')
  })

  it('shows the geometry warning only after an inspection lacks sector data', () => {
    const wrapper = mount(FlashMapPanel, {
      props: { ...baseProps, inspectionReady: true },
    })

    expect(wrapper.text()).toContain('几何未验证')
    expect(wrapper.text()).toContain('扇区几何信息不可验证')
  })
})
