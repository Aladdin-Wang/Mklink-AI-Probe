import { isTauri } from '@tauri-apps/api/core'
import { relaunch } from '@tauri-apps/plugin-process'
import { check, type Update } from '@tauri-apps/plugin-updater'
import { ref } from 'vue'

export type AppUpdateState = 'idle' | 'checking' | 'downloading' | 'ready' | 'installing' | 'error'

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export function useAppUpdater() {
  const state = ref<AppUpdateState>('idle')
  const version = ref('')
  const progress = ref<number | null>(null)
  const error = ref('')
  let availableUpdate: Update | null = null

  async function checkForUpdates() {
    if (!isTauri()) return

    state.value = 'checking'
    version.value = ''
    progress.value = null
    error.value = ''
    availableUpdate = null

    try {
      const update = await check()
      if (!update) {
        state.value = 'idle'
        return
      }

      availableUpdate = update
      version.value = update.version
      state.value = 'downloading'
      let contentLength = 0
      let downloaded = 0
      await update.download(event => {
        if (event.event === 'Started') {
          contentLength = event.data.contentLength ?? 0
          progress.value = contentLength > 0 ? 0 : null
        } else if (event.event === 'Progress') {
          downloaded += event.data.chunkLength
          progress.value = contentLength > 0 ? Math.min(1, downloaded / contentLength) : null
        } else {
          progress.value = 1
        }
      })
      state.value = 'ready'
    } catch (value) {
      error.value = message(value)
      state.value = 'error'
    }
  }

  async function installAndRelaunch() {
    if (!availableUpdate || state.value !== 'ready') return
    state.value = 'installing'
    error.value = ''
    try {
      await availableUpdate.install()
      await relaunch()
    } catch (value) {
      error.value = message(value)
      state.value = 'error'
    }
  }

  return {
    state,
    version,
    progress,
    error,
    checkForUpdates,
    retry: checkForUpdates,
    installAndRelaunch,
  }
}
