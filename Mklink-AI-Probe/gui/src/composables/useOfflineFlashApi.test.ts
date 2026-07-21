import { afterEach, describe, expect, it, vi } from 'vitest'
import { useOfflineFlashApi } from './useOfflineFlashApi'

describe('useOfflineFlashApi', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('preserves structured probe conflict details as an actionable Chinese error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: {
        code: 'PROBE_BUSY',
        resource: 'mklink_bridge',
        conflict_owner: 'user:dashboard:superwatch',
      },
    }), { status: 409, statusText: 'Conflict' })))

    const error = await useOfflineFlashApi().detectModel().catch(value => value)

    expect(error).toBeInstanceOf(Error)
    expect(error.message).toBe('探针正被 SuperWatch 占用，请先停止该功能后重试。')
  })

  it('delivers offline trigger lines before resolving the final result', async () => {
    const encoder = new TextEncoder()
    let finish: (() => void) | undefined
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"line","line":"erase started"}\n'))
        finish = () => {
          controller.enqueue(encoder.encode(
            '{"type":"result","result":{"status":"completed","lines":["erase started"]}}\n',
          ))
          controller.close()
        }
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, {
      status: 200,
      headers: { 'Content-Type': 'application/x-ndjson' },
    })))
    const lines: string[] = []
    let resolved = false

    const pending = useOfflineFlashApi()
      .trigger('V4', 'factory-download.py', line => lines.push(line))
      .then(result => {
        resolved = true
        return result
      })
    await vi.waitFor(() => expect(lines).toEqual(['erase started']))
    expect(resolved).toBe(false)
    finish?.()

    await expect(pending).resolves.toEqual({
      status: 'completed',
      lines: ['erase started'],
    })
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/offline-download/trigger'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ model: 'V4', script_name: 'factory-download.py' }),
      }),
    )
  })
})
