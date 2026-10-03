import { afterEach, expect, it, vi } from 'vitest'
import { useResourceStatus } from './useResourceStatus'

afterEach(() => vi.unstubAllGlobals())

it('reads the resource endpoint and releases the displayed owner when its lease ends', async () => {
  const lease = { owner: 'user:dashboard:rtt', acquired_at: 1, expires_at: null, is_user: true, is_ai: false }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ mklink_bridge: lease })))
    .mockResolvedValueOnce(new Response('{}'))
  vi.stubGlobal('fetch', fetchMock)
  const resources = useResourceStatus()
  await resources.refresh()
  expect(resources.getBridgeOwner()).toBe('user:dashboard:rtt')
  expect(resources.status.value.mklink_bridge).toEqual(lease)
  await resources.refresh()
  expect(resources.getBridgeOwner()).toBeNull()
  expect(fetchMock.mock.calls.map(call => call[0])).toEqual(['/api/resources/status', '/api/resources/status'])
})
