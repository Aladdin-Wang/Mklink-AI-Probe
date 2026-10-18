import { API_BASE } from './runtimeEndpoint'
import { ref, watch, type Ref } from 'vue'

const selecting = ref(0)
let selectedGeneration: number | undefined

// A download's own reservation must not unmount the form that submitted it.
// Every other device transition still discards cached download state.
export function useDownloadViewKey(generation: Ref<number | undefined>): Ref<number> {
  const key = ref(generation.value || 0)
  watch([generation, selecting], ([value, pending]) => {
    if (!pending && value !== selectedGeneration) key.value = value || 0
  })
  return key
}

// Reserve a physical probe without connecting its target or restoring debug settings.
export async function selectDownloadProbe(probe: string, cmsisDap = false): Promise<Record<string, string>> {
  selecting.value++
  try {
    const response = await fetch(`${API_BASE}/api/runtime/select`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cmsisDap ? { cmsis_dap_id: probe } : { probe }),
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(payload?.detail?.message || payload?.detail || response.statusText)
    }
    const selected = await response.json()
    selectedGeneration = selected.device_generation
    return selected.probe_id ? {
      'X-MKLink-Probe': selected.probe_id,
      'X-MKLink-Device-Generation': String(selected.device_generation),
    } : {}
  } finally { selecting.value-- }
}
