<template>
  <aside class="symbol-panel">
    <div class="panel-toolbar">
      <input
        v-model="query"
        class="form-input"
        data-testid="variable-search"
        placeholder="搜索变量"
      />
      <button
        class="icon-button"
        type="button"
        title="重新解析符号"
        :disabled="catalog.reparsing.value"
        data-testid="reparse-symbols"
        @click="reparseSymbols"
      >
        ↻
      </button>
    </div>

    <div class="panel-filters">
      <label>
        <input v-model="selectedOnly" type="checkbox" data-testid="selected-only" />
        仅已选
      </label>
      <span>{{ selected.size }} / {{ catalog.items.value.length }}</span>
    </div>

    <div v-if="catalog.stale.value" class="stale-banner">AXF 已变化，请重新解析</div>
    <div v-if="catalog.truncatedRoots.value.length" class="truncated-banner">
      以下大型变量仅展开前 256 个可读叶子：{{ catalog.truncatedRoots.value.join('、') }}
    </div>
    <div v-if="!deviceConnected" class="empty-state">请先连接设备</div>
    <div v-else-if="catalog.loading.value" class="empty-state">正在加载符号...</div>
    <div v-else class="variable-groups">
      <h3 class="variable-root-heading">全局变量</h3>
      <template v-for="row in rows" :key="row.node.key">
        <button
          v-if="row.node.kind === 'branch'"
          class="branch-row"
          type="button"
          :data-testid="`branch-${row.node.key}`"
          :title="row.node.key"
          :style="{ paddingLeft: rowIndent(row.depth) }"
          @click="toggleBranch(row.node.key)"
        >
          <ChevronDown v-if="row.expanded" :size="15" aria-hidden="true" />
          <ChevronRight v-else :size="15" aria-hidden="true" />
          <span class="branch-name">{{ row.node.label }}</span>
          <span class="branch-count">{{ row.selectedLeafCount }} / {{ row.node.leafCount }}</span>
        </button>
        <div
          v-else-if="row.node.descriptor"
          class="variable-row"
          :class="{ selected: selected.has(row.node.descriptor.path) }"
          :data-testid="`leaf-${row.node.descriptor.path}`"
        >
          <div class="variable-main" :style="{ paddingLeft: rowIndent(row.depth) }">
            <input
              type="checkbox"
              :checked="selected.has(row.node.descriptor.path)"
              :data-testid="`toggle-${row.node.descriptor.path}`"
              :disabled="selectionBusy.has(row.node.descriptor.path)"
              @change="toggleSelection(row.node.descriptor.path, $event)"
            />
            <span class="visibility-slot">
              <button
                v-if="selected.has(row.node.descriptor.path)"
                class="visibility-button"
                type="button"
                :class="{ hidden: hiddenChannels?.has(row.node.descriptor.path) }"
                :data-testid="`visibility-${row.node.descriptor.path}`"
                :aria-label="hiddenChannels?.has(row.node.descriptor.path) ? `显示 ${row.node.descriptor.path} 波形` : `隐藏 ${row.node.descriptor.path} 波形`"
                :aria-pressed="!hiddenChannels?.has(row.node.descriptor.path)"
                :title="hiddenChannels?.has(row.node.descriptor.path) ? '显示波形' : '隐藏波形'"
                @click.stop="toggleVisibility(row.node.descriptor.path)"
              >
                <EyeOff v-if="hiddenChannels?.has(row.node.descriptor.path)" :size="15" aria-hidden="true" />
                <Eye v-else :size="15" aria-hidden="true" />
              </button>
            </span>
            <button
              class="variable-name"
              type="button"
              :title="row.node.descriptor.path"
              @click="beginEdit(row.node.descriptor)"
            >
              {{ row.node.label }}
            </button>
            <span class="variable-type">{{ row.node.descriptor.type_name }}</span>
            <span :data-testid="`latest-${row.node.descriptor.path}`" class="variable-value">
              {{ formatValue(latestValues[row.node.descriptor.path]) }}
            </span>
            <button
              class="edit-button"
              type="button"
              :data-testid="`edit-${row.node.descriptor.path}`"
              :disabled="catalog.stale.value || !row.node.descriptor.writable"
              title="设置变量"
              @click="beginEdit(row.node.descriptor)"
            >
              编辑
            </button>
          </div>

          <div v-if="editing === row.node.descriptor.path" class="write-editor">
            <select
              v-if="row.node.descriptor.scalar_kind === 'bool'"
              v-model="editValues[row.node.descriptor.path]"
              :data-testid="`write-input-${row.node.descriptor.path}`"
            >
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
            <select
              v-else-if="row.node.descriptor.scalar_kind === 'enum'"
              v-model="editValues[row.node.descriptor.path]"
              :data-testid="`write-input-${row.node.descriptor.path}`"
            >
              <option v-for="(_value, label) in row.node.descriptor.enum_values" :key="label" :value="label">
                {{ label }}
              </option>
            </select>
            <input
              v-else
              v-model="editValues[row.node.descriptor.path]"
              class="form-input"
              :data-testid="`write-input-${row.node.descriptor.path}`"
              inputmode="decimal"
            />
            <button
              type="button"
              class="btn btn-primary"
              :data-testid="`write-${row.node.descriptor.path}`"
              :disabled="writing.has(row.node.descriptor.path)"
              @click="writeValue(row.node.descriptor)"
            >
              {{ writing.has(row.node.descriptor.path) ? '写入中' : '写入' }}
            </button>
            <button type="button" class="btn btn-secondary" @click="editing = null">取消</button>
          </div>
          <div
            v-if="writeSuccess[row.node.descriptor.path] !== undefined"
            class="write-success"
            :data-testid="`write-ok-${row.node.descriptor.path}`"
          >
            已验证: {{ formatValue(writeSuccess[row.node.descriptor.path]) }}
          </div>
        </div>
      </template>
      <div v-if="rows.length === 0" class="empty-state">无匹配变量</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { ChevronDown, ChevronRight, Eye, EyeOff } from '@lucide/vue'
