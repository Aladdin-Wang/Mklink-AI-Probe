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
})
