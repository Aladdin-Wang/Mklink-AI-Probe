import { describe, expect, it } from 'vitest'
import { encodeRttTransmit, toHexPayload } from './rttTransmit'

describe('RTT transmit encoding', () => {
  it('encodes text as UTF-8 and appends the selected line ending', () => {
    expect(encodeRttTransmit('温度?', 'text', '\r\n')).toEqual(
      Uint8Array.from([...new TextEncoder().encode('温度?'), 0x0d, 0x0a]),
    )
  })

  it('accepts continuous or ASCII-whitespace-separated hex bytes', () => {
    expect(encodeRttTransmit('AA 55\t01', 'hex', '\n')).toEqual(
      Uint8Array.of(0xaa, 0x55, 0x01, 0x0a),
    )
    expect(encodeRttTransmit('00ff', 'hex', '')).toEqual(Uint8Array.of(0x00, 0xff))
  })

  it('rejects invalid and odd-length hex input', () => {
    expect(() => encodeRttTransmit('GG', 'hex', '')).toThrow('十六进制')
    expect(() => encodeRttTransmit('A', 'hex', '')).toThrow('偶数')
  })

  it.each([
    ['', []],
    ['\r', [0x0d]],
    ['\n', [0x0a]],
    ['\r\n', [0x0d, 0x0a]],
  ] as const)('appends the literal %j ending', (ending, suffix) => {
    expect(encodeRttTransmit('A', 'text', ending)).toEqual(Uint8Array.of(0x41, ...suffix))
  })

  it('serializes bytes as compact lowercase hex', () => {
    expect(toHexPayload(Uint8Array.of(0x00, 0x0a, 0xff))).toBe('000aff')
  })
})
