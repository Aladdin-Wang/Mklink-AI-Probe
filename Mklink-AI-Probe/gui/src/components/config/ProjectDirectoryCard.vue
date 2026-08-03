<template>
  <div class="card" style="margin-bottom:16px">
    <div class="card-title">{{ tr('项目目录', 'Project Directory') }}</div>
    <div class="form-row autocomplete-wrapper">
      <input
        ref="inputRef"
        class="form-input path-input"
        v-model="localPath"
        :placeholder="tr('输入或浏览选择项目根目录', 'Enter or browse for the project root')"
        @focus="showDropdown = true"
        @keydown.escape="showDropdown = false"
        @keydown.enter="apply"
      />
      <button class="btn btn-primary" @click="apply" :disabled="applying">{{ tr('应用', 'Apply') }}</button>
      <!-- Autocomplete dropdown -->
      <div v-if="showDropdown && filtered.length > 0" class="autocomplete-dropdown">
        <div
          v-for="entry in filtered"
          :key="entry.path"
          class="autocomplete-item"
          @mousedown.prevent="selectEntry(entry.path)"
        >
          <span class="ac-name">{{ entry.name }}</span>
          <span class="ac-path">{{ truncatePath(entry.path) }}</span>
          <span class="ac-time">{{ relativeTime(entry.last_used) }}</span>
        </div>
      </div>
    </div>
    <div class="form-row" style="margin-top:4px">
      <button class="btn btn-sm" @click="$emit('toggleBrowser')">{{ browserOpen ? tr('收起浏览', 'Hide Browser') : tr('浏览...', 'Browse...') }}</button>
      <button class="btn btn-sm btn-primary" @click="$emit('initProject')" :disabled="initing" style="margin-left:8px">
        {{ initing ? tr('初始化中...', 'Initializing...') : tr('初始化工程', 'Initialize Project') }}
      </button>
    </div>
    <div v-if="initResult" class="init-result" style="margin-top:8px">
      <div class="init-header">
        <span class="init-title">{{ initResult.success ? tr('初始化结果', 'Initialization Result') : tr('初始化失败', 'Initialization Failed') }}</span>
        <button class="btn btn-sm" @click="$emit('clearInitResult')">{{ tr('关闭', 'Close') }}</button>
      </div>
      <pre v-if="initResult.output" class="init-output">{{ initResult.output }}</pre>
      <div v-if="initResult.error" class="alert alert-error">{{ initResult.error }}</div>
    </div>
    <div v-if="rootError" class="alert alert-error" style="margin-top:8px">{{ rootError }}</div>

    <!-- Inline directory browser (slot for parent to control) -->
    <slot name="browser"></slot>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useProjectHistory } from '../../composables/useProjectHistory'
import { tr } from '../../composables/useLanguage'

const props = defineProps<{
  modelValue: string
  applying: boolean
  initing: boolean
  browserOpen: boolean
  initResult: { success?: boolean; output?: string; error?: string } | null
  rootError: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  applied: []
  toggleBrowser: []
  initProject: []
  clearInitResult: []
}>()

const { filteredEntries } = useProjectHistory()

const inputRef = ref<HTMLInputElement | null>(null)
const showDropdown = ref(false)
const localPath = computed({
  get: () => props.modelValue,
  set: (v: string) => emit('update:modelValue', v),
})

const filtered = computed(() => filteredEntries(localPath.value))

function apply() {
  showDropdown.value = false
  emit('applied')
}

function selectEntry(path: string) {
  emit('update:modelValue', path)
  showDropdown.value = false
  emit('applied')
}

function truncatePath(path: string): string {
  if (path.length <= 45) return path
  return path.substring(0, 18) + '...' + path.substring(path.length - 24)
}

function relativeTime(iso: string): string {
  try {
    const diffMs = Date.now() - new Date(iso).getTime()
    const m = Math.floor(diffMs / 60000)
    if (m < 1) return tr('刚刚', 'Just now')
    if (m < 60) return tr(`${m}分钟前`, `${m} min ago`)
    const h = Math.floor(m / 60)
    if (h < 24) return tr(`${h}小时前`, `${h} hr ago`)
    return tr(`${Math.floor(h / 24)}天前`, `${Math.floor(h / 24)} d ago`)
  } catch { return '' }
}

function onClickOutside(e: MouseEvent) {
  const el = inputRef.value?.closest('.autocomplete-wrapper')
  if (el && !el.contains(e.target as Node)) {
    showDropdown.value = false
  }
}

onMounted(() => document.addEventListener('mousedown', onClickOutside))
onUnmounted(() => document.removeEventListener('mousedown', onClickOutside))
</script>

<style scoped>
.autocomplete-wrapper {
  position: relative;
}
.autocomplete-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 80px;
  z-index: 10;
  background: var(--bg);
  border: 1px solid var(--border);
  border-top: none;
  border-radius: 0 0 var(--radius) var(--radius);
  max-height: 200px;
  overflow-y: auto;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}
.autocomplete-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 12px;
  transition: background 0.1s;
}
.autocomplete-item:hover {
  background: var(--surface);
}
.ac-name {
  font-weight: 500;
  color: var(--fg);
  flex-shrink: 0;
}
.ac-path {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.ac-time {
  color: var(--dim);
  font-size: 11px;
  flex-shrink: 0;
  white-space: nowrap;
}
.path-input {
  font-family: var(--font-mono);
  font-size: 12px;
}
.init-result {
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}
.init-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.init-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--fg);
}
.init-output {
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  color: var(--muted);
  background: var(--bg);
  padding: 10px 12px;
  margin: 0;
  white-space: pre-wrap;
  max-height: 260px;
  overflow-y: auto;
}
</style>
