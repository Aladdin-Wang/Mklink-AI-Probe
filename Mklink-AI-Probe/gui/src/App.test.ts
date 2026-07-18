import { shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import App from './App.vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ name: 'dashboard' }),
}))

vi.mock('./composables/useMklinkApi', () => ({
  useMklinkApi: () => ({ startStatusPolling: vi.fn(), stopStatusPolling: vi.fn() }),
}))

vi.mock('./composables/useBackendHealth', () => ({
  useBackendHealth: () => ({
    backendAlive: ref(true),
    startHealthPolling: vi.fn(),
    stopHealthPolling: vi.fn(),
  }),
}))

describe('App version footer', () => {
  it('shows the release candidate and source build in the lower right', () => {
    const wrapper = shallowMount(App, {
      global: {
        stubs: {
          StatusBar: true,
          ToastContainer: true,
          RouterView: true,
        },
      },
    })

    expect(wrapper.get('[data-testid="app-version"]').text())
      .toMatch(/^v0\.1\.0-rc\.2 · [0-9a-f]{7,}$/)
    wrapper.unmount()
  })
})
