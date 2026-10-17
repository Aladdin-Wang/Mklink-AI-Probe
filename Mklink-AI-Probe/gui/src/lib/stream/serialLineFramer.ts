/** Publish partial lines immediately; transport chunks never imply a text newline. */
export class SerialLineFramer {
  private direction = ''
  private length = 0
  private open = false
  private afterCR = false

  frame(bytes: Uint8Array, direction: 'RX' | 'TX') {
    if (direction !== this.direction || direction === 'TX') {
      this.direction = direction
      this.length = 0
      this.open = this.afterCR = false
    }
    const fragments: Array<{ bytes: Uint8Array; continuesPrevious: boolean }> = []
    let offset = 0
    while (offset < bytes.length) {
      if (this.afterCR && bytes[offset] === 10) {
        fragments.push({ bytes: bytes.subarray(offset, offset + 1), continuesPrevious: true })
        offset++
        this.afterCR = false
        continue
      }
      this.afterCR = false
      const start = offset
      const continuesPrevious = this.open
      const budget = 4096 - this.length
      while (offset < bytes.length && offset - start < budget) {
        const byte = bytes[offset++]
        if (byte === 10 || byte === 13) break
      }
      this.length += offset - start
      const last = bytes[offset - 1]
      this.afterCR = last === 13
      this.open = last !== 10 && last !== 13 && this.length < 4096
      if (!this.open) this.length = 0
      fragments.push({ bytes: bytes.subarray(start, offset), continuesPrevious })
    }
    return fragments
  }
}
