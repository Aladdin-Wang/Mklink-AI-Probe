import { describe, expect, it } from 'vitest'
import { minMaxEnvelope } from './minMaxEnvelope'

describe('minMaxEnvelope', () => {
  it('keeps a one-sample spike inside a crowded pixel column', () => {
    const envelope = minMaxEnvelope(
      Float64Array.from([0, 1, 2, 3, 4, 5]),
      Float32Array.from([0, 0, 100, 0, 0, 0]),
      0,
      5,
      2,
    )

    expect(Math.max(...envelope.max)).toBe(100)
    expect(envelope.min.length + envelope.max.length).toBeLessThanOrEqual(4)
    expect(envelope.times).toBeInstanceOf(Float64Array)
    expect(envelope.min).toBeInstanceOf(Float32Array)
    expect(envelope.max).toBeInstanceOf(Float32Array)
  })

  it('uses inclusive visible bounds and groups repeated timestamps', () => {
    const envelope = minMaxEnvelope(
      Float64Array.of(0, 1, 1, 1, 2, 3),
      Float32Array.of(99, 4, -2, 8, 6, 99),
      1,
      2,
      2,
    )

    expect(Array.from(envelope.times)).toEqual([1, 2])
    expect(Array.from(envelope.min)).toEqual([-2, 6])
    expect(Array.from(envelope.max)).toEqual([8, 6])
  })

  it('returns empty typed arrays for empty input or no finite visible values', () => {
    const empty = minMaxEnvelope(new Float64Array(), new Float32Array(), 0, 1, 10)
    const invalid = minMaxEnvelope(
      Float64Array.of(0, 1, 2),
      Float32Array.of(Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY),
      0,
      2,
      10,
    )

    for (const envelope of [empty, invalid]) {
      expect(envelope.times).toBeInstanceOf(Float64Array)
      expect(envelope.min).toBeInstanceOf(Float32Array)
      expect(envelope.max).toBeInstanceOf(Float32Array)
      expect(envelope.times.length).toBe(0)
      expect(envelope.min.length).toBe(0)
      expect(envelope.max.length).toBe(0)
    }
  })

  it('keeps a single sample and handles a zero-duration range', () => {
    const envelope = minMaxEnvelope(
      Float64Array.of(2),
      Float32Array.of(7),
      2,
      2,
      1,
    )

    expect(Array.from(envelope.times)).toEqual([2])
    expect(Array.from(envelope.min)).toEqual([7])
    expect(Array.from(envelope.max)).toEqual([7])
  })

  it('rejects mismatched arrays, invalid ranges, and invalid pixel widths', () => {
    expect(() => minMaxEnvelope(Float64Array.of(1), new Float32Array(), 0, 1, 1))
      .toThrow(/same length/)
    expect(() => minMaxEnvelope(Float64Array.of(1), Float32Array.of(1), 2, 1, 1))
      .toThrow(/range/)
    expect(() => minMaxEnvelope(Float64Array.of(1), Float32Array.of(1), 0, 1, 0))
      .toThrow(/pixelWidth/)
    expect(() => minMaxEnvelope(Float64Array.of(1), Float32Array.of(1), 0, 1, 1.5))
      .toThrow(/pixelWidth/)
    expect(() => minMaxEnvelope(Float64Array.of(1), Float32Array.of(1), Number.NaN, 1, 1))
      .toThrow(/range/)
  })

  it('rejects finite endpoints whose duration overflows', () => {
    expect(() => minMaxEnvelope(
      Float64Array.of(-Number.MAX_VALUE, Number.MAX_VALUE),
      Float32Array.of(1, 2),
      -Number.MAX_VALUE,
      Number.MAX_VALUE,
      2,
    )).toThrow(/duration/)
  })

  it('ignores samples with non-finite timestamps or values', () => {
    const envelope = minMaxEnvelope(
      Float64Array.of(0, Number.NaN, 1, Number.POSITIVE_INFINITY, 2),
      Float32Array.of(1, 100, 2, 100, 3),
      0,
      2,
      3,
    )

    expect(Array.from(envelope.min)).toEqual([1, 2, 3])
    expect(Array.from(envelope.max)).toEqual([1, 2, 3])
  })
})
