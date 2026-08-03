import { describe, expect, it } from 'vitest'
import { SeggerAnsiNormalizer } from './seggerAnsi'

describe('SeggerAnsiNormalizer', () => {
  it('maps SEGGER normal foreground, bright background, and clear semantics', () => {
    const normalizer = new SeggerAnsiNormalizer()
    expect(normalizer.push('\x1b[2;31mred\x1b[4;44mblue\x1b[2J')).toBe(
      '\x1b[22;31mred\x1b[104mblue\x1b[2J\x1b[H',
    )
  })

  it('preserves standard ANSI and completes SEGGER sequences across chunks', () => {
    const normalizer = new SeggerAnsiNormalizer()
    expect(normalizer.push('start\x1b[2;')).toBe('start')
    expect(normalizer.push('33mwarn\x1b[0m')).toBe('\x1b[22;33mwarn\x1b[0m')
    expect(normalizer.push('\x1b[2K\r')).toBe('\x1b[2K\r')
  })

  it('drops an incomplete sequence when reset', () => {
    const normalizer = new SeggerAnsiNormalizer()
    expect(normalizer.push('\x1b[')).toBe('')
    normalizer.reset()
    expect(normalizer.push('plain')).toBe('plain')
  })
})
