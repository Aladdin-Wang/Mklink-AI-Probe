import { readonly, ref, shallowRef } from 'vue'
import type {
  AxfFingerprint,
  SymbolCatalogPage,
  SymbolCatalogStatus,
  SymbolDescriptor,
  SymbolRebindSummary,
} from '../types/mklink'

const API_BASE = import.meta.env.VITE_MKLINK_API || ''
const PAGE_SIZE = 500

const items = shallowRef<SymbolDescriptor[]>([])
const generation = ref(0)
const parsedAt = ref(0)
const fingerprint = shallowRef<AxfFingerprint | null>(null)
const stale = ref(false)
const total = ref(0)
const loading = ref(false)
const reparsing = ref(false)
const error = ref<string | null>(null)

let loadingPromise: Promise<void> | null = null

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string') return message
  }
  return fallback
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(errorMessage(payload, response.statusText || 'Request failed'))
  }
  return response.json() as Promise<T>
}

async function fetchCatalog(): Promise<SymbolCatalogPage> {
  const first = await request<SymbolCatalogPage>(
    `/api/symbols/catalog?offset=0&limit=${PAGE_SIZE}`,
  )
  const merged = [...first.items]
  while (merged.length < first.total) {
    const page = await request<SymbolCatalogPage>(
      `/api/symbols/catalog?offset=${merged.length}&limit=${PAGE_SIZE}`,
    )
    if (page.generation !== first.generation) {
      throw new Error('Symbol catalog changed while loading; retry')
    }
    if (page.items.length === 0) break
    merged.push(...page.items)
  }
  return { ...first, items: merged, total: merged.length }
}

function publishCatalog(catalog: SymbolCatalogPage): void {
  items.value = catalog.items
  generation.value = catalog.generation
  parsedAt.value = catalog.parsed_at
  fingerprint.value = catalog.fingerprint
  stale.value = catalog.stale
  total.value = catalog.total
}

async function loadCatalog(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    publishCatalog(await fetchCatalog())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    throw cause
  } finally {
    loading.value = false
  }
}

async function ensureLoaded(force = false): Promise<void> {
  if (!force && generation.value > 0) return
  if (loadingPromise) return loadingPromise
  loadingPromise = loadCatalog().finally(() => {
    loadingPromise = null
  })
  return loadingPromise
}

async function refreshStatus(): Promise<SymbolCatalogStatus> {
  const status = await request<SymbolCatalogStatus>('/api/symbols/status')
  stale.value = status.stale
  if (status.generation === generation.value) {
    parsedAt.value = status.parsed_at
    fingerprint.value = status.fingerprint
    total.value = status.total
  }
  return status
}

async function reparse(): Promise<SymbolRebindSummary> {
  reparsing.value = true
  error.value = null
  try {
    const response = await request<Partial<SymbolRebindSummary>>('/api/symbols/reparse', {
      method: 'POST',
    })
    const nextCatalog = await fetchCatalog()
    publishCatalog(nextCatalog)
    return {
      preserved: response.preserved ?? [],
      updated: response.updated ?? [],
      removed: response.removed ?? [],
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    throw cause
  } finally {
    reparsing.value = false
  }
}

export function useSymbolCatalog() {
  return {
    items: readonly(items),
    generation: readonly(generation),
    parsedAt: readonly(parsedAt),
    fingerprint: readonly(fingerprint),
    stale: readonly(stale),
    total: readonly(total),
    loading: readonly(loading),
    reparsing: readonly(reparsing),
    error: readonly(error),
    ensureLoaded,
    refreshStatus,
    reparse,
  }
}
