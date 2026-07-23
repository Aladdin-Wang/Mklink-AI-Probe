import { describe, expect, it } from 'vitest'
import { TypedRingBuffer } from './typedRingBuffer'

describe('TypedRingBuffer', () => {
  it('overwrites the oldest sample while keeping fixed typed-array storage', () => {
    const buffer = new TypedRingBuffer(3, 1)
    const timestamps = buffer.timestamps
    const values = buffer.values

    buffer.append(1, Float32Array.of(10))
    buffer.append(2, Float32Array.of(20))
    buffer.append(3, Float32Array.of(30))
    buffer.append(4, Float32Array.of(40))

    expect(buffer.snapshot()).toEqual({ times: [2, 3, 4], channels: [[20, 30, 40]] })
    expect(buffer.timestamps).toBe(timestamps)
    expect(buffer.values).toBe(values)
    expect(buffer.capacity).toBe(3)
  })

  it('stores sample-major multi-channel input without crossing channel boundaries', () => {
    const buffer = new TypedRingBuffer(3, 2)

    buffer.appendBatch(
      Float64Array.of(10, 20),
      Float32Array.of(1, 101, 2, 102),
    )

    expect(buffer.snapshot()).toEqual({
      times: [10, 20],
      channels: [[1, 2], [101, 102]],
    })
  })

  it('copies only the requested visible range into caller-owned typed arrays', () => {
    const buffer = new TypedRingBuffer(5, 2)
    buffer.appendBatch(
      Float64Array.of(1, 2, 3, 4, 5),
      Float32Array.of(10, 100, 20, 200, 30, 300, 40, 400, 50, 500),
    )
    const destination = {
      times: new Float64Array(4),
      values: new Float32Array(8),
    }

    const copied = buffer.copyVisibleRange(2, 4, destination)

    expect(copied).toBe(3)
    expect(Array.from(destination.times.slice(0, copied))).toEqual([2, 3, 4])
    expect(Array.from(destination.values.slice(0, copied * 2))).toEqual([
      20, 200, 30, 300, 40, 400,
    ])
    expect(buffer.visibleRangeLength(2, 4)).toBe(3)
  })

  it('validates configuration, sample layout, and destination capacity', () => {
    expect(() => new TypedRingBuffer(0, 1)).toThrow(/capacity/)
    expect(() => new TypedRingBuffer(2, 0)).toThrow(/channel/)

    const buffer = new TypedRingBuffer(2, 2)
    expect(() => buffer.append(1, Float32Array.of(1))).toThrow(/channel/)
    expect(() => buffer.appendBatch(Float64Array.of(1, 2), Float32Array.of(1, 2)))
      .toThrow(/sample-major/)
    buffer.appendBatch(Float64Array.of(1, 2), Float32Array.of(1, 2, 3, 4))
    expect(() => buffer.copyVisibleRange(0, 10, {
      times: new Float64Array(1),
      values: new Float32Array(2),
    })).toThrow(/destination/)
  })

  it('selects per-channel min/max points with one bounded shared logical index set', () => {
    const buffer = new TypedRingBuffer(10, 2)
    buffer.appendBatch(
      Float64Array.from({ length: 10 }, (_, index) => index),
      Float32Array.from({ length: 20 }, (_, index) => {
        const sample = Math.floor(index / 2)
        const channel = index % 2
        if (channel === 0 && sample === 1) return 100
        if (channel === 0 && sample === 2) return -100
        if (channel === 1 && sample === 6) return 200
        if (channel === 1 && sample === 8) return -200
        return sample
      }),
    )

    const selected = buffer.selectMinMaxEnvelope(0, 9, 2)
    const indices = Array.from(selected.logicalIndices.slice(0, selected.pointCount))
    const offsets = Array.from(selected.channelOffsets)

    expect(selected.candidateSampleCount).toBe(10)
    expect(selected.pointCount).toBeLessThanOrEqual(2 * 2 * 2)
    expect(offsets).toHaveLength(3)
    expect(indices.slice(offsets[0], offsets[1])).toEqual(expect.arrayContaining([1, 2]))
    expect(indices.slice(offsets[1], offsets[2])).toEqual(expect.arrayContaining([6, 8]))
  })

  it('uses logical-order binary search and remains bounded after wrap', () => {
    const buffer = new TypedRingBuffer(5, 1)
    buffer.appendBatch(
      Float64Array.of(1, 2, 3, 4, 5, 6, 7),
      Float32Array.of(1, 2, 3, 40, -50, 6, 7),
    )

    const selected = buffer.selectMinMaxEnvelope(4, 7, 1)
    const indices = Array.from(selected.logicalIndices.slice(0, selected.pointCount))

    expect(selected.candidateSampleCount).toBe(4)
    expect(selected.pointCount).toBeLessThanOrEqual(2)
    expect(indices.map(index => buffer.valueAt(index, 0))).toEqual([40, -50])
  })
})
