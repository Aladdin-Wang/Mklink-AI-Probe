import { expect, it, vi } from 'vitest'
import { navigateToRuntime } from './runtimeNavigation'

it('deduplicates the HTTP and presence notifications without losing the login fragment', () => {
  const replace = vi.spyOn(window.location, 'replace').mockImplementation(() => {})
  try {
    navigateToRuntime('http://127.0.0.1:8766/_runtime/open#test-token')
    navigateToRuntime()
    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenCalledWith('http://127.0.0.1:8766/_runtime/open?runtime_transition=probe#test-token')
  } finally { replace.mockRestore() }
})
