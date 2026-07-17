import { afterEach, describe, expect, it, vi } from 'vitest'

const firstPage = {
  generation: 1,
  parsed_at: 10,
  fingerprint: { size: 100, mtime_ns: 200 },
  stale: false,
  total: 2,
  items: [
    {
      path: 'controller.target',
      address: 0x20000024,
      type_name: 'float',
      scalar_kind: 'float',
      size: 4,
      writable: true,
      enum_values: {},
      parent_path: 'controller',
    },
    {
      path: 'gain',
      address: 0x20000020,
      type_name: 'float',
      scalar_kind: 'float',
      size: 4,
      writable: true,
      enum_values: {},
      parent_path: null,
    },
  ],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? 'Request failed' : 'OK',
    headers: { 'Content-Type': 'application/json' },
  })
}

async function freshCatalog() {
  vi.resetModules()
  return (await import('./useSymbolCatalog')).useSymbolCatalog()
}

describe('useSymbolCatalog', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('loads the catalog once and shares it across consumers', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(firstPage))
    vi.stubGlobal('fetch', fetchMock)
    vi.resetModules()
    const { useSymbolCatalog } = await import('./useSymbolCatalog')
    const first = useSymbolCatalog()
    const second = useSymbolCatalog()

    await Promise.all([first.ensureLoaded(), second.ensureLoaded()])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(second.items.value.map(item => item.path)).toEqual(['controller.target', 'gain'])
    expect(second.generation.value).toBe(1)
  })

  it('refreshes stale status without replacing the loaded catalog', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(firstPage))
      .mockResolvedValueOnce(jsonResponse({
        loaded: true,
        generation: 1,
        parsed_at: 10,
        fingerprint: firstPage.fingerprint,
        stale: true,
        total: 2,
      }))
    vi.stubGlobal('fetch', fetchMock)
    const symbols = await freshCatalog()

    await symbols.ensureLoaded()
    await symbols.refreshStatus()

    expect(symbols.stale.value).toBe(true)
    expect(symbols.items.value.map(item => item.path)).toEqual(['controller.target', 'gain'])
  })

  it('reparses and atomically replaces the catalog', async () => {
    const nextPage = {
      ...firstPage,
      generation: 2,
      stale: false,
      items: [{ ...firstPage.items[1], address: 0x20000040 }],
      total: 1,
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(firstPage))
      .mockResolvedValueOnce(jsonResponse({ preserved: [], updated: ['gain'], removed: ['controller.target'] }))
      .mockResolvedValueOnce(jsonResponse(nextPage))
    vi.stubGlobal('fetch', fetchMock)
    const symbols = await freshCatalog()

    await symbols.ensureLoaded()
    const summary = await symbols.reparse()

    expect(summary).toEqual({ preserved: [], updated: ['gain'], removed: ['controller.target'] })
    expect(symbols.generation.value).toBe(2)
    expect(symbols.items.value).toHaveLength(1)
    expect(symbols.items.value[0].address).toBe(0x20000040)
  })

  it('keeps the previous catalog when reparse fails', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(firstPage))
      .mockResolvedValueOnce(jsonResponse({ detail: { phase: 'reparse', message: 'bad DWARF' } }, 409))
    vi.stubGlobal('fetch', fetchMock)
    const symbols = await freshCatalog()

    await symbols.ensureLoaded()
    await expect(symbols.reparse()).rejects.toThrow('bad DWARF')

    expect(symbols.generation.value).toBe(1)
    expect(symbols.items.value).toHaveLength(2)
  })

  it('writes a typed value with the selected catalog generation', async () => {
    const result = { path: 'gain', generation: 1, value: 1.3, verified: true }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(firstPage))
      .mockResolvedValueOnce(jsonResponse(result))
    vi.stubGlobal('fetch', fetchMock)
    const symbols = await freshCatalog()

    await symbols.ensureLoaded()
    await expect(symbols.writeSymbol('gain', 1.3)).resolves.toEqual(result)

    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/dash/superwatch/write',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ path: 'gain', generation: 1, value: 1.3 }),
      }),
    )
  })
})
