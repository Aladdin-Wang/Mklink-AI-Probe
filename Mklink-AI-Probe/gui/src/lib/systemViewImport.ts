export interface SystemViewImportResult {
  events: number
  skipped: number
  parseErrors: number
  session: Record<string, unknown> | null
  summary: Record<string, unknown> | null
}

export interface SystemViewImportOptions {
  stream: ReadableStream<Uint8Array>
  batchSize?: number
  onBatch: (events: any[]) => void | Promise<void>
  onSession?: (record: Record<string, unknown>) => void | Promise<void>
  onSummary?: (record: Record<string, unknown>) => void | Promise<void>
  onProgress?: (bytesRead: number) => void | Promise<void>
  signal?: AbortSignal
}

const DEFAULT_BATCH_SIZE = 1000

export async function importSystemViewJsonl(
  options: SystemViewImportOptions,
): Promise<SystemViewImportResult> {
  const batchSize = normalizeBatchSize(options.batchSize)
  const result: SystemViewImportResult = {
    events: 0,
    skipped: 0,
    parseErrors: 0,
    session: null,
    summary: null,
  }
  const batch: any[] = []
  const reader = options.stream.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  let bytesRead = 0

  async function flushBatch() {
    if (!batch.length) return
    throwIfAborted(options.signal)
    const next = batch.splice(0, batch.length)
    await options.onBatch(next)
    throwIfAborted(options.signal)
    await yieldToBrowser()
    throwIfAborted(options.signal)
  }

  async function processLine(rawLine: string) {
    throwIfAborted(options.signal)
    const line = rawLine.replace(/\r$/, '').replace(/^\uFEFF/, '').trim()
    if (!line) return

    let record: unknown
    try {
      record = JSON.parse(line)
    } catch {
      result.parseErrors += 1
      return
    }
    if (!isRecord(record)) {
      result.skipped += 1
      return
    }

    if (record.type === 'session') {
      result.session = record
      await options.onSession?.(record)
      return
    }
    if (record.type === 'summary') {
      result.summary = record
      await options.onSummary?.(record)
      return
    }
    if (record.type !== 'event' || typeof record.kind !== 'string') {
      result.skipped += 1
      return
    }

    batch.push(record)
    result.events += 1
    if (batch.length >= batchSize) await flushBatch()
  }

  try {
    while (true) {
      throwIfAborted(options.signal)
      const { done, value } = await reader.read()
      if (done) break
      bytesRead += value.byteLength
      await options.onProgress?.(bytesRead)
      pending += decoder.decode(value, { stream: true })
      const lines = pending.split('\n')
      pending = lines.pop() ?? ''
      for (const line of lines) await processLine(line)
    }

    pending += decoder.decode()
    if (pending) await processLine(pending)
    await flushBatch()
    return result
  } finally {
    reader.releaseLock()
  }
}

function normalizeBatchSize(value: number | undefined): number {
  if (!Number.isFinite(value) || !value || value <= 0) return DEFAULT_BATCH_SIZE
  return Math.floor(value)
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function throwIfAborted(signal: AbortSignal | undefined) {
  if (signal?.aborted) throw new Error('SystemView import aborted')
}

function yieldToBrowser(): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, 0))
}
