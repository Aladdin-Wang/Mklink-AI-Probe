import { shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import App from './App.vue'

const backendState = ref<'starting' | 'alive' | 'dead'>('starting')
const startStatusPolling = vi.fn()
const restart = vi.fn()
const checkForUpdates = vi.fn()
const installAndRelaunch = vi.fn()
const retryUpdate = vi.fn()
const updateState = ref<'idle' | 'checking' | 'downloading' | 'ready' | 'installing' | 'error'>('idle')

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ name: 'dashboard' }),
}))

vi.mock('./composables/useMklinkApi', () => ({
  useMklinkApi: () => ({ startStatusPolling, stopStatusPolling: vi.fn() }),
}))

vi.mock('./composables/useBackendHealth', () => ({
  useBackendHealth: () => ({
    backendState,
    startHealthPolling: vi.fn(),
    stopHealthPolling: vi.fn(),
    restart,
  }),
}))

vi.mock('./composables/useAppUpdater', () => ({
  useAppUpdater: () => ({
    state: updateState,
    version: ref('0.2.0'),
    progress: ref(1),
    error: ref(''),
    checkForUpdates,
    installAndRelaunch,
    retry: retryUpdate,
  }),
}))

function mountApp() {
  return shallowMount(App, {
    global: {
      stubs: {
        StatusBar: true,
        ToastContainer: true,
        AppUpdateBanner: true,
        RouterView: { template: '<div data-testid="route-view" />' },
      },
    },
  })
}

describe('App version footer', () => {
  it('checks for desktop updates when the application starts', () => {
    checkForUpdates.mockClear()
    const wrapper = mountApp()

    expect(checkForUpdates).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('shows the stable release and source build in the lower right', () => {
    const wrapper = mountApp()

    expect(wrapper.get('[data-testid="app-version"]').text())
      .toMatch(/^v0\.1\.0 · [0-9a-f]{7,}$/)
    wrapper.unmount()
  })

  it('does not mount route views or poll device state before the backend API is ready', async () => {
    backendState.value = 'starting'
    startStatusPolling.mockClear()
    const wrapper = mountApp()

    expect(wrapper.find('[data-testid="route-view"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="backend-starting"]').exists()).toBe(true)
    expect(startStatusPolling).not.toHaveBeenCalled()

    backendState.value = 'alive'
    await nextTick()

    expect(wrapper.get('[data-testid="route-view"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="backend-starting"]').exists()).toBe(false)
    expect(startStatusPolling).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('offers sidecar recovery when the first startup attempt fails', async () => {
    backendState.value = 'dead'
    restart.mockClear()
    const wrapper = mountApp()

    expect(wrapper.find('[data-testid="route-view"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="backend-starting"]').exists()).toBe(false)
    await wrapper.get('[data-testid="backend-restart"]').trigger('click')
    expect(restart).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
})
