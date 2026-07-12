import type {
  ImageInspection,
  JobEvent,
  JobCreateResult,
  JobRequest,
  JobSnapshot,
  JobStreamError,
  JobStreamEvent,
  JobSubscription,
  PackCancelResult,
  PackOperationResponse,
  PackRemoveResult,
  PackStatus,
  PreviewPage,
  ProbeRecord,
  TargetRecord,
  TargetSearchOptions,
} from '../types/onlineFlash'

const API_BASE = import.meta.env.VITE_MKLINK_API || ''
const ONLINE_FLASH_BASE = '/api/online-flash'
const TERMINAL_STATES = new Set(['succeeded', 'failed', 'stopped'])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue)
  if (!isRecord(value)) return value
  return Object.fromEntries(
    Object.keys(value).sort().map(key => [key, stableValue(value[key])]),
  )
}

function stableJson(value: unknown): string | null {
  try {
    return JSON.stringify(stableValue(value)) ?? null
  } catch {
    return null
  }
}

function errorDetail(payload: unknown): unknown {
  if (isRecord(payload) && Object.prototype.hasOwnProperty.call(payload, 'detail')) {
    return payload.detail
  }
  return payload
}

function stringField(value: unknown, field: string): string | null {
  if (!isRecord(value) || typeof value[field] !== 'string') return null
  return value[field]
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(item => {
      const message = stringField(item, 'msg')
      return message ?? stableJson(item) ?? fallback
    }).join('; ')
  }
  if (isRecord(detail)) {
    const message = stringField(detail, 'message')
    if (message) return message
    const code = stringField(detail, 'code')
    const owner = stringField(detail, 'owner')
    const resource = stringField(detail, 'resource')
    if (code && owner && resource) return `${code}: ${resource} is owned by ${owner}`
    return stableJson(detail) ?? fallback
  }
  if (detail !== null && detail !== undefined) return String(detail)
  return fallback
}

export class OnlineFlashApiError extends Error {
  readonly status: number
  readonly code: string | null
  readonly owner: string | null
  readonly resource: string | null
  readonly detail: unknown

