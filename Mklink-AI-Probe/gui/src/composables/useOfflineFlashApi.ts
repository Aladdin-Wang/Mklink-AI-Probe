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

async function responseError(response: Response): Promise<Error> {
  const payload = await response.json().catch(() => null)
  const detail = payload?.detail
  return new Error(typeof detail === 'string' ? detail : response.statusText)
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
