import type {
  OfflineAlgorithmCandidate,
  OfflineConfigPayload,
  OfflineDeployResult,
  OfflineDiskStatus,
  OfflineModelResult,
  OfflinePreview,
  OfflineTriggerResult,
} from '../types/offlineFlash'

const API_BASE = import.meta.env.VITE_MKLINK_API || ''
const BASE = `${API_BASE}/api/offline-download`

function resourceOwnerLabel(owner: unknown): string {
  if (typeof owner !== 'string') return '其他功能'
  const name = owner.split(':').at(-1)?.toLowerCase()
  if (name === 'superwatch') return 'SuperWatch'
  if (name === 'rtt') return 'RTT View'
  if (name === 'systemview') return 'RTOS Trace'
  if (name === 'vofa') return 'VOFA+'
  return owner
}

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const value = detail as Record<string, unknown>
    if (value.code === 'PROBE_BUSY') {
      return `探针正被 ${resourceOwnerLabel(value.conflict_owner ?? value.owner)} 占用，请先停止该功能后重试。`
    }
    if (typeof value.message === 'string') return value.message
    try { return JSON.stringify(value) } catch { return fallback }
  }
  return fallback
}

async function responseError(response: Response): Promise<Error> {
  const payload = await response.json().catch(() => null)
  return new Error(detailMessage(payload?.detail, response.statusText || `HTTP ${response.status}`))
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers: options?.body instanceof FormData
      ? options.headers
      : { 'Content-Type': 'application/json', ...options?.headers },
  })
  if (!response.ok) throw await responseError(response)
  return response.json()
}

export function useOfflineFlashApi() {
  function getStatus(): Promise<OfflineDiskStatus> {
    return request('/status')
  }

  function detectModel(port?: string): Promise<OfflineModelResult> {
    return request('/detect-model', {
      method: 'POST',
      body: JSON.stringify(port ? { port } : {}),
    })
  }

  function listAlgorithms(partNumber: string): Promise<OfflineAlgorithmCandidate[]> {
    return request(`/algorithms?part_number=${encodeURIComponent(partNumber)}`)
  }

  function preview(config: OfflineConfigPayload): Promise<OfflinePreview> {
    return request('/preview', { method: 'POST', body: JSON.stringify(config) })
  }

  function deploy(
    config: OfflineConfigPayload,
    firmwareFiles: File[],
    flmFiles: File[],
  ): Promise<OfflineDeployResult> {
    const body = new FormData()
    body.append('config_json', JSON.stringify(config))
    firmwareFiles.forEach(file => body.append('firmware_files', file, file.name))
    flmFiles.forEach(file => body.append('flm_files', file, file.name))
    return request('/deploy', { method: 'POST', body })
  }

  function trigger(port?: string): Promise<OfflineTriggerResult> {
    return request('/trigger', {
      method: 'POST',
      body: JSON.stringify(port ? { port } : {}),
    })
  }

  return { getStatus, detectModel, listAlgorithms, preview, deploy, trigger }
}
