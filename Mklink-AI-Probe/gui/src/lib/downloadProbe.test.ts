import { afterEach, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { selectDownloadProbe, useDownloadViewKey } from './downloadProbe'

afterEach(() => vi.unstubAllGlobals())

it.each(['before', 'after'])('preserves a download form when polling observes its reservation %s the response', async timing => {
  const generation = ref(10)
  const scope = effectScope()
  const key = scope.run(() => useDownloadViewKey(generation))!
  let finish!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
  const selection = selectDownloadProbe('dap', true)
  if (timing === 'before') generation.value = 11
  await nextTick()
  expect(key.value).toBe(10)
  finish(new Response(JSON.stringify({ probe_id: 'physical', device_generation: 11 })))
  expect(await selection).toEqual({ 'X-MKLink-Probe': 'physical', 'X-MKLink-Device-Generation': '11' })
  generation.value = 11
  await nextTick()
  expect(key.value).toBe(10)
  generation.value = 12 // An explicit disconnect or another client changes device.
  await nextTick()
  expect(key.value).toBe(12)
  scope.stop()
})

it('does not hide an external switch when reservation fails', async () => {
  const generation = ref(20)
  const scope = effectScope()
  const key = scope.run(() => useDownloadViewKey(generation))!
  vi.stubGlobal('fetch', vi.fn(async () => {
    generation.value = 21
    return new Response(JSON.stringify({ detail: 'Probe busy' }), { status: 409 })
  }))
  await expect(selectDownloadProbe('busy')).rejects.toThrow('Probe busy')
  await nextTick()
  expect(key.value).toBe(21)
  scope.stop()
})
