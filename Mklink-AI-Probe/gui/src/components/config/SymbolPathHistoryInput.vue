<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { Clock3, X } from '@lucide/vue'
import { tr } from '../../composables/useLanguage'
import { SYMBOL_PATH_HISTORY_KEY, loadSymbolPathHistory, rememberSymbolPath, removeSymbolPath } from '../../lib/symbolPathHistory'

const props = defineProps<{ path: string; displayPath?: string; disabled?: boolean }>()
const emit = defineEmits<{ (event: 'update:path', path: string): void }>()
const root = ref<HTMLElement>()
const input = ref<HTMLInputElement>()
const open = ref(false)
const query = ref('')
const history = ref(loadSymbolPathHistory(window.localStorage))
// Migrate the previous single saved path once; deleting it must stay deleted.
try {
  if (window.localStorage.getItem(SYMBOL_PATH_HISTORY_KEY) === null) {
    history.value = rememberSymbolPath(window.localStorage, props.path, props.displayPath)
  }
} catch { /* Storage may be unavailable. */ }
const visible = computed(() => history.value.filter(path => path.toLowerCase().includes(query.value.toLowerCase())))
const expanded = computed(() => open.value && !props.disabled && visible.value.length > 0)

function showHistory() {
  history.value = loadSymbolPathHistory(window.localStorage)
  query.value = ''
  open.value = true
}
function edit(event: Event) {
  const value = (event.target as HTMLInputElement).value
  query.value = value
  open.value = true
  emit('update:path', value)
}
function commit(event: Event) {
  history.value = rememberSymbolPath(window.localStorage, (event.target as HTMLInputElement).value)
}
function select(path: string) {
  emit('update:path', path)
  history.value = rememberSymbolPath(window.localStorage, path)
  input.value?.focus()
  open.value = false
}
function remove(path: string) {
  history.value = removeSymbolPath(window.localStorage, path)
  input.value?.focus()
}
function leave(event: FocusEvent) {
  if (!root.value?.contains(event.relatedTarget as Node | null)) open.value = false
}
async function move(event: KeyboardEvent, direction: number) {
  event.preventDefault()
  if (!open.value) showHistory()
  await nextTick()
  const choices = [...(root.value?.querySelectorAll<HTMLButtonElement>('[data-history-path]') || [])]
  if (!choices.length) return
  const index = choices.indexOf(document.activeElement as HTMLButtonElement)
  choices[index < 0 ? (direction > 0 ? 0 : choices.length - 1) : (index + direction + choices.length) % choices.length]?.focus()
}
function dismiss() {
  input.value?.focus()
  open.value = false
}
</script>

<template>
  <div ref="root" class="history-input" @focusout="leave" @keydown.esc.stop="dismiss"
    @keydown.down="move($event, 1)" @keydown.up="move($event, -1)">
    <input ref="input" id="symbol-path" class="form-input path-input" data-testid="symbol-path"
      :value="displayPath?.trim() || path" :disabled="disabled" autocomplete="off"
      :placeholder="tr('.axf 或 .elf 文件路径', '.axf or .elf file path')"
      :aria-expanded="expanded" aria-controls="symbol-path-history"
      @focus="showHistory" @click="showHistory" @input="edit" @change="commit" />
    <div v-if="expanded" id="symbol-path-history" class="history-menu" role="group"
      :aria-label="tr('最近使用的文件', 'Recent files')">
      <div class="history-heading"><Clock3 :size="13" aria-hidden="true" />{{ tr('最近使用的文件', 'Recent files') }}</div>
      <div v-for="path in visible" :key="path" class="history-row">
        <button type="button" class="history-choice" data-history-path :title="path" @click="select(path)">
          <span class="history-name">{{ path.split(/[/\\]/).pop() }}</span>
          <span class="history-path">{{ path }}</span>
        </button>
        <button type="button" class="history-remove" :aria-label="tr('移除历史记录：', 'Remove from history: ') + path"
          :title="tr('移除历史记录', 'Remove from history')" @click="remove(path)"><X :size="14" aria-hidden="true" /></button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-input { flex: 1; min-width: 0; position: relative; }
.path-input { width: 100%; min-width: 0; font-family: var(--font-mono); font-size: 12px; }
.history-menu { position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 30; max-height: 300px; overflow-y: auto; padding: 6px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface, #1c222b); box-shadow: 0 12px 28px #0004; }
.history-heading { display: flex; align-items: center; gap: 7px; padding: 7px 10px; color: var(--dim); font-size: 11px; }
.history-row { display: flex; align-items: center; gap: 4px; }
.history-choice { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: stretch; gap: 4px; padding: 9px 10px; text-align: left; }
.history-choice, .history-remove { color: var(--text); background: transparent; border: 0; border-radius: 6px; cursor: pointer; }
.history-choice:hover, .history-choice:focus-visible, .history-remove:hover, .history-remove:focus-visible { background: var(--bg); outline: 1px solid var(--accent); }
.history-name { font-size: 12px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-path { color: var(--dim); font-family: var(--font-mono); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-remove { padding: 8px; display: flex; }
</style>
