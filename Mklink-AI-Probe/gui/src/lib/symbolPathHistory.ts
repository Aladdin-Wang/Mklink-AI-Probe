import { DESKTOP_SETTINGS_STORAGE_KEY, isSameFileSourcePath, isSymbolFilePath, type DesktopSettingsStorage } from './desktopSettings'

export const SYMBOL_PATH_HISTORY_KEY = DESKTOP_SETTINGS_STORAGE_KEY + '.symbol-history'
export const MAX_SYMBOL_PATH_HISTORY = 10

export function loadSymbolPathHistory(storage: DesktopSettingsStorage): string[] {
  try {
    const value: unknown = JSON.parse(storage.getItem(SYMBOL_PATH_HISTORY_KEY) || '[]')
    if (!Array.isArray(value)) return []
    const paths: string[] = []
    for (const path of value) {
      if (typeof path === 'string' && isSymbolFilePath(path)
        && !paths.some(previous => isSameFileSourcePath(previous, path))) paths.push(path.trim())
    }
    return paths.slice(0, MAX_SYMBOL_PATH_HISTORY)
  } catch { return [] }
}

function save(storage: DesktopSettingsStorage, paths: string[]): string[] {
  try { storage.setItem(SYMBOL_PATH_HISTORY_KEY, JSON.stringify(paths)) } catch { /* History must not block file selection. */ }
  return paths
}

export function rememberSymbolPath(storage: DesktopSettingsStorage, path: string, displayPath = path): string[] {
  const history = loadSymbolPathHistory(storage)
  // Uploaded browser snapshots are not reusable original file paths.
  if (!isSymbolFilePath(path) || !isSameFileSourcePath(path, displayPath || path)) return history
  return save(storage, [path.trim(), ...history.filter(previous => !isSameFileSourcePath(previous, path))].slice(0, MAX_SYMBOL_PATH_HISTORY))
}

export function removeSymbolPath(storage: DesktopSettingsStorage, path: string): string[] {
  return save(storage, loadSymbolPathHistory(storage).filter(previous => !isSameFileSourcePath(previous, path)))
}
