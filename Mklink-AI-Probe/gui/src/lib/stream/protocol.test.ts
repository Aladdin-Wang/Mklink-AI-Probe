import { describe, expect, it } from 'vitest'
import { decodeFrame } from './protocol'

const GOLDEN_HEX =
  '4d4b535401020024070000000900000000000000e80300000000000002000000080000000000803f000000c0'
const MAX_PAYLOAD_SIZE = 4 * 1024 * 1024

function hexBytes(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2)
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16)
  }
  return bytes
}

function golden(): Uint8Array {
  return hexBytes(GOLDEN_HEX)
}

describe('decodeFrame', () => {
  it('decodes the Python v1 golden vector', () => {
    const frame = decodeFrame(golden().buffer)

    expect(frame.streamType).toBe(2)
    expect(frame.flags).toBe(0)
    expect(frame.streamId).toBe(7)
    expect(frame.sequence).toBe(9n)
    expect(frame.timestampNs).toBe(1000n)
    expect(frame.itemCount).toBe(2)
    expect(Array.from(new Float32Array(frame.payload))).toEqual([1, -2])
  })

  it.each([
    [0, '58', /magic/],
    [4, '02', /version/],
    [5, '63', /stream type/],
    [7, '23', /header size/],
  ] as const)('rejects an invalid header byte at offset %i', (offset, replacement, error) => {
    const bytes = golden()
    bytes[offset] = Number.parseInt(replacement, 16)

    expect(() => decodeFrame(bytes.buffer)).toThrow(error)
  })

  it.each([7, 9])('rejects a declared payload length of %i', declaredLength => {
    const bytes = golden()
    new DataView(bytes.buffer).setUint32(32, declaredLength, true)

    expect(() => decodeFrame(bytes.buffer)).toThrow(/payload length/)
  })

  it('rejects a payload larger than four MiB before reading it', () => {
    const bytes = golden().slice(0, 36)
    new DataView(bytes.buffer).setUint32(32, MAX_PAYLOAD_SIZE + 1, true)

    expect(() => decodeFrame(bytes.buffer)).toThrow(/payload.*4 MiB/)
  })
})
