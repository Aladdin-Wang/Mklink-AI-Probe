import { ref } from 'vue'
import { API_BASE } from '../lib/runtimeEndpoint'
export interface Section { id: string; name: string; collapsed: boolean; height: number }
export interface SignalStyle { alias: string; emphasis: boolean; group: string; pane: string; renderMode?: 'line' | 'points' }
export interface WatchWorkspace { version: 2; defaultGroup?: string; groups: Section[]; panes: Section[]; signals: Record<string, SignalStyle> }
const empty = (): WatchWorkspace => ({ version: 2, groups: [{ id: 'main', name: '默认分组', collapsed: false, height: 240 }], panes: [{ id: 'main', name: '默认分组', collapsed: false, height: 240 }], signals: {} })
const workspace = ref<WatchWorkspace>(empty())
const error = ref(''), busy = ref(false), ready = ref(false)
let revision = '', loading: Promise<void> | null = null
function publish() {
  const snapshot = JSON.parse(JSON.stringify(workspace.value))
  ;(window as any).__MKLINK_WATCH_WORKSPACE__ = snapshot
  ;(window as any).__waveformViewers?.SuperWatch?.setWorkspace?.(snapshot)
}
async function request(options?: RequestInit) {
  const response = await fetch(`${API_BASE}/api/dash/superwatch/workspace`, options)
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || response.statusText)
  if (data.workspace?.version !== 2 || !Array.isArray(data.workspace.groups) || !Array.isArray(data.workspace.panes) || !data.workspace.panes.length || !data.workspace.signals || typeof data.revision !== 'string') throw new Error('Invalid workspace response')
  return data
}
async function load() {
  if (busy.value) return
  if (loading) return loading
  loading = (async () => {
    try {
      const data = await request()
      workspace.value = data.workspace; revision = data.revision; ready.value = true; error.value = ''; publish()
    } catch (e) { error.value = String(e); ready.value = false }
    finally { loading = null }
  })()
  return loading
}
async function update(change: (value: WatchWorkspace) => void) {
  if (!ready.value || busy.value) return
  busy.value = true
  const next = JSON.parse(JSON.stringify(workspace.value)) as WatchWorkspace
  change(next)
  try {
    const data = await request({ method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace: next, revision }) })
    workspace.value = data.workspace; revision = data.revision; error.value = ''; publish()
  } catch (e) { error.value = String(e) }
  finally { busy.value = false }
}
function style(path: string): SignalStyle {
  return workspace.value.signals[path] || { alias: '', emphasis: false, group: workspace.value.defaultGroup || workspace.value.groups[0]?.id || 'main', pane: workspace.value.defaultGroup || workspace.value.groups[0]?.id || 'main', renderMode: 'line' }
}
function setStyle(paths: string[], patch: Partial<SignalStyle>) {
  return update(w => { for (const path of paths) w.signals[path] = { ...style(path), ...patch, ...(patch.group !== undefined ? {pane: patch.group} : {}) } })
}
function imported(event: Event) {
  const data = (event as CustomEvent).detail
  if (data?.version === 1 || data?.version === 2) void update(w => Object.assign(w, data))
}
if (typeof window !== 'undefined') window.addEventListener('mklink:workspace-import', imported)
export function useWatchWorkspace() { return { workspace, error, busy, ready, load, update, style, setStyle } }

if (typeof window !== 'undefined') window.addEventListener('mklink:workspace-split', event => {
  const path = (event as CustomEvent).detail?.path
  if (typeof path !== 'string') return
  void update(w => {
    const id = crypto.randomUUID()
    w.groups.push({id, name: style(path).alias || path, collapsed: false, height: 200})
    w.signals[path] = {...style(path), group: id, pane: id}
  })
})

if (typeof window !== 'undefined') window.addEventListener('mklink:workspace-resize', event => {
  const panes = (event as CustomEvent).detail
  if (Array.isArray(panes)) void update(w => { for (const pane of panes) { const group=w.groups.find(g=>g.id===pane.id); if(group) group.height=pane.height } })
})
