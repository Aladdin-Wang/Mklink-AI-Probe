import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadTextFile, timestampedLogName } from './downloadTextFile'

describe('downloadTextFile', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('downloads a UTF-8 text file and releases the object URL', () => {
    vi.useFakeTimers()
    const createObjectURL = vi.fn().mockReturnValue('blob:test')
    const revokeObjectURL = vi.fn()
    const click = vi.fn()
    const remove = vi.fn()
    const appendChild = vi.spyOn(document.body, 'appendChild').mockImplementation(node => node)
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    vi.spyOn(document, 'createElement').mockReturnValue({
      href: '', download: '', style: {}, click, remove,
    } as unknown as HTMLAnchorElement)

    downloadTextFile('serial.log', '温度=25')

    const blob = createObjectURL.mock.calls[0][0] as Blob
    expect(blob.type).toBe('text/plain;charset=utf-8')
    expect(appendChild).toHaveBeenCalledTimes(1)
    expect(click).toHaveBeenCalledTimes(1)
    expect(remove).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).not.toHaveBeenCalled()
    vi.runAllTimers()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:test')
  })

  it('creates filesystem-safe timestamped log names', () => {
    expect(timestampedLogName('rtt', new Date('2026-08-10T01:02:03.456Z')))
      .toBe('rtt-2026-08-10T01-02-03-456Z.log')
  })
})
