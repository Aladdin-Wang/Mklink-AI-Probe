import { describe, expect, it, vi } from 'vitest'
import { importSystemViewJsonl } from './systemViewImport'

describe('importSystemViewJsonl', () => {
  it('streams event batches and reports byte progress for offline replay', async () => {
    const text = [
      JSON.stringify({ type: 'session', cpu_freq: 360_000_000 }),
      JSON.stringify({ type: 'event', kind: 'task_start_exec', task_id: 1, t_us: 10 }),
      JSON.stringify({ type: 'event', kind: 'task_stop_exec', task_id: 1, t_us: 20 }),
      JSON.stringify({ type: 'summary', events: 2 }),
      '',
    ].join('\n')
    const bytes = new TextEncoder().encode(text)
    const progress = vi.fn()
    const batches: any[][] = []

    const result = await importSystemViewJsonl({
      stream: new Blob([bytes]).stream(),
      batchSize: 1,
      onProgress: progress,
      onBatch: batch => { batches.push(batch) },
    })

    expect(result.events).toBe(2)
    expect(batches).toHaveLength(2)
    expect(progress).toHaveBeenLastCalledWith(bytes.byteLength)
  })
})
