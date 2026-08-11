import { createApp } from 'vue'
import { initializeRuntimeEndpoint } from './lib/runtimeEndpoint'

async function startApp() {
  try {
    await initializeRuntimeEndpoint()
  } catch (error) {
    console.error('[main] backend endpoint initialization failed:', error)
  }
  const [{ default: App }, { default: router }] = await Promise.all([
    import('./App.vue'),
    import('./router'),
  ])
  createApp(App).use(router).mount('#app')
}

void startApp()
