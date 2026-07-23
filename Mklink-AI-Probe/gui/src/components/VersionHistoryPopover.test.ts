import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import VersionHistoryPopover from './VersionHistoryPopover.vue'

describe('VersionHistoryPopover', () => {
  it('shows the current release notes and stable release history', async () => {
    const wrapper = mount(VersionHistoryPopover, {
      props: { version: '0.1.2', buildCommit: '8a8a227' },
      attachTo: document.body,
    })

    expect(wrapper.get('[data-testid="app-version"]').text()).toContain('v0.1.2 · 8a8a227')
    expect(wrapper.find('[data-testid="version-history-panel"]').exists()).toBe(false)

    await wrapper.trigger('mouseenter')

    expect(wrapper.get('[data-testid="version-history-panel"]').text()).toContain('版本更新')
    expect(wrapper.get('[data-testid="version-history-panel"]').text()).toContain('Web 调试交互')
    expect(wrapper.findAll('[data-testid="release-entry"]')).toHaveLength(3)
    wrapper.unmount()
  })

  it('pins on click and closes on a second click or Escape', async () => {
    const wrapper = mount(VersionHistoryPopover, {
      props: { version: '0.1.2', buildCommit: '8a8a227' },
      attachTo: document.body,
    })
    const trigger = wrapper.get('[data-testid="app-version"]')

    await trigger.trigger('click')
    await wrapper.trigger('mouseleave')
    expect(wrapper.find('[data-testid="version-history-panel"]').exists()).toBe(true)
    expect(trigger.attributes('aria-expanded')).toBe('true')

    await trigger.trigger('click')
    expect(wrapper.find('[data-testid="version-history-panel"]').exists()).toBe(false)

    await trigger.trigger('click')
    await document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="version-history-panel"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('closes a pinned history panel when the user clicks outside', async () => {
    const wrapper = mount(VersionHistoryPopover, {
      props: { version: '0.1.2', buildCommit: '8a8a227' },
      attachTo: document.body,
    })

    await wrapper.get('[data-testid="app-version"]').trigger('click')
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="version-history-panel"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
