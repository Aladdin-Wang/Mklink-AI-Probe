import type { RttLineEnding, RttTransmitMode } from './desktopSettings'

const encoder = new TextEncoder()

function endingBytes(lineEnding: RttLineEnding): Uint8Array {
  return encoder.encode(lineEnding)
}

function appendEnding(payload: Uint8Array, lineEnding: RttLineEnding): Uint8Array {
  const suffix = endingBytes(lineEnding)
  const result = new Uint8Array(payload.length + suffix.length)
  result.set(payload)
  result.set(suffix, payload.length)
  return result
}

export function encodeRttTransmit(
  text: string,
  mode: RttTransmitMode,
  lineEnding: RttLineEnding,
): Uint8Array {
  if (mode === 'text') return appendEnding(encoder.encode(text), lineEnding)

  const compact = text.replace(/[\x09-\x0d\x20]/g, '')
  if (!/^[0-9a-f]*$/i.test(compact)) {
    throw new Error('HEX 输入只能包含十六进制字符和空白')
  }
  if (compact.length % 2 !== 0) {
    throw new Error('HEX 输入必须包含偶数个字符')
  }

  const payload = new Uint8Array(compact.length / 2)
  for (let index = 0; index < compact.length; index += 2) {
    payload[index / 2] = Number.parseInt(compact.slice(index, index + 2), 16)
  }
  return appendEnding(payload, lineEnding)
}

export function toHexPayload(bytes: Uint8Array): string {
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}
