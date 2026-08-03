import { ref, readonly } from 'vue'
import { API_BASE } from '../lib/runtimeEndpoint'

export interface ResourceLeaseStatus {
  owner: string
  acquired_at: number
  expires_at: number | null
  is_user: boolean
  is_ai: boolean
}

export interface ResourceStatus {
  [resource: string]: ResourceLeaseStatus
}

const status = ref<ResourceStatus>({})

export function useResourceStatus() {
  async function refresh() {
    try {
      const resp = await fetch(`${API_BASE}/api/session/status`)
      if (resp.ok) {
        status.value = await resp.json()
      }
    } catch {
      // ignore
    }
  }

  async function checkConflict(type: string): Promise<string[]> {
    try {
      const resp = await fetch(`${API_BASE}/api/dash/conflict-check?type=${type}`)
      if (resp.ok) {
        const data = await resp.json()
        return data.conflicts || []
      }
    } catch {
      // ignore
    }
    return []
  }

  function getBridgeOwner(): string | null {
    const lease = status.value['mklink_bridge']
    return lease ? lease.owner : null
  }

  return {
    status: readonly(status),
    refresh,
    checkConflict,
    getBridgeOwner,
  }
}
