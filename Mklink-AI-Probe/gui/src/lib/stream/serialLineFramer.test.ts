import { describe, expect, it } from 'vitest'
import { SerialLineFramer } from './serialLineFramer'

const encoder = new TextEncoder()
describe('serial text line framing', () => {
  it('shows partial text now and joins arbitrary chunk boundaries, including split CRLF', () => {
    const input = 'UART5 seq=00025058 tick=2900384 DATA\r\nnext\nlast'
    for (let split = 1; split < input.length; split++) {
      const framer = new SerialLineFramer()
      const rows: string[] = []
      const first = framer.frame(encoder.encode(input.slice(0, split)), 'RX')
      expect(first.length).toBeGreaterThan(0)
      const all = [...first, ...framer.frame(encoder.encode(input.slice(split)), 'RX')]
      for (const fragment of all) {
        const text = new TextDecoder().decode(fragment.bytes)
        if (fragment.continuesPrevious) rows[rows.length - 1] += text
        else rows.push(text)
      }
      expect(rows).toEqual(['UART5 seq=00025058 tick=2900384 DATA\r\n', 'next\n', 'last'])
    }
  })

  it('preserves bare CR, empty lines, direction order and every byte', () => {
    const framer = new SerialLineFramer()
    expect(framer.frame(encoder.encode('a\rb\n\n'), 'RX').map(f => new TextDecoder().decode(f.bytes)))
      .toEqual(['a\r', 'b\n', '\n'])
    expect(framer.frame(encoder.encode('partial'), 'RX')[0]?.continuesPrevious).toBe(false)
    expect(framer.frame(encoder.encode('send'), 'TX')[0]?.continuesPrevious).toBe(false)
    expect(framer.frame(encoder.encode('reply'), 'RX')[0]?.continuesPrevious).toBe(false)
    expect(framer.frame(encoder.encode('tail'), 'RX')[0]?.continuesPrevious).toBe(true)
  })

  it('bounds a never-ending line without holding short tails', () => {
    const framer = new SerialLineFramer()
    const first = framer.frame(new Uint8Array(4095).fill(65), 'RX')
    expect(first[0]?.bytes.length).toBe(4095)
    const next = framer.frame(Uint8Array.of(66, 67), 'RX')
    expect(next.map(f => [f.bytes.length, f.continuesPrevious])).toEqual([[1, true], [1, false]])
  })
})
