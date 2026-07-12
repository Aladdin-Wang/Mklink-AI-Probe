import type { PreviewPage } from '../types/onlineFlash'

export const HEX_ROW_BYTES = 16
export const PREVIEW_PAGE_BYTES = 4096
export const PREVIEW_OVERSCAN_ROWS = 20
export const PREVIEW_MAX_PAGES = 16

export interface FormattedHexRow {
  address: string
  hex: string[]
  ascii: string
}

export interface PreviewSource {
  imageId: string
  start: number
  size: number
}

export interface VisibleHexRange {
  startRow: number
  endRow: number
  totalRows: number
  paddingTop: number
  paddingBottom: number
}

export type PreviewPageLoader = (
  imageId: string,
  offset: number,
  length: number,
  signal: AbortSignal,
) => Promise<PreviewPage>

interface DecodedPage {
  bytes: Uint8Array
  present: boolean[]
}

export function formatHexRow(
  address: number,
  bytes: Uint8Array,
  presence?: readonly boolean[],
): FormattedHexRow {
  const hex: string[] = []
  let ascii = ''
  for (let index = 0; index < HEX_ROW_BYTES; index += 1) {
    const present = index < bytes.length && (presence?.[index] ?? true)
    if (!present) {
      hex.push('--')
      ascii += ' '
      continue
    }
    const value = bytes[index]
    hex.push(value.toString(16).toUpperCase().padStart(2, '0'))
    ascii += value >= 0x20 && value <= 0x7e ? String.fromCharCode(value) : '.'
  }
  return {
    address: address.toString(16).toUpperCase().padStart(8, '0'),
    hex,
    ascii,
  }
}

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value)
  return Uint8Array.from(binary, character => character.charCodeAt(0))
}

function abortError(): DOMException {
  return new DOMException('Aborted', 'AbortError')
}

export class HexPreviewModel {
  private readonly loader: PreviewPageLoader
  private readonly pageSize: number
  private readonly maxPages: number
  private source: PreviewSource | null = null
  private readonly cache = new Map<number, DecodedPage>()
  private readonly controllers = new Set<AbortController>()
  private generation = 0

  constructor(
    loader: PreviewPageLoader,
    pageSize = PREVIEW_PAGE_BYTES,
    maxPages = PREVIEW_MAX_PAGES,
  ) {
    this.loader = loader
    this.pageSize = pageSize
    this.maxPages = maxPages
  }

  setSource(source: PreviewSource | null): void {
    this.generation += 1
    for (const controller of this.controllers) controller.abort()
    this.controllers.clear()
    this.cache.clear()
    this.source = source
  }

  visibleRange(scrollTop: number, viewportHeight: number, rowHeight: number): VisibleHexRange {
    const totalRows = this.source ? Math.ceil(this.source.size / HEX_ROW_BYTES) : 0
    const firstVisible = Math.max(0, Math.floor(scrollTop / rowHeight))
    const visibleCount = Math.ceil(viewportHeight / rowHeight)
    const startRow = Math.max(0, firstVisible - PREVIEW_OVERSCAN_ROWS)
    const endRow = Math.min(totalRows, firstVisible + visibleCount + PREVIEW_OVERSCAN_ROWS)
    return {
      startRow,
      endRow,
      totalRows,
      paddingTop: startRow * rowHeight,
      paddingBottom: Math.max(0, (totalRows - endRow) * rowHeight),
    }
  }

  async loadRows(startRow: number, endRow: number): Promise<FormattedHexRow[]> {
    const source = this.source
    if (!source) return []
    const boundedStart = Math.max(0, startRow)
    const boundedEnd = Math.min(Math.ceil(source.size / HEX_ROW_BYTES), Math.max(boundedStart, endRow))
    const rows: FormattedHexRow[] = []
    for (let row = boundedStart; row < boundedEnd; row += 1) {
      const offset = row * HEX_ROW_BYTES
      const pageOffset = Math.floor(offset / this.pageSize) * this.pageSize
      const decoded = await this.loadPage(pageOffset, source)
      const withinPage = offset - pageOffset
      const length = Math.min(HEX_ROW_BYTES, source.size - offset)
      rows.push(formatHexRow(
        source.start + offset,
        decoded.bytes.slice(withinPage, withinPage + length),
        decoded.present.slice(withinPage, withinPage + length),
      ))
    }
    return rows
  }

  private async loadPage(offset: number, source: PreviewSource): Promise<DecodedPage> {
    const cached = this.cache.get(offset)
    if (cached) {
      this.cache.delete(offset)
      this.cache.set(offset, cached)
      return cached
    }
    const generation = this.generation
    const controller = new AbortController()
    this.controllers.add(controller)
    try {
      const length = Math.min(this.pageSize, source.size - offset)
      const response = await this.loader(source.imageId, offset, length, controller.signal)
      if (controller.signal.aborted || generation !== this.generation || source !== this.source) {
        throw abortError()
      }
      const decoded = {
        bytes: decodeBase64(response.data_base64),
        present: response.present,
      }
      this.cache.set(offset, decoded)
      while (this.cache.size > this.maxPages) {
        const oldest = this.cache.keys().next().value as number | undefined
        if (oldest === undefined) break
        this.cache.delete(oldest)
      }
      return decoded
    } finally {
      this.controllers.delete(controller)
    }
  }
}
