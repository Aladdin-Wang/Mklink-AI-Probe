<template>
  <button class="panel-btn" data-testid="sw-record-toggle" :class="{ active: status.active }" :disabled="busy" @click="status.active ? stop() : showPicker()">{{ status.active ? tr('停止记录', 'Stop recording') : tr('开始记录', 'Start recording') }}</button>
  <span v-if="status.path" class="record-result" :title="status.path">{{ status.active ? tr('记录中', 'Recording') : tr('已保存', 'Saved') }} · {{ status.samples || 0 }} {{ tr('条', 'samples') }}</span>
  <span v-if="error || status.error" role="alert" class="record-error">{{ error || status.error }}</span>
  <Teleport to="body">
    <dialog ref="dialog" class="record-dialog" @keydown.stop>
      <form @submit.prevent="start">
        <h3>{{ tr('保存 SuperWatch 日志', 'Save SuperWatch log') }}</h3>
        <p>{{ tr('日志持续写入后台电脑的所选目录，停止采集也会完成保存。', 'Logs are continuously written on the backend computer. Stopping acquisition also completes recording.') }}</p>
        <div class="record-path"><input v-model="directory" data-testid="sw-record-directory" :aria-label="tr('保存目录', 'Save directory')"><button type="button" @click="browse(directory)">{{ tr('浏览', 'Browse') }}</button></div>
        <div class="record-drives"><button v-for="drive in drives" :key="drive" type="button" @click="browse(drive)">{{ drive }}</button><button type="button" @click="browse(parent)">↑ {{ tr('上一级', 'Parent') }}</button></div>
        <div class="record-folders"><button v-for="dir in dirs" :key="dir.path" type="button" @click="browse(dir.path)">▸ {{ dir.name }}</button></div>
        <p>{{ tr('自动分段保存 JSONL，可在“日志回放”中按编号加载查看。', 'JSONL parts are saved automatically; open numbered parts in Log replay.') }}</p>
        <p v-if="error" role="alert" class="record-error">{{ error }}</p>
        <footer><button type="button" @click="dialog?.close()">{{ tr('取消', 'Cancel') }}</button><button data-testid="sw-record-confirm" :disabled="busy || !directory.trim()">{{ tr('开始记录', 'Start recording') }}</button></footer>
      </form>
    </dialog>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { API_BASE } from '../../lib/runtimeEndpoint'
import { language } from '../../composables/useLanguage'
const emit = defineEmits<{ state: [state: string] }>()
const tr = (zh: string, en: string) => language.value === 'en' ? en : zh
type Recording = { active: boolean; state: string; samples?: number; path?: string; error?: string }
const status = ref<Recording>({ active: false, state: 'idle' })
const directory = ref(localStorage.getItem('mklink.superwatch.recordDirectory') || '')
const dialog = ref<HTMLDialogElement>()
const dirs = ref<Array<{ name: string; path: string }>>([]), drives = ref<string[]>([]), parent = ref('')
const busy = ref(false), error = ref('')
let timer: ReturnType<typeof setTimeout> | undefined, disposed = false, browseGeneration = 0
async function request(path: string, body?: unknown) {
  const response = await fetch(`${API_BASE}${path}`, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
  return data
}
function update(data: Recording) { status.value = data; emit('state', data.state) }
async function poll() {
  try { if (!busy.value) update(await request('/api/dash/superwatch/recording/status')) }
  catch (caught) { error.value = String(caught) }
  finally { if (!disposed) timer = setTimeout(poll, 1000) }
}
async function browse(path: string) {
  const generation = ++browseGeneration
  try {
    const data = await request(`/api/project-root/browse?path=${encodeURIComponent(path)}`)
    if (generation !== browseGeneration || disposed) return
    directory.value = data.current; parent.value = data.parent; dirs.value = data.dirs; drives.value = data.drives
    error.value = ''
  } catch (caught) { error.value = String(caught) }
}
function showPicker() { error.value = ''; dialog.value?.showModal(); void browse(directory.value) }
async function start() {
  busy.value = true; error.value = ''
  try {
    update(await request('/api/dash/superwatch/recording/start', { directory: directory.value }))
    localStorage.setItem('mklink.superwatch.recordDirectory', directory.value)
    dialog.value?.close()
  } catch (caught) { error.value = String(caught) }
  finally { busy.value = false }
}
async function stop() {
  busy.value = true; error.value = ''
  try { update(await request('/api/dash/superwatch/recording/stop', {})) }
  catch (caught) { error.value = String(caught) }
  finally { busy.value = false }
}
onMounted(poll)
onUnmounted(() => { disposed = true; clearTimeout(timer) })
</script>

<style scoped>
.record-dialog { color: var(--text-primary, #ddd); background: var(--bg-secondary, #1b222c); border: 1px solid var(--border, #465366); border-radius: 8px; width: min(620px, 90vw); padding: 20px; }
.record-dialog::backdrop { background: #0008; }
.record-dialog p { font-size: 12px; opacity: .8; }
.record-dialog button, .record-dialog input { color: inherit; background: transparent; border: 1px solid #465366; border-radius: 4px; padding: 6px 10px; }
.record-path, .record-drives, footer { display: flex; gap: 8px; margin: 10px 0; }
.record-path input { flex: 1; min-width: 0; }
.record-folders { height: 220px; overflow: auto; display: flex; flex-direction: column; gap: 4px; }
.record-folders button { text-align: left; }
footer { justify-content: flex-end; }
.record-error { color: #ff8585; max-width: 320px; font-size: 12px; }
.record-result { font-size: 12px; white-space: nowrap; }
</style>
