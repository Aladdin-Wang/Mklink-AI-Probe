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
  ipc.invoke.mockImplementation(command => command === 'restart_sidecar'
    ? new Promise(resolve => { ready = resolve }) : Promise.resolve(null))
  const health = (await import('../composables/useBackendHealth')).useBackendHealth()
  health.startHealthPolling()
  const restart = health.restart()
  await health.restart()
  await vi.advanceTimersByTimeAsync(60_000)
  expect(health.backendState.value).toBe('starting')
  expect(ipc.invoke.mock.calls.filter(([command]) => command === 'restart_sidecar')).toHaveLength(1)
  ready({ port: 8767, instanceId: 'restarted' })
  await vi.advanceTimersByTimeAsync(600)
  await restart
  expect(health.backendState.value).toBe('alive')
  health.stopHealthPolling()
})

it('recovers the owned endpoint after event initialization failed instead of polling port zero forever', async () => {
  vi.stubGlobal('__TAURI_INTERNALS__', {})
  ipc.listen.mockRejectedValueOnce(new Error('IPC listener not ready'))
  const fetchMock = vi.fn(async () => Response.json({ status: 'ok', shared_runtime: true }))
  vi.stubGlobal('fetch', fetchMock)
  const runtime = await import('./runtimeEndpoint')
  await expect(runtime.initializeRuntimeEndpoint()).rejects.toThrow('IPC listener')
  expect(runtime.API_BASE).toBe('http://127.0.0.1:0')
  ipc.invoke.mockResolvedValue({ port: 8771, instanceId: 'owned-window' })
  const health = (await import('../composables/useBackendHealth')).useBackendHealth()
  await health.refreshHealth()
  expect(health.backendState.value).toBe('alive')
  expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8771/api/health')
  ipc.invoke.mockResolvedValue({ port: 8772, instanceId: 'owned-window' })
  await health.refreshHealth()
  expect(runtime.WS_BASE).toBe('ws://127.0.0.1:8772')
})

it('surfaces a native startup failure without waiting for the entire cold-start timeout', async () => {
  vi.stubGlobal('__TAURI_INTERNALS__', {})
  ipc.invoke.mockRejectedValue(new Error('Desktop proxy exited (exit code: 1). Log: startup.log'))
  const runtime = await import('./runtimeEndpoint')
  await expect(runtime.initializeRuntimeEndpoint()).rejects.toThrow('exit code: 1')
  expect(runtime.backendStartupError.value).toContain('startup.log')
  expect(runtime.runtimeBackendPort.value).toBeNull()
})
