export interface VisibleRangeDestination {
  readonly times: Float64Array
  readonly values: Float32Array
}

export interface RingBufferSnapshot {
  readonly times: number[]
  readonly channels: number[][]
}

/**
 * Fixed-capacity, sample-major storage.
 *
 * `values[slot * channelCount + channel]` stores one channel value for a
 * sample. The backing arrays are allocated exactly once and oldest samples
 * are overwritten after the buffer fills.
 */
export class TypedRingBuffer {
  readonly timestamps: Float64Array
  readonly values: Float32Array
  readonly capacity: number
  readonly channelCount: number

  private startSlot = 0
  private sampleCount = 0

  constructor(capacity: number, channelCount: number) {
    if (!Number.isInteger(capacity) || capacity <= 0) {
      throw new RangeError('capacity must be a positive integer')
    }
    if (!Number.isInteger(channelCount) || channelCount <= 0) {
      throw new RangeError('channelCount must be a positive integer')
    }
    this.capacity = capacity
    this.channelCount = channelCount
    this.timestamps = new Float64Array(capacity)
    this.values = new Float32Array(capacity * channelCount)
  }

  get length(): number {
    return this.sampleCount
  }

  append(timestamp: number, channels: Float32Array): void {
    if (channels.length !== this.channelCount) {
      throw new RangeError(`expected ${this.channelCount} channel values`)
    }
    const slot = this.sampleCount < this.capacity
      ? (this.startSlot + this.sampleCount) % this.capacity
      : this.startSlot
    if (this.sampleCount < this.capacity) {
      this.sampleCount += 1
    } else {
      this.startSlot = (this.startSlot + 1) % this.capacity
    }
    this.timestamps[slot] = timestamp
    this.values.set(channels, slot * this.channelCount)
  }

  /** Append sample-major values: sample 0 channels, then sample 1 channels. */
  appendBatch(timestamps: Float64Array, sampleMajorValues: Float32Array): void {
    if (sampleMajorValues.length !== timestamps.length * this.channelCount) {
      throw new RangeError('sample-major values must contain channelCount values per timestamp')
    }
    for (let sample = 0; sample < timestamps.length; sample += 1) {
      const offset = sample * this.channelCount
      this.append(
        timestamps[sample],
        sampleMajorValues.subarray(offset, offset + this.channelCount),
      )
    }
  }

  visibleRangeLength(start: number, end: number): number {
    let count = 0
    for (let logical = 0; logical < this.sampleCount; logical += 1) {
      const slot = (this.startSlot + logical) % this.capacity
      const timestamp = this.timestamps[slot]
      if (timestamp >= start && timestamp <= end) count += 1
    }
    return count
  }

  copyVisibleRange(
    start: number,
    end: number,
    destination: VisibleRangeDestination,
  ): number {
    let count = 0
    for (let logical = 0; logical < this.sampleCount; logical += 1) {
      const slot = (this.startSlot + logical) % this.capacity
      const timestamp = this.timestamps[slot]
      if (timestamp < start || timestamp > end) continue
      if (
        count >= destination.times.length
        || (count + 1) * this.channelCount > destination.values.length
      ) {
        throw new RangeError('destination is too small for visible range')
      }
      destination.times[count] = timestamp
      const sourceOffset = slot * this.channelCount
      destination.values.set(
        this.values.subarray(sourceOffset, sourceOffset + this.channelCount),
        count * this.channelCount,
      )
      count += 1
    }
    return count
  }

  /** Test/debug helper. Rendering code must use copyVisibleRange instead. */
  snapshot(): RingBufferSnapshot {
    const times = new Array<number>(this.sampleCount)
    const channels = Array.from(
      { length: this.channelCount },
      () => new Array<number>(this.sampleCount),
    )
    for (let logical = 0; logical < this.sampleCount; logical += 1) {
      const slot = (this.startSlot + logical) % this.capacity
      times[logical] = this.timestamps[slot]
      for (let channel = 0; channel < this.channelCount; channel += 1) {
        channels[channel][logical] = this.values[slot * this.channelCount + channel]
      }
    }
    return { times, channels }
  }

  reset(): void {
    this.startSlot = 0
    this.sampleCount = 0
  }
}
