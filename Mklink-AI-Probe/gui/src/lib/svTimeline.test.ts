import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { exactTickFromOffset } from './svTimeline'

describe('SvTimeline prefiltered input contract', () => {
  it('adds relative plot offsets to an exact BigInt origin', () => {
    expect(exactTickFromOffset(9_007_199_254_740_993n, 1)).toBe('9007199254740994')
  })

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