import { useSymbolCatalog } from '../../composables/useSymbolCatalog'
import { useToast } from '../../composables/useToast'
import { buildSymbolTree, collectBranchKeys, visibleSymbolRows } from '../../lib/symbolTree'
import type { SymbolDescriptor } from '../../types/mklink'

const API_BASE = import.meta.env.VITE_MKLINK_API || ''

const props = defineProps<{
  deviceConnected: boolean
  latestValues: Record<string, number | boolean>
  hiddenChannels?: ReadonlySet<string>
}>()

const emit = defineEmits<{
  'visibility-change': [path: string, visible: boolean]
  'selection-removed': [path: string]
}>()

const catalog = useSymbolCatalog()
const toast = useToast()
const query = ref('')
const selectedOnly = ref(false)
const selected = shallowRef(new Set<string>())
const selectionBusy = shallowRef(new Set<string>())
const writing = shallowRef(new Set<string>())
const editing = ref<string | null>(null)
const editValues = reactive<Record<string, string>>({})
const writeSuccess = reactive<Record<string, number | boolean | undefined>>({})
const expanded = shallowRef(new Set<string>())
let searchExpansionSnapshot: Set<string> | null = null

const tree = computed(() => buildSymbolTree(catalog.items.value))
const rows = computed(() => visibleSymbolRows(tree.value, {
  expanded: expanded.value,
  selected: selected.value,
  query: query.value,
  selectedOnly: selectedOnly.value,
}))

async function request(path: string, options?: RequestInit): Promise<any> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = payload?.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || response.statusText)
  }
  return payload
}

async function loadWorkspace(): Promise<void> {
  if (!props.deviceConnected) return
  try {
    await catalog.ensureLoaded()
    const response = await request('/api/dash/superwatch/items')
    selected.value = new Set(
      Array.isArray(response.items) ? response.items.map((item: { name: string }) => item.name) : [],
    )
  } catch (cause) {
    toast.error(cause instanceof Error ? cause.message : String(cause))
  }
}

