export interface MinMaxEnvelope {
  /** First finite timestamp represented by each occupied pixel column. */
  readonly times: Float64Array
  readonly min: Float32Array
  readonly max: Float32Array
}

const EMPTY_ENVELOPE: MinMaxEnvelope = Object.freeze({
  times: new Float64Array(),
  min: new Float32Array(),
  max: new Float32Array(),
})

/**
 * Reduce one visible, timestamp-ordered sample window to per-pixel extrema.
 *
 * Bounds are inclusive. Non-finite samples are ignored. A zero-duration
 * range is valid and maps matching samples to one column. Runtime and scratch
 * storage are O(input visible samples + pixelWidth); no point objects are
 * allocated in the sample loop.
 */
export function minMaxEnvelope(
  times: Float64Array,
  values: Float32Array,
  start: number,
  end: number,
  pixelWidth: number,
): MinMaxEnvelope {
  if (times.length !== values.length) {
    throw new RangeError('times and values must have the same length')
  }
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) {
    throw new RangeError('visible range must be finite and end at or after start')
  }
  if (!Number.isInteger(pixelWidth) || pixelWidth <= 0) {
    throw new RangeError('pixelWidth must be a positive integer')
  }
  if (times.length === 0) return EMPTY_ENVELOPE

  const columnTimes = new Float64Array(pixelWidth)
  const minima = new Float32Array(pixelWidth)
  const maxima = new Float32Array(pixelWidth)
  const occupied = new Uint8Array(pixelWidth)
  const duration = end - start
  if (!Number.isFinite(duration)) {
    throw new RangeError('visible range duration must be finite')
  }

  for (let index = 0; index < times.length; index += 1) {
    const timestamp = times[index]
    const value = values[index]
    if (
      !Number.isFinite(timestamp)
      || !Number.isFinite(value)
      || timestamp < start
      || timestamp > end
    ) continue

    const column = duration === 0
      ? 0
      : Math.min(pixelWidth - 1, Math.floor(((timestamp - start) / duration) * pixelWidth))
    if (occupied[column] === 0) {
      occupied[column] = 1
      columnTimes[column] = timestamp
      minima[column] = value
      maxima[column] = value
    } else {
      if (value < minima[column]) minima[column] = value
      if (value > maxima[column]) maxima[column] = value
    }
  }

  let columnCount = 0
  for (let column = 0; column < pixelWidth; column += 1) {
    if (occupied[column] !== 0) columnCount += 1
  }
  if (columnCount === 0) return EMPTY_ENVELOPE

  const outputTimes = new Float64Array(columnCount)
  const outputMin = new Float32Array(columnCount)
  const outputMax = new Float32Array(columnCount)
  let outputIndex = 0
  for (let column = 0; column < pixelWidth; column += 1) {
    if (occupied[column] === 0) continue
    outputTimes[outputIndex] = columnTimes[column]
    outputMin[outputIndex] = minima[column]
    outputMax[outputIndex] = maxima[column]
    outputIndex += 1
  }
  return { times: outputTimes, min: outputMin, max: outputMax }
}
