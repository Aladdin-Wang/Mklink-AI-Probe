import { describe, expect, it } from 'vitest'
import { fitWatchSections } from './useWatchSectionSizes'

describe('SuperWatch section height allocation', () => {
  it('keeps manual heights and gives the remaining space to search', () => {
    const result = fitWatchSections(700, { signals: false, pinned: false, all: false }, { signals: 250, pinned: 200 })
    expect(result.sizes).toEqual({ signals: 250, pinned: 200, all: 238 })
    expect(result.resizable).toEqual(['signals', 'pinned'])
  })
  it('fits oversized preferences without losing a usable search viewport', () => {
    const result = fitWatchSections(400, { signals: false, pinned: false, all: false }, { signals: 1000, pinned: 800 })
    expect(result.sizes.signals).toBeGreaterThanOrEqual(80)
    expect(result.sizes.pinned).toBeGreaterThanOrEqual(76)
    expect(result.sizes.all).toBeGreaterThanOrEqual(180)
    expect(Object.values(result.sizes).reduce((a, b) => a + b, 12)).toBe(400)
  })
  it('lets the outer region scroll when even minimum sizes do not fit', () => {
    const result = fitWatchSections(200, { signals: false, pinned: false, all: false }, { signals: 300, pinned: 200 })
    expect(result.sizes).toEqual({ signals: 80, pinned: 76, all: 180 })
  })
  it('reclaims folded space and leaves a divider only between open sections', () => {
    expect(fitWatchSections(700, { signals: true, pinned: true, all: false }, { signals: 250, pinned: 200 }))
      .toEqual({ sizes: { signals: 34, pinned: 34, all: 632 }, resizable: [] })
    expect(fitWatchSections(700, { signals: false, pinned: false, all: true }, { signals: 250, pinned: 200 }))
      .toEqual({ sizes: { signals: 250, pinned: 410, all: 34 }, resizable: ['signals'] })
  })
})
