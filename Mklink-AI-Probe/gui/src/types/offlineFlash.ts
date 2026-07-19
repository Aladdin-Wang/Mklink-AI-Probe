import type { TargetRecord } from './onlineFlash'

export interface OfflineDiskStatus {
  available: boolean
  disk_path: string | null
  python_dir: string | null
  flm_dir: string | null
}

export interface OfflineModelResult {
  model: 'V2' | 'V3' | 'V4'
  version: string
}

export interface OfflineAlgorithmCandidate {
  id: string
  file_name: string
  flash_base: string
  ram_base: string
  source_kind: 'pack' | 'profile' | 'existing'
  source_token: string | null
  origin: string
  available: boolean
  on_probe: boolean
}

export interface OfflineAlgorithmConfig {
  id: string
  file_name: string
  flash_base: string
  ram_base: string
  source_kind: 'upload' | 'pack' | 'profile' | 'existing'
  source_token?: string | null
  upload_index?: number | null
}

export interface OfflineFirmwareConfig {
  id: string
  file_name: string
  format: 'bin' | 'hex'
  base_address: string | null
  algorithm_id: string
  upload_index: number
}

export interface OfflineConfigPayload {
  model: 'auto' | 'V2' | 'V3' | 'V4'
  port?: string | null
  script_name: string
  auto_download_count: number
  wait_idcode_timeout_ms: number
  swd_clock_hz: number
  target_part?: string | null
  board?: string | null
  hpm_flash_cfg?: [string, string, string, string] | null
  algorithms: OfflineAlgorithmConfig[]
  firmwares: OfflineFirmwareConfig[]
}

export interface OfflinePreview {
  model: 'V2' | 'V3' | 'V4'
  script_name: string
  script: string
}

export interface OfflineDeployResult {
  status: 'deployed'
  model: 'V2' | 'V3' | 'V4'
  script_name: string
  files: string[]
}

export interface OfflineTriggerResult {
  status: 'completed' | 'failed'
  lines: string[]
}

export interface OfflineTargetState {
  query: string
  results: TargetRecord[]
  busy: boolean
  error: string
}
