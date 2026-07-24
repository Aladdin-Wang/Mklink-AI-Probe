import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import VersionHistoryPopover from './VersionHistoryPopover.vue'

describe('VersionHistoryPopover', () => {
  it('shows the current release notes and stable release history', async () => {
    const wrapper = mount(VersionHistoryPopover, {
      props: { version: '0.1.3', buildCommit: 'f9f2f70' },
      attachTo: document.body,
    })

    expect(wrapper.get('[data-testid="app-version"]').text()).toContain('v0.1.3 · f9f2f70')
    expect(wrapper.find('[data-testid="version-history-panel"]').exists()).toBe(false)

    await wrapper.trigger('mouseenter')

    const panel = wrapper.get('[data-testid="version-history-panel"]')
    expect(panel.text()).toContain('版本更新')
    expect(panel.text()).toContain('修复符号解析并完善调试资源协同')
    expect(panel.text()).toContain('匿名 struct/union 成员展开')
    expect(panel.text()).toContain('AI Skill 主动版本提醒')
    expect(wrapper.findAll('[data-testid="release-entry"]')).toHaveLength(4)
    expect(wrapper.get('.release-entry.current').text()).toContain('v0.1.3')
    expect(wrapper.get('.current-badge').text()).toBe('当前版本')
    wrapper.unmount()
  })

  it('pins on click and closes on a second click or Escape', async () => {
    const wrapper = mount(VersionHistoryPopover, {
      props: { version: '0.1.3', buildCommit: 'f9f2f70' },
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
      props: { version: '0.1.3', buildCommit: 'f9f2f70' },
      attachTo: document.body,
    })

    await wrapper.get('[data-testid="app-version"]').trigger('click')
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="version-history-panel"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
