import { beforeEach, describe, expect, it, vi } from 'vitest'

const updaterMocks = vi.hoisted(() => ({
  check: vi.fn(),
  isTauri: vi.fn(),
  relaunch: vi.fn(),
}))

vi.mock('@tauri-apps/api/core', () => ({ isTauri: updaterMocks.isTauri }))
vi.mock('@tauri-apps/plugin-updater', () => ({ check: updaterMocks.check }))
vi.mock('@tauri-apps/plugin-process', () => ({ relaunch: updaterMocks.relaunch }))

import { useAppUpdater } from './useAppUpdater'

function update(version = '0.2.0') {
  return {
    version,
    download: vi.fn(async (onEvent?: (event: unknown) => void) => {
      onEvent?.({ event: 'Started', data: { contentLength: 100 } })
      onEvent?.({ event: 'Progress', data: { chunkLength: 40 } })
      onEvent?.({ event: 'Progress', data: { chunkLength: 60 } })
      onEvent?.({ event: 'Finished' })
    }),
    install: vi.fn(async () => undefined),
  }
}

describe('useAppUpdater', () => {
  beforeEach(() => {
    updaterMocks.check.mockReset()
    updaterMocks.isTauri.mockReset()
    updaterMocks.relaunch.mockReset()
  })

  it('does nothing outside the Tauri desktop runtime', async () => {
    updaterMocks.isTauri.mockReturnValue(false)
    const updater = useAppUpdater()

    await updater.checkForUpdates()

    expect(updaterMocks.check).not.toHaveBeenCalled()
    expect(updater.state.value).toBe('idle')
  })

  it('checks on request and downloads an available update in the background', async () => {
    updaterMocks.isTauri.mockReturnValue(true)
    const available = update()
    updaterMocks.check.mockResolvedValue(available)
    const updater = useAppUpdater()

    await updater.checkForUpdates()

    expect(updaterMocks.check).toHaveBeenCalledOnce()
    expect(available.download).toHaveBeenCalledOnce()
    expect(updater.state.value).toBe('ready')
    expect(updater.version.value).toBe('0.2.0')
    expect(updater.progress.value).toBe(1)
  })

  it('can retry after a network failure', async () => {
    updaterMocks.isTauri.mockReturnValue(true)
    updaterMocks.check.mockRejectedValueOnce(new Error('network unavailable'))
    const available = update()
    updaterMocks.check.mockResolvedValueOnce(available)
    const updater = useAppUpdater()

    await updater.checkForUpdates()
    expect(updater.state.value).toBe('error')
    expect(updater.error.value).toBe('network unavailable')

    await updater.retry()
    expect(updater.state.value).toBe('ready')
    expect(updater.error.value).toBe('')
  })

  it('installs the downloaded update and relaunches after explicit confirmation', async () => {
    updaterMocks.isTauri.mockReturnValue(true)
    const available = update()
    updaterMocks.check.mockResolvedValue(available)
    const updater = useAppUpdater()
    await updater.checkForUpdates()

    await updater.installAndRelaunch()

    expect(available.install).toHaveBeenCalledOnce()
    expect(updaterMocks.relaunch).toHaveBeenCalledOnce()
    expect(updater.state.value).toBe('installing')
  })
})
