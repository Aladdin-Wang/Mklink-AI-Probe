import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppUpdateBanner from './AppUpdateBanner.vue'

describe('AppUpdateBanner', () => {
  it('shows background download progress without blocking the application', () => {
    const wrapper = mount(AppUpdateBanner, {
      props: { state: 'downloading', version: '0.2.0', progress: 0.42, error: '' },
    })

    expect(wrapper.get('[data-testid="update-banner"]').text()).toContain('正在下载 v0.2.0')
    expect(wrapper.get('progress').attributes('value')).toBe('0.42')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('offers installation only after the update is ready', async () => {
    const wrapper = mount(AppUpdateBanner, {
      props: { state: 'ready', version: '0.2.0', progress: 1, error: '' },
    })

    await wrapper.get('[data-testid="install-update"]').trigger('click')
    expect(wrapper.emitted('install')).toHaveLength(1)
  })

  it('offers retry after an update error', async () => {
    const wrapper = mount(AppUpdateBanner, {
      props: { state: 'error', version: '', progress: null, error: 'network unavailable' },
    })

    expect(wrapper.text()).toContain('network unavailable')
    await wrapper.get('[data-testid="retry-update"]').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })
})