function withSet(source: Set<string>, path: string, enabled: boolean): Set<string> {
  const next = new Set(source)
  if (enabled) next.add(path)
  else next.delete(path)
  return next
}

function toggleBranch(path: string): void {
  if (query.value.trim() || selectedOnly.value) return
  expanded.value = withSet(expanded.value, path, !expanded.value.has(path))
}

function rowIndent(depth: number): string {
  return `${8 + depth * 16}px`
}

async function toggleSelection(path: string, event: Event): Promise<void> {
  const checked = (event.target as HTMLInputElement).checked
  selectionBusy.value = withSet(selectionBusy.value, path, true)
  try {
    const action = checked ? 'add' : 'remove'
    await request(`/api/dash/superwatch/${action}`, {
      method: 'POST',
      body: JSON.stringify({ name: path }),
    })
    selected.value = withSet(selected.value, path, checked)
    if (!checked) emit('selection-removed', path)
  } catch (cause) {
    ;(event.target as HTMLInputElement).checked = !checked
    toast.error(cause instanceof Error ? cause.message : String(cause))
  } finally {
    selectionBusy.value = withSet(selectionBusy.value, path, false)
  }
}

function toggleVisibility(path: string): void {
  emit('visibility-change', path, props.hiddenChannels?.has(path) ?? false)
}

function beginEdit(symbol: SymbolDescriptor): void {
  if (catalog.stale.value || !symbol.writable) return
  const current = props.latestValues[symbol.path]
  if (symbol.scalar_kind === 'bool') {
    editValues[symbol.path] = String(current ?? false)
  } else if (symbol.scalar_kind === 'enum') {
    const match = Object.entries(symbol.enum_values).find(([, value]) => value === current)
    editValues[symbol.path] = match?.[0] ?? Object.keys(symbol.enum_values)[0] ?? ''
  } else {
    editValues[symbol.path] = current === undefined ? '' : String(current)
  }
  editing.value = symbol.path
}

function typedValue(symbol: SymbolDescriptor): unknown {
  const raw = editValues[symbol.path]
  if (symbol.scalar_kind === 'bool') return raw === 'true'
  if (symbol.scalar_kind === 'enum') return raw
  if (symbol.scalar_kind === 'signed' || symbol.scalar_kind === 'unsigned') {
    const value = Number(raw)
    if (!Number.isInteger(value)) throw new Error('请输入整数')
    return value
  }
  const value = Number(raw)
  if (!Number.isFinite(value)) throw new Error('请输入有限数值')
  return value
}

async function writeValue(symbol: SymbolDescriptor): Promise<void> {
  writing.value = withSet(writing.value, symbol.path, true)
  try {
    const result = await catalog.writeSymbol(symbol.path, typedValue(symbol))
    writeSuccess[symbol.path] = result.value
    editing.value = null
  } catch (cause) {
    toast.error(cause instanceof Error ? cause.message : String(cause))
  } finally {
    writing.value = withSet(writing.value, symbol.path, false)
  }
}

async function reparseSymbols(): Promise<void> {
  try {
    const summary = await catalog.reparse()
    const next = new Set(selected.value)
    summary.removed.forEach(path => {
      next.delete(path)
      emit('selection-removed', path)
    })
    selected.value = next
    toast.success(
      `符号已更新：保留 ${summary.preserved.length}，更新 ${summary.updated.length}，移除 ${summary.removed.length}`,
    )
  } catch (cause) {
    toast.error(cause instanceof Error ? cause.message : String(cause))
  }
}

function formatValue(value: number | boolean | undefined): string {
  if (value === undefined) return '--'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toPrecision(7)
  return String(value)
}

