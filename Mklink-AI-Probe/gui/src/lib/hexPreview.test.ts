import { describe, expect, it, vi } from 'vitest'
import { HexPreviewModel, formatHexRow } from './hexPreview'
import type { PreviewPage } from '../types/onlineFlash'

function page(offset: number, length = 4096): PreviewPage {
  const data = Uint8Array.from({ length }, (_, index) => (offset + index) & 0xff)
  let binary = ''
  for (const value of data) binary += String.fromCharCode(value)
  return {
    address: 0x1000 + offset,
    length,
    data_base64: btoa(binary),
    present: Array.from({ length }, () => true),
  }
}

describe('formatHexRow', () => {
  it('formats an uppercase eight-digit address, sixteen cells, and printable ASCII', () => {
    const bytes = Uint8Array.from([0x20, 0x41, 0x7e, 0x1f, 0x7f])
    const row = formatHexRow(0x1a2b, bytes)

    expect(row.address).toBe('00001A2B')
    expect(row.hex).toHaveLength(16)
    expect(row.hex.slice(0, 5)).toEqual(['20', '41', '7E', '1F', '7F'])
    expect(row.hex.slice(5)).toEqual(Array(11).fill('--'))
    expect(row.ascii).toBe(' A~..           ')
  })

  it('renders explicitly missing bytes as gaps', () => {
    const row = formatHexRow(0xfffffff8, Uint8Array.from([0x41, 0x42, 0x43]), [true, false, true])

    expect(row.hex.slice(0, 4)).toEqual(['41', '--', '43', '--'])
    expect(row.ascii.slice(0, 4)).toBe('A C ')
  })
})

describe('HexPreviewModel', () => {
  it('calculates only visible rows plus twenty-row overscan', () => {
    const model = new HexPreviewModel(vi.fn())
    model.setSource({ imageId: 'image', start: 0x1000, size: 16 * 1000 })

    expect(model.visibleRange(50 * 20, 10 * 20, 20)).toEqual({
      startRow: 30,
      endRow: 80,
      totalRows: 1000,
      paddingTop: 600,
      paddingBottom: 18_400,
    })
  })

  it('loads 4096-byte pages and preserves a partial final row', async () => {
    const loader = vi.fn(async (_id: string, offset: number, length: number) => page(offset, length))
    const model = new HexPreviewModel(loader)
    model.setSource({ imageId: 'image', start: 0x1000, size: 4099 })

    const rows = await model.loadRows(255, 257)

    expect(loader).toHaveBeenNthCalledWith(1, 'image', 0, 4096, expect.any(AbortSignal))
    expect(loader).toHaveBeenNthCalledWith(2, 'image', 4096, 3, expect.any(AbortSignal))
    expect(rows).toHaveLength(2)
    expect(rows[0].address).toBe('00001FF0')
    expect(rows[1].hex.slice(0, 4)).toEqual(['00', '01', '02', '--'])
  })

  it('evicts the least-recently-used page after sixteen cached pages', async () => {
    const loader = vi.fn(async (_id: string, offset: number, length: number) => page(offset, length))
    const model = new HexPreviewModel(loader)
    model.setSource({ imageId: 'image', start: 0x1000, size: 4096 * 18 })

    for (let index = 0; index < 16; index += 1) await model.loadRows(index * 256, index * 256 + 1)
    await model.loadRows(0, 1)
    await model.loadRows(16 * 256, 16 * 256 + 1)
    await model.loadRows(256, 257)

    expect(loader).toHaveBeenCalledTimes(18)
    expect(loader.mock.calls.at(-1)?.[1]).toBe(4096)
  })

  it('aborts stale requests and clears cached pages when the image changes', async () => {
    let resolveFirst!: (value: PreviewPage) => void
    const first = new Promise<PreviewPage>(resolve => { resolveFirst = resolve })
    const loader = vi.fn((_id: string, offset: number, length: number, signal: AbortSignal) => {
      if (loader.mock.calls.length === 1) {
        return new Promise<PreviewPage>((resolve, reject) => {
          first.then(resolve)
          signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        })
      }
      return Promise.resolve(page(offset, length))
    })
    const model = new HexPreviewModel(loader)
    model.setSource({ imageId: 'old', start: 0x1000, size: 4096 })
    const stale = model.loadRows(0, 1)

    model.setSource({ imageId: 'new', start: 0x1000, size: 4096 })
    await expect(stale).rejects.toMatchObject({ name: 'AbortError' })
    resolveFirst(page(0))
    await model.loadRows(0, 1)

    expect(loader).toHaveBeenCalledTimes(2)
    expect(loader.mock.calls[1][0]).toBe('new')
  })

  it('shares one in-flight fetch for concurrent consumers of the same page', async () => {
    let resolve!: (value: PreviewPage) => void
    const pending = new Promise<PreviewPage>(done => { resolve = done })
    const loader = vi.fn(() => pending)
    const model = new HexPreviewModel(loader)
    model.setSource({ imageId: 'image', start: 0x1000, size: 4096 })

    const first = model.loadRows(0, 1)
    const second = model.loadRows(1, 2)
    expect(loader).toHaveBeenCalledTimes(1)
    resolve(page(0))

    await expect(first).resolves.toHaveLength(1)
    await expect(second).resolves.toHaveLength(1)
  })

  it('removes a rejected in-flight page so it can be retried', async () => {
    const loader = vi.fn()
      .mockRejectedValueOnce(new Error('preview failed'))
      .mockResolvedValueOnce(page(0))
    const model = new HexPreviewModel(loader)
    model.setSource({ imageId: 'image', start: 0x1000, size: 4096 })

    await expect(model.loadRows(0, 1)).rejects.toThrow('preview failed')
    await expect(model.loadRows(0, 1)).resolves.toHaveLength(1)
    expect(loader).toHaveBeenCalledTimes(2)
  })

  it('does not let an old slow consumer evict the sixteen current pages', async () => {
    let resolveOld!: (value: PreviewPage) => void
    const old = new Promise<PreviewPage>(done => { resolveOld = done })
    const loader = vi.fn((_id: string, offset: number, length: number) => (
      offset === 0 ? old : Promise.resolve(page(offset, length))
    ))
    const model = new HexPreviewModel(loader)
    model.setSource({ imageId: 'image', start: 0x1000, size: 4096 * 17 })

    const stale = model.loadRows(0, 1)
    for (let pageIndex = 1; pageIndex <= 16; pageIndex += 1) {
      await model.loadRows(pageIndex * 256, pageIndex * 256 + 1)
    }
    resolveOld(page(0))
    await stale
    await model.loadRows(256, 257)

    expect(loader).toHaveBeenCalledTimes(17)
  })
})
