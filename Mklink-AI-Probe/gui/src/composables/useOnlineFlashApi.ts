import type {
  ImageInspection,
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

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(item => {
      if (item && typeof item === 'object' && 'msg' in item) return String(item.msg)
      return String(item)
    }).join('; ')
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String(detail.message)
  }
  return detail ? String(detail) : fallback
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
    throw new Error(errorMessage(payload, response.statusText))
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
  ): JobSubscription {
    const params = new URLSearchParams({ after: String(afterSequence) })
    const source = new EventSource(
      `${API_BASE}${ONLINE_FLASH_BASE}/jobs/${encoded(jobId)}/events?${params.toString()}`,
    )
    const receive = (event: Event) => {
      if (!(event instanceof MessageEvent) || typeof event.data !== 'string') {
        onEvent({ code: 'STREAM_ERROR', message: 'Event stream connection failed' })
        return
      }
      try {
        onEvent(JSON.parse(event.data) as JobStreamEvent)
      } catch {
        const error: JobStreamError = {
          code: 'STREAM_PARSE_ERROR',
          message: 'Event stream returned invalid JSON',
        }
        onEvent(error)
      }
    }
    for (const eventName of ['state', 'progress', 'log', 'error']) {
      source.addEventListener(eventName, receive)
    }
    return { close: () => source.close() }
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
