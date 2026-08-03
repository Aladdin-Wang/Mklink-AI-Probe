import { describe, expect, it } from 'vitest'
import { isTauriRuntime, resolveRuntimeBase } from './runtimeEndpoint'

describe('runtime endpoint selection', () => {
  it('uses the current origin for a browser-hosted Web GUI', () => {
    expect(isTauriRuntime({})).toBe(false)
    expect(resolveRuntimeBase('http://127.0.0.1:8765/', false)).toBe('')
  })

  it('uses the configured sidecar endpoint inside Tauri', () => {
    expect(isTauriRuntime({ __TAURI_INTERNALS__: {} })).toBe(true)
    expect(resolveRuntimeBase('http://127.0.0.1:8765/', true)).toBe('http://127.0.0.1:8765')
  })

  it('accepts the legacy Tauri marker used by older WebViews', () => {
    expect(isTauriRuntime({ __TAURI__: {} })).toBe(true)
  })
})
