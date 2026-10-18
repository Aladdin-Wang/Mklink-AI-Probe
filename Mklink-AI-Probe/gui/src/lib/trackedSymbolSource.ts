import { ref } from 'vue'
import { fileContentStamp } from './fileContent'
import { symbolFileHandle } from './filePicker'
import { isSameFileSourcePath, loadDesktopSettings, saveDesktopSettings } from './desktopSettings'
import type { UploadedFileSource } from '../types/mklink'

export const trackedSymbolPath = ref('')
export const trackedSymbolError = ref('')
export const trackedSymbolPending = ref(0)
let revision = 0
let cancel: (() => void) | undefined
let reload: (() => Promise<void>) | undefined

interface SymbolTrackingActions {
  upload(file: File): Promise<UploadedFileSource>
  reload(path: string, expectedPath: string): Promise<{ state?: string; rtt_addr?: string }>
}

export async function reloadTrackedSymbolSource(): Promise<boolean> {
  if (!trackedSymbolPending.value || !reload) return false
  await reload()
  return true
}

/** The handle belongs to this browser session; plain uploads cannot be watched. */
export function trackSymbolSource(file: File, source: UploadedFileSource, actions: SymbolTrackingActions): void {
  cancel?.()
  trackedSymbolPath.value = ''
  trackedSymbolError.value = ''
  trackedSymbolPending.value = 0
  reload = undefined
  const handle = symbolFileHandle(file)
  if (!handle) return
  let stopped = false
  let busy = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let path = source.path
  let stamp = `${source.sha256}:${file.lastModified}`
  let observed = stamp
  let stableSince = 0
  let pending: { file: File; stamp: string } | undefined
  const current = () => !stopped && isSameFileSourcePath(loadDesktopSettings(window.localStorage).symbolPath, path)
  const clear = () => {
    trackedSymbolPath.value = ''
    trackedSymbolPending.value = 0
    reload = undefined
  }
  cancel = () => { stopped = true; if (timer !== undefined) clearTimeout(timer) }
  trackedSymbolPath.value = path
  reload = async () => {
    if (busy) throw new Error('Symbol reload is already in progress')
    if (!current() || !pending) { clear(); throw new Error('The selected symbol source changed') }
    busy = true
    const selected = pending
    try {
      const uploaded = await actions.upload(selected.file)
      if (!current()) throw new Error('The selected symbol source changed')
      const result = await actions.reload(uploaded.path, path)
      if (result.state !== 'applied') throw new Error('Symbols were not reloaded')
      if (!current()) return
      const settings = loadDesktopSettings(window.localStorage)
      path = uploaded.path
      saveDesktopSettings(window.localStorage, { ...settings, symbolPath: path,
        symbolDisplayPath: uploaded.name || selected.file.name, rttAddress: result.rtt_addr || '' })
      trackedSymbolPath.value = path
      stamp = selected.stamp
      if (pending === selected) { pending = undefined; trackedSymbolPending.value = 0 }
      trackedSymbolError.value = ''
    } catch (error) {
      if (current()) trackedSymbolError.value = error instanceof Error ? error.message : String(error)
      throw error
    } finally { busy = false }
  }
  const poll = async () => {
    if (!current()) { if (!stopped) clear(); return }
    try {
      const next = await handle.getFile()
      const nextStamp = `${await fileContentStamp(next)}:${next.lastModified}`
      if (!current()) return
      if (nextStamp !== observed) { observed = nextStamp; stableSince = Date.now() }
      if (nextStamp !== stamp && nextStamp !== pending?.stamp && Date.now() - stableSince >= 2000) {
        pending = { file: next, stamp: nextStamp }
        trackedSymbolPending.value = ++revision
      }
    } catch (error) {
      if (current()) trackedSymbolError.value = error instanceof Error ? error.message : String(error)
    } finally {
      if (current()) timer = setTimeout(poll, 1000)
    }
  }
  timer = setTimeout(poll, 1000)
}
