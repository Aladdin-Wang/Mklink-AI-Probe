export interface ProbeRecord {
  unique_id: string
  vendor_name: string
  product_name: string
  description: string
  vid: number | null
  pid: number | null
  serial_number: string | null
}

export interface TargetRecord {
  part_number: string
  vendor: string
  pack_id: string | null
  pack_version: string | null
  installed: boolean
  source: string
}

export interface PackStatus {
  last_error: string | null
  index_available: boolean
  target_count: number
}

export interface ImageSegment {
  start: number
  end: number
}

export interface ImageInspection {
  image_id: string
  file_name: string
  format: string
  size: number
  sha256: string
  start: number
  end: number
  segments: ImageSegment[]
  base_address: number | null
}

export interface PreviewPage {
  address: number
  length: number
  data_base64: string
  present: boolean[]
}

export interface SectorRecord {
  address: number
  size: number
}

export type JobAction = 'connect' | 'erase' | 'program' | 'verify' | 'reset' | 'disconnect'

export interface JobRequest {
  actions: JobAction[]
  image_id?: string | null
  preempt_ai?: boolean
  probe_id?: string | null
  target_part?: string | null
  frequency?: number
  connect_mode?: string
  reset_mode?: string
  base_address?: number | null
  sector_addresses?: number[]
}

export type JobState =
  | 'queued'
  | 'connecting'
  | 'erasing'
  | 'programming'
  | 'verifying'
  | 'resetting'
  | 'disconnecting'
  | 'stopping'
  | 'stopped'
  | 'succeeded'
  | 'failed'

export interface JobSnapshot {
  job_id: string
  state: JobState
  actions: string[]
  image_id: string | null
  created_at: number
  updated_at: number
  probe_id: string | null
  target_part: string | null
  frequency: number
  connect_mode: string
  reset_mode: string
  file_path: null
  image_format: string | null
  image_start: number | null
  image_end: number | null
  image_size: number | null
  image_sha256: string | null
  current_action: string | null
  stage_progress: number
  total_progress: number
  speed_bytes_per_second: number
  elapsed_seconds: number
  error_code: string | null
  error_message: string | null
}

export interface JobEvent {
  job_id: string
  sequence: number
  timestamp: number
  event: 'state' | 'progress' | 'log' | 'error'
  message: string
  state: JobState | null
  progress: number | null
}

export interface JobStreamError {
  code: string
  message: string
}

export type JobStreamEvent = JobEvent | JobStreamError

export interface PackFractionProgressEvent {
  type: 'progress'
  progress: number
}

export interface PackCountProgressEvent {
  type: 'progress'
  current: number
  total: number
}

export type PackProgressEvent = PackFractionProgressEvent | PackCountProgressEvent

export interface PackLogEvent {
  type: 'log'
  message: string
}

export type PackEvent = PackProgressEvent | PackLogEvent

export interface PackInstalledPartResult {
  status: 'installed'
  part_number: string
}

export interface PackInstalledVersionResult {
  status: 'installed'
  pack_id: string
  version: string
}

export type PackInstalledResult = PackInstalledPartResult | PackInstalledVersionResult

export interface PackIndexUpdatedResult {
  status: 'updated'
  target_count?: never
}

export interface PackIndexCountResult {
  status: 'updated'
  target_count: number
}

export type PackIndexResult = PackIndexUpdatedResult | PackIndexCountResult

export type PackOperationResult = PackInstalledResult | PackIndexResult

export interface PackOperationResponse {
  result: PackOperationResult
  events: PackEvent[]
}

export interface PackCancelResult {
  status: 'cancelled'
}

export interface PackRemoveResult {
  status: 'removed'
  pack_id: string
  version: string
}

export interface JobCreateResult {
  job_id: string
  job: JobSnapshot
}

export interface TargetSearchOptions {
  vendor?: string
  installed?: boolean
  limit?: number
}

export interface JobSubscription {
  close(): void
}
