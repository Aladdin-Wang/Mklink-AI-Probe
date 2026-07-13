import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('SvTimeline prefiltered input contract', () => {
  it('accepts prefiltered intervals without slicing or sorting a 50k source per frame', () => {
    const source = readFileSync('src/lib/svTimeline.js', 'utf8')
    expect(source).toMatch(/setPrefilteredIntervals\(/)
    const start = source.indexOf('setPrefilteredIntervals(')
    const method = source.slice(start, source.indexOf('\n  _mergeTasks', start))
    expect(method).not.toMatch(/\.slice\(/)
    expect(method).not.toMatch(/\.sort\(/)
    expect(method).not.toMatch(/_filterContinuous/)
  })
})