  constructor(status: number, fallback: string, payload: unknown) {
    const detail = errorDetail(payload)
    super(errorMessage(detail, fallback || `HTTP ${status}`))
    this.name = 'OnlineFlashApiError'
    this.status = status
    this.code = stringField(detail, 'code')
    this.owner = stringField(detail, 'owner')
    this.resource = stringField(detail, 'resource')
    this.detail = detail
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isMultipart = options.body instanceof FormData
  const headers = new Headers(options.headers)
  if (!isMultipart && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(`${API_BASE}${ONLINE_FLASH_BASE}${path}`, {
    ...options,
    headers,
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new OnlineFlashApiError(response.status, response.statusText, payload)
  }
  return response.json() as Promise<T>
}

function encoded(value: string): string {
  return encodeURIComponent(value)
}

export function useOnlineFlashApi() {
  function listProbes(): Promise<ProbeRecord[]> {
    return request('/probes')
  }

  function searchTargets(query = '', options: TargetSearchOptions = {}): Promise<TargetRecord[]> {
    const params = new URLSearchParams({ q: query })
    if (options.vendor !== undefined) params.set('vendor', options.vendor)
    if (options.installed !== undefined) params.set('installed', String(options.installed))
    if (options.limit !== undefined) params.set('limit', String(options.limit))
    return request(`/targets?${params.toString()}`)
  }

  function getPackStatus(): Promise<PackStatus> {
    return request('/packs/status')
  }

  function updatePackIndex(): Promise<PackOperationResponse> {
    return request('/packs/index/update', { method: 'POST' })
  }

  function installPack(partNumber: string): Promise<PackOperationResponse> {
    return request('/packs/install', {
      method: 'POST',
      body: JSON.stringify({ part_number: partNumber }),
    })
  }

  function importPack(file: File): Promise<PackOperationResponse> {
    const body = new FormData()
    body.append('file', file)
    return request('/packs/import', { method: 'POST', body })
  }

  function cancelPackOperation(): Promise<PackCancelResult> {
    return request('/packs/cancel', { method: 'POST' })
  }

  function removePack(packId: string, version: string): Promise<PackRemoveResult> {
    return request(`/packs/${encoded(packId)}/${encoded(version)}`, { method: 'DELETE' })
  }

  function inspectImage(
    file: File,
    partNumber: string,
    baseAddress?: number | string | null,
  ): Promise<ImageInspection> {
    const body = new FormData()
    body.append('file', file)
    body.append('part_number', partNumber)
    if (baseAddress !== undefined && baseAddress !== null) {
      body.append('base_address', String(baseAddress))
    }
    return request('/images/inspect', { method: 'POST', body })
  }

  function previewImage(imageId: string, offset = 0, length = 4096): Promise<PreviewPage> {
    const params = new URLSearchParams({ offset: String(offset), length: String(length) })
    return request(`/images/${encoded(imageId)}/preview?${params.toString()}`)
  }

  function createJob(job: JobRequest): Promise<JobCreateResult> {
    return request('/jobs', { method: 'POST', body: JSON.stringify(job) })
  }

  function getActiveJob(): Promise<JobSnapshot | null> {
    return request('/jobs/active')
  }

  function getJob(jobId: string): Promise<JobSnapshot> {
    return request(`/jobs/${encoded(jobId)}`)
  }

  function stopJob(jobId: string): Promise<JobSnapshot> {
    return request(`/jobs/${encoded(jobId)}/stop`, { method: 'POST' })
  }

  function subscribeJob(
    jobId: string,
    afterSequence: number,
    onEvent: (event: JobStreamEvent) => void,
    onError?: (error: JobStreamError) => void,
  ): JobSubscription {
    const params = new URLSearchParams({ after: String(afterSequence) })
    const source = new EventSource(
      `${API_BASE}${ONLINE_FLASH_BASE}/jobs/${encoded(jobId)}/events?${params.toString()}`,
    )
    let lastSequence = afterSequence
    let closed = false
    const close = () => {
      if (closed) return
      closed = true
      source.close()
    }
    const reportError = (error: JobStreamError) => {
      if (onError) onError(error)
      else onEvent(error)
    }
    const receive = (event: Event) => {
      if (closed) return
      if (!(event instanceof MessageEvent) || typeof event.data !== 'string') {
        close()
        reportError({ code: 'STREAM_ERROR', message: 'Event stream connection failed' })
        return
      }
      let parsed: JobStreamEvent
      try {
        parsed = JSON.parse(event.data) as JobStreamEvent
      } catch {
        const error: JobStreamError = {
          code: 'STREAM_PARSE_ERROR',
          message: 'Event stream returned invalid JSON',
        }
        close()
        reportError(error)
        return
      }
      if (isRecord(parsed) && typeof parsed.sequence === 'number') {
        const jobEvent = parsed as JobEvent
        if (jobEvent.sequence <= lastSequence) return
        lastSequence = jobEvent.sequence
        if (event.type === 'error' || (jobEvent.state && TERMINAL_STATES.has(jobEvent.state))) {
          try {
            onEvent(jobEvent)
          } finally {
            close()
          }
          return
        }
        onEvent(jobEvent)
        return
      }
      if (event.type === 'error') {
        try {
          onEvent(parsed)
        } finally {
          close()
        }
        return
      }
      onEvent(parsed)
    }
    for (const eventName of ['state', 'progress', 'log', 'error']) {
      source.addEventListener(eventName, receive)
    }
    return { close }
  }

  return {
    listProbes,
    searchTargets,
    getPackStatus,
    updatePackIndex,
    installPack,
    importPack,
    cancelPackOperation,
    removePack,
    inspectImage,
    previewImage,
    createJob,
    getActiveJob,
    getJob,
    stopJob,
    subscribeJob,
  }
}
