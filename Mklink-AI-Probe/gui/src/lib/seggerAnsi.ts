const CSI = '\x1b['

function normalizeCompleteSequences(text: string): string {
  return text
    .replace(/\x1b\[2;(3[0-7])m/g, `${CSI}22;$1m`)
    .replace(/\x1b\[4;4([0-7])m/g, (_match, color: string) => (
      `${CSI}${100 + Number(color)}m`
    ))
    .replace(/\x1b\[2J/g, `${CSI}2J${CSI}H`)
}

function incompleteCsiStart(text: string): number {
  for (let index = 0; index < text.length; index += 1) {
    if (text.charCodeAt(index) !== 0x1b) continue
    if (index + 1 >= text.length) return index
    if (text[index + 1] !== '[') continue
    let cursor = index + 2
    while (cursor < text.length) {
      const code = text.charCodeAt(cursor)
      if (code >= 0x40 && code <= 0x7e) break
      cursor += 1
    }
    if (cursor >= text.length) return index
    index = cursor
  }
  return -1
}

export class SeggerAnsiNormalizer {
  private pending = ''

  push(chunk: string): string {
    const combined = this.pending + chunk
    this.pending = ''
    const pendingAt = incompleteCsiStart(combined)
    if (pendingAt < 0) return normalizeCompleteSequences(combined)
    this.pending = combined.slice(pendingAt)
    return normalizeCompleteSequences(combined.slice(0, pendingAt))
  }

  reset(): void {
    this.pending = ''
  }
}
