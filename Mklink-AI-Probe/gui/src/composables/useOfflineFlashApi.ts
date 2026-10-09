import type {
  OfflineAlgorithmCandidate,
  OfflineConfigPayload,
  OfflineDeployResult,
  OfflineDiskStatus,
  OfflinePreview,
  OfflineSecurityCapability,
  OfflineTriggerResult,
} from '../types/offlineFlash'
import { tr } from './useLanguage'
import { API_BASE } from '../lib/runtimeEndpoint'

function base(): string {
  return `${API_BASE}/api/offline-download`
}

function resourceOwnerLabel(owner: unknown): string {
  if (typeof owner !== 'string') return tr('其他功能', 'another feature')
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
      return tr(`探针正在执行 ${resourceOwnerLabel(value.conflict_owner ?? value.owner)} 的操作，请等待操作完成。`, `The probe is executing an operation for ${resourceOwnerLabel(value.conflict_owner ?? value.owner)}. Wait for it to finish.`)
    }
    if (typeof value.message === 'string') return value.message
    try { return JSON.stringify(value) } catch { return fallback }
  }
  return fallback
}

export class OfflineFlashApiError extends Error {
  readonly notStarted: boolean
  constructor(message: string, notStarted: boolean) {
    super(message)
    this.notStarted = notStarted
  }
}

async function responseError(response: Response): Promise<Error> {
  const payload = await response.json().catch(() => null)
  return new OfflineFlashApiError(detailMessage(payload?.detail, response.statusText || `HTTP ${response.status}`),
    response.headers.get('X-MKLink-Submission') === 'not-started')
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${base()}${path}`, {
    ...options,
    headers: options?.body instanceof FormData
      ? options.headers
      : { 'Content-Type': 'application/json', ...options?.headers },
  })
  if (!response.ok) throw await responseError(response)
  return response.json()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

export function useOfflineFlashApi() {
  function getStatus(): Promise<OfflineDiskStatus> {
    return request('/status')
  }

  function listAlgorithms(partNumber: string): Promise<OfflineAlgorithmCandidate[]> {
    return request(`/algorithms?part_number=${encodeURIComponent(partNumber)}`)
  }

  function getSecurityStatus(model: string, partNumber: string): Promise<OfflineSecurityCapability> {
    return request(`/security?model=${encodeURIComponent(model)}&part_number=${encodeURIComponent(partNumber)}`)
  }

  function preview(config: OfflineConfigPayload): Promise<OfflinePreview> {
    return request('/preview', { method: 'POST', body: JSON.stringify(config) })
  }

  function deploy(
    config: OfflineConfigPayload,
    firmwareFiles: File[],
    flmFiles: File[],
    requestId: string = crypto.randomUUID(),
  ): Promise<OfflineDeployResult> {
    const body = new FormData()
    body.append('config_json', JSON.stringify(config))
    body.append('request_id', requestId)
    firmwareFiles.forEach(file => body.append('firmware_files', file, file.name))
    flmFiles.forEach(file => body.append('flm_files', file, file.name))
    return request<OfflineDeployResult>('/deploy', { method: 'POST', body,
      headers: { 'X-MKLink-Request-Id': requestId } }).catch(error => {
      if (error instanceof Error) { error.message += `; request_id=${requestId}`; throw error }
      throw new Error(`${String(error)}; request_id=${requestId}`)
    })
  }

  async function deploymentStatus(requestId: string) {
    const response = await fetch(`${API_BASE}/api/runtime/jobs/`)
    if (!response.ok) throw await responseError(response)
    const payload = await response.json()
    const job = payload.jobs.find((item: { request_id: string }) => item.request_id === requestId)
    if (!job || job.action !== 'offline_deploy') {
      throw new Error(tr('原下载器没有保留此部署记录；不能据此判断未执行或重新部署。', 'No retained deployment on this probe; this does not prove it did not run. Do not replay.'))
    }
    return job as { state: string; result: OfflineDeployResult | null; error: string | null; recovery_directory?: string }
  }

  async function trigger(
    model: 'V2' | 'V3' | 'V4',
    scriptName: string,
    onLine?: (line: string) => void,
    port?: string,
  ): Promise<OfflineTriggerResult> {
    const headers = new Headers({
      'Content-Type': 'application/json',
      Accept: 'application/x-ndjson',
    })
    const response = await fetch(`${base()}/trigger`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        model,
        script_name: scriptName,
        ...(port ? { port } : {}),
      }),
    })
    if (!response.ok) throw await responseError(response)
    if (!response.headers.get('Content-Type')?.toLowerCase().includes('application/x-ndjson')) {
      return response.json()
    }
    if (!response.body) throw new Error(tr('脱机下载未返回实时日志数据流', 'Offline flashing did not return a live log stream'))

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let result: OfflineTriggerResult | null = null
    const consume = (line: string) => {
      if (!line.trim()) return
      const message = JSON.parse(line) as Record<string, unknown>
      if (message.type === 'line' && typeof message.line === 'string') {
        onLine?.(message.line)
        return
      }
      if (message.type === 'result' && isRecord(message.result)) {
        result = message.result as unknown as OfflineTriggerResult
        return
      }
      if (message.type === 'error') {
        throw new Error(detailMessage(message.detail, tr('脱机下载执行失败', 'Offline flashing failed')))
      }
      throw new Error(tr('脱机下载返回了无效的实时日志消息', 'Offline flashing returned an invalid live log message'))
    }

    try {
      while (true) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value, { stream: !done })
        let newline = buffer.indexOf('\n')
        while (newline >= 0) {
          consume(buffer.slice(0, newline))
          buffer = buffer.slice(newline + 1)
          newline = buffer.indexOf('\n')
        }
        if (done) break
      }
      consume(buffer)
    } catch (value) {
      await reader.cancel().catch(() => undefined)
      throw value
    }
    if (result === null) throw new Error(tr('脱机下载实时日志在返回结果前中断', 'Offline flash log stream ended before returning a result'))
    return result
  }

  return { getStatus, listAlgorithms, getSecurityStatus, preview, deploy, deploymentStatus, trigger }
}
