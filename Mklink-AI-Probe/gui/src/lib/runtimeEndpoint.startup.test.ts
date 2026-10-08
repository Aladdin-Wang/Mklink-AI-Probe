import { afterEach, expect, it, vi } from 'vitest'

const ipc = vi.hoisted(() => ({ invoke: vi.fn(), listen: vi.fn(async () => () => {}) }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: ipc.invoke }))
vi.mock('@tauri-apps/api/event', () => ({ listen: ipc.listen }))

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.resetModules()
  vi.clearAllMocks()
})

it('waits through a 60-second cold start and uses the reported dynamic port', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('__TAURI_INTERNALS__', {})
  const started = Date.now()
  ipc.invoke.mockImplementation(async () => Date.now() - started >= 60_000
    ? { port: 8766, instanceId: 'slow-start' } : null)
  const runtime = await import('./runtimeEndpoint')
  let complete = false
  const initializing = runtime.initializeRuntimeEndpoint().then(() => { complete = true })
  await vi.advanceTimersByTimeAsync(21_000)
  expect(complete).toBe(false)
  await vi.advanceTimersByTimeAsync(40_000)
  await initializing
  expect(runtime.API_BASE).toBe('http://127.0.0.1:8766')
  expect(runtime.WS_BASE).toBe('ws://127.0.0.1:8766')
})

it('eventually reports a backend that never publishes its endpoint', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('__TAURI_INTERNALS__', {})
  ipc.invoke.mockResolvedValue(null)
  const runtime = await import('./runtimeEndpoint')
  const result = runtime.initializeRuntimeEndpoint().catch(error => error)
  await vi.advanceTimersByTimeAsync(126_000)
  expect((await result).message).toContain('Timed out')
  expect(runtime.runtimeBackendPort.value).toBeNull()
})

it('keeps a slow restart in progress and ignores duplicate restart clicks', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('__TAURI_INTERNALS__', {})
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ status: 'ok' })))
  let ready!: (endpoint: { port: number, instanceId: string }) => void
  ipc.invoke.mockImplementation(() => new Promise(resolve => { ready = resolve }))
  const health = (await import('../composables/useBackendHealth')).useBackendHealth()
  health.startHealthPolling()
  const restart = health.restart()
  await health.restart()
  await vi.advanceTimersByTimeAsync(60_000)
  expect(health.backendState.value).toBe('starting')
  expect(ipc.invoke).toHaveBeenCalledTimes(1)
  ready({ port: 8767, instanceId: 'restarted' })
  await vi.advanceTimersByTimeAsync(600)
  await restart
  expect(health.backendState.value).toBe('alive')
  health.stopHealthPolling()
})
