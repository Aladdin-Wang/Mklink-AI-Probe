type RuntimeWindow = {
  __TAURI__?: unknown
  __TAURI_INTERNALS__?: unknown
}

export function isTauriRuntime(runtime: RuntimeWindow = window as RuntimeWindow): boolean {
  return Boolean(runtime.__TAURI__ || runtime.__TAURI_INTERNALS__)
}

export function resolveRuntimeBase(configuredBase: string, tauri = isTauriRuntime()): string {
  return tauri ? configuredBase.trim().replace(/\/+$/, '') : ''
}

export const IS_TAURI = isTauriRuntime()
export const API_BASE = resolveRuntimeBase(import.meta.env.VITE_MKLINK_API || '', IS_TAURI)
export const WS_BASE = resolveRuntimeBase(import.meta.env.VITE_MKLINK_WS || '', IS_TAURI)
