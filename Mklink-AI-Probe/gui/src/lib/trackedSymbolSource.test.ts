import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fileContentStamp } from './fileContent'
vi.mock('./fileContent', () => ({ fileContentStamp: (file: File) => file.text() }))
import { loadDesktopSettings, saveDesktopSettings } from './desktopSettings'
const handles = vi.hoisted(() => new WeakMap<File, { getFile(): Promise<File> }>())
vi.mock('./filePicker', () => ({ symbolFileHandle: (file: File) => handles.get(file) }))
import { trackSymbolSource, trackedSymbolError, trackedSymbolPending, reloadTrackedSymbolSource } from './trackedSymbolSource'

beforeEach(() => { vi.useFakeTimers(); const values = new Map<string, string>(); vi.stubGlobal('localStorage', { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v) }) })
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals() })

describe('browser symbol tracking', () => {
  async function setup() {
    const original = new File(['old'], 'app.axf', { lastModified: 1 })
    const rebuilt = new File(['new'], 'app.axf', { lastModified: 1 })
    const getFile = vi.fn().mockResolvedValue(rebuilt)
    handles.set(original, { getFile })
    const source = { path: '/cache/old.axf', name: 'app.axf', size: 3, sha256: await fileContentStamp(original) }
    const upload = vi.fn().mockResolvedValue({ ...source, path: '/cache/new.axf', sha256: await fileContentStamp(rebuilt) })
    const actions = { upload, reload: vi.fn().mockResolvedValue({ state: 'applied', rtt_addr: '0x20000040' }) }
    saveDesktopSettings(window.localStorage, { ...loadDesktopSettings(window.localStorage), symbolPath: source.path, rttAddress: '0x20000020' })
    trackSymbolSource(original, source, actions)
    return { actions, getFile }
  }

  it('only prompts for stable changed bytes, and switches symbols and RTT only after explicit reload', async () => {
    const { actions } = await setup()
    await vi.advanceTimersByTimeAsync(1100)
    expect(trackedSymbolPending.value).toBe(0)
    await vi.advanceTimersByTimeAsync(6000)
    expect(trackedSymbolPending.value).toBeGreaterThan(0)
    expect(actions.upload).not.toHaveBeenCalled()
    expect(actions.reload).not.toHaveBeenCalled()
    expect(loadDesktopSettings(window.localStorage)).toMatchObject({ symbolPath: '/cache/old.axf', rttAddress: '0x20000020' })
    expect(await reloadTrackedSymbolSource()).toBe(true)
    expect(actions.upload).toHaveBeenCalledOnce()
    expect(actions.reload).toHaveBeenCalledWith('/cache/new.axf', '/cache/old.axf')
    expect(loadDesktopSettings(window.localStorage)).toMatchObject({ symbolPath: '/cache/new.axf', rttAddress: '0x20000040' })
    expect(trackedSymbolPending.value).toBe(0)
    await vi.advanceTimersByTimeAsync(2000)
    expect(actions.upload).toHaveBeenCalledOnce()
  })

  it('does not replace a different source chosen while an upload is pending', async () => {
    const { actions } = await setup()
    actions.upload.mockImplementationOnce(async () => {
      saveDesktopSettings(window.localStorage, { ...loadDesktopSettings(window.localStorage), symbolPath: '/chosen.axf' })
      return { path: '/late.axf', name: 'app.axf', size: 3, sha256: 'late' }
    })
    await vi.advanceTimersByTimeAsync(3100)
    await expect(reloadTrackedSymbolSource()).rejects.toThrow('source changed')
    expect(loadDesktopSettings(window.localStorage).symbolPath).toBe('/chosen.axf')
    expect(actions.reload).not.toHaveBeenCalled()
  })

  it('reports parse failure without repeatedly stopping and reparsing unchanged bytes', async () => {
    const { actions } = await setup()
    actions.reload.mockRejectedValue(new Error('invalid AXF'))
    await vi.advanceTimersByTimeAsync(3100)
    await expect(reloadTrackedSymbolSource()).rejects.toThrow('invalid AXF')
    await vi.advanceTimersByTimeAsync(5000)
    expect(actions.reload).toHaveBeenCalledOnce()
    expect(trackedSymbolError.value).toBe('invalid AXF')
    expect(trackedSymbolPending.value).toBeGreaterThan(0)
    expect(loadDesktopSettings(window.localStorage)).toMatchObject({ symbolPath: '/cache/old.axf', rttAddress: '0x20000020' })
  })

  it('prompts for a timestamp-only rebuild without uploading or switching', async () => {
    const { actions, getFile } = await setup()
    getFile.mockResolvedValue(new File(['old'], 'app.axf', { lastModified: 2 }))
    await vi.advanceTimersByTimeAsync(3100)
    const first = trackedSymbolPending.value
    expect(first).toBeGreaterThan(0)
    await vi.advanceTimersByTimeAsync(4000)
    expect(trackedSymbolPending.value).toBe(first)
    expect(actions.upload).not.toHaveBeenCalled()
    getFile.mockResolvedValue(new File(['old'], 'app.axf', { lastModified: 3 }))
    await vi.advanceTimersByTimeAsync(3100)
    expect(trackedSymbolPending.value).toBeGreaterThan(first)
  })

  it('keeps a newer build pending when the user is loading an earlier build', async () => {
    const { actions, getFile } = await setup()
    await vi.advanceTimersByTimeAsync(3100)
    actions.reload.mockImplementationOnce(async () => {
      getFile.mockResolvedValue(new File(['next'], 'app.axf', { lastModified: 3 }))
      await vi.advanceTimersByTimeAsync(3100)
      return { state: 'applied', rtt_addr: '0x20000040' }
    })
    await reloadTrackedSymbolSource()
    expect(trackedSymbolPending.value).toBeGreaterThan(0)
    expect(actions.upload).toHaveBeenCalledOnce()
    await reloadTrackedSymbolSource()
    expect(actions.upload.mock.calls[1]![0]).toBe(await getFile())
    expect(trackedSymbolPending.value).toBe(0)
  })
})
