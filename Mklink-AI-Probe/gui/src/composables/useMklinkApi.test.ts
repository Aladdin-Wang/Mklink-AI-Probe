import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useMklinkApi } from './useMklinkApi'

describe('RTT API contracts', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    fetchMock.mockReset()
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({}),
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  it('passes an optional explicit source path to RTT detection', async () => {
    const api = useMklinkApi()
    await api.findRtt('C:\\firmware\\app.elf')
    await api.findRtt()

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/rtt-find', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ source_path: 'C:\\firmware\\app.elf' }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/rtt-find', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({}),
    }))
  })

  it('writes RTT bytes through a compact lowercase hex payload', async () => {
    const api = useMklinkApi()
    await api.writeRtt(Uint8Array.of(0x00, 0x0a, 0xff))

    expect(fetchMock).toHaveBeenCalledWith('/api/dash/rtt/write', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ data_hex: '000aff' }),
    }))
  })

  it('keeps AXF parsing built-in by default and forwards explicit external mode', async () => {
    const api = useMklinkApi()
    await api.parseAxf('C:\\firmware\\app.axf')
    await api.parseAxf('C:\\firmware\\app.axf', 'external')

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/device/parse-axf', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ axf: 'C:\\firmware\\app.axf' }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/device/parse-axf', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ axf: 'C:\\firmware\\app.axf', elf_backend: 'external' }),
    }))
  })
})