onMounted(loadWorkspace)
watch(() => props.deviceConnected, connected => {
  if (connected) void loadWorkspace()
})
watch(query, (next, previous) => {
  if (next.trim() && !previous.trim()) searchExpansionSnapshot = new Set(expanded.value)
  if (!next.trim() && previous.trim() && searchExpansionSnapshot) {
    expanded.value = searchExpansionSnapshot
    searchExpansionSnapshot = null
  }
})
watch(tree, roots => {
  const valid = collectBranchKeys(roots)
  expanded.value = new Set([...expanded.value].filter(path => valid.has(path)))
  if (searchExpansionSnapshot) {
    searchExpansionSnapshot = new Set([...searchExpansionSnapshot].filter(path => valid.has(path)))
  }
})
</script>

<style scoped>
.symbol-panel {
  display: flex;
  flex-direction: column;
  min-width: 280px;
  min-height: 0;
  border-right: 1px solid var(--border);
  background: var(--surface);
}
.panel-toolbar { display: flex; gap: 6px; padding: 10px; border-bottom: 1px solid var(--border); }
.panel-toolbar .form-input { min-width: 0; flex: 1; }
.icon-button { width: 30px; height: 30px; border: 1px solid var(--border); background: transparent; color: var(--fg); cursor: pointer; }
.panel-filters { display: flex; justify-content: space-between; padding: 7px 10px; color: var(--muted); font-size: 12px; border-bottom: 1px solid var(--border); }
.panel-filters label { display: flex; align-items: center; gap: 5px; }
.stale-banner { padding: 7px 10px; color: var(--warn); background: color-mix(in srgb, var(--warn) 10%, transparent); font-size: 12px; }
.truncated-banner {
  padding: 7px 10px;
  color: var(--warn);
  background: color-mix(in srgb, var(--warn) 8%, transparent);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.variable-groups { min-height: 0; overflow: auto; }
.variable-root-heading { margin: 0; padding: 7px 10px; color: var(--muted); background: var(--bg); font-size: 11px; font-weight: 600; }
.branch-row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  align-items: center;
  gap: 5px;
  width: 100%;
  min-height: 32px;
  padding-top: 4px;
  padding-right: 10px;
  padding-bottom: 4px;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  color: var(--fg);
  cursor: pointer;
  text-align: left;
}
.branch-row:hover { background: color-mix(in srgb, var(--accent) 5%, var(--surface)); }
.branch-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font: 12px Consolas, monospace; }
.branch-count { color: var(--muted); font: 11px Consolas, monospace; }
.variable-row { border-bottom: 1px solid var(--border); }
.variable-row.selected { background: color-mix(in srgb, var(--accent) 7%, transparent); }
.variable-main { display: grid; grid-template-columns: 18px 24px minmax(100px, 1fr) 64px 66px 42px; align-items: center; gap: 5px; min-height: 36px; padding: 4px 8px; }
.visibility-slot { display: grid; place-items: center; width: 24px; height: 24px; }
.visibility-button { display: grid; place-items: center; width: 24px; height: 24px; padding: 0; border: 0; background: transparent; color: var(--accent); cursor: pointer; }
.visibility-button:hover { background: color-mix(in srgb, var(--accent) 10%, transparent); }
.visibility-button.hidden { color: var(--muted); }
.visibility-button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.variable-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border: 0; background: transparent; color: var(--fg); cursor: pointer; text-align: left; font: 12px Consolas, monospace; }
.variable-type, .variable-value { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); font: 11px Consolas, monospace; }
.variable-value { color: var(--info); text-align: right; }
.edit-button { border: 0; background: transparent; color: var(--accent); cursor: pointer; font-size: 11px; }
.edit-button:disabled { color: var(--muted); cursor: default; }
.write-editor { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 6px; padding: 0 8px 8px 60px; }
.write-editor input, .write-editor select { min-width: 0; height: 28px; }
.write-editor .btn { min-height: 28px; padding: 3px 8px; }
.write-success { padding: 0 8px 7px 60px; color: var(--success); font-size: 11px; }
.empty-state { padding: 24px 12px; color: var(--muted); text-align: center; font-size: 12px; }
</style>
