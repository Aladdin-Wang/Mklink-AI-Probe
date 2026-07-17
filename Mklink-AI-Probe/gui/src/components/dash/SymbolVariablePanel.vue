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
        <input v-model="selectedOnly" type="checkbox" />
        仅已选
      </label>
      <span>{{ selected.size }} / {{ catalog.items.value.length }}</span>
    </div>

    <div v-if="catalog.stale.value" class="stale-banner">AXF 已变化，请重新解析</div>
    <div v-if="!deviceConnected" class="empty-state">请先连接设备</div>
    <div v-else-if="catalog.loading.value" class="empty-state">正在加载符号...</div>
    <div v-else class="variable-groups">
      <section v-for="group in groups" :key="group.name" class="variable-group">
        <h3>{{ group.name }}</h3>
        <div
          v-for="symbol in group.items"
          :key="symbol.path"
          class="variable-row"
          :class="{ selected: selected.has(symbol.path) }"
        >
          <div class="variable-main">
            <input
              type="checkbox"
              :checked="selected.has(symbol.path)"
              :data-testid="`toggle-${symbol.path}`"
              :disabled="selectionBusy.has(symbol.path)"
              @change="toggleSelection(symbol.path, $event)"
            />
            <button class="variable-name" type="button" @click="beginEdit(symbol)">
              {{ symbol.path }}
            </button>
            <span class="variable-type">{{ symbol.type_name }}</span>
            <span :data-testid="`latest-${symbol.path}`" class="variable-value">
              {{ formatValue(latestValues[symbol.path]) }}
            </span>
            <button
              class="edit-button"
              type="button"
              :data-testid="`edit-${symbol.path}`"
              :disabled="catalog.stale.value || !symbol.writable"
              title="设置变量"
              @click="beginEdit(symbol)"
            >
              编辑
            </button>
          </div>

          <div v-if="editing === symbol.path" class="write-editor">
            <select
              v-if="symbol.scalar_kind === 'bool'"
              v-model="editValues[symbol.path]"
              :data-testid="`write-input-${symbol.path}`"
            >
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
            <select
              v-else-if="symbol.scalar_kind === 'enum'"
              v-model="editValues[symbol.path]"
              :data-testid="`write-input-${symbol.path}`"
            >
              <option v-for="(_value, label) in symbol.enum_values" :key="label" :value="label">
                {{ label }}
              </option>
            </select>
            <input
              v-else
              v-model="editValues[symbol.path]"
              class="form-input"
              :data-testid="`write-input-${symbol.path}`"
              inputmode="decimal"
            />
            <button
              type="button"
              class="btn btn-primary"
              :data-testid="`write-${symbol.path}`"
              :disabled="writing.has(symbol.path)"
              @click="writeValue(symbol)"
            >
              {{ writing.has(symbol.path) ? '写入中' : '写入' }}
            </button>
            <button type="button" class="btn btn-secondary" @click="editing = null">取消</button>
          </div>
          <div
            v-if="writeSuccess[symbol.path] !== undefined"
            class="write-success"
            :data-testid="`write-ok-${symbol.path}`"
          >
            已验证: {{ formatValue(writeSuccess[symbol.path]) }}
          </div>
        </div>
      </section>
      <div v-if="groups.length === 0" class="empty-state">无匹配变量</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { useSymbolCatalog } from '../../composables/useSymbolCatalog'
import { useToast } from '../../composables/useToast'
import type { SymbolDescriptor } from '../../types/mklink'

const API_BASE = import.meta.env.VITE_MKLINK_API || ''

const props = defineProps<{
  deviceConnected: boolean
  latestValues: Record<string, number | boolean>
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

const groups = computed(() => {
  const key = query.value.trim().toLocaleLowerCase()
  const grouped = new Map<string, SymbolDescriptor[]>()
  for (const symbol of catalog.items.value) {
    if (selectedOnly.value && !selected.value.has(symbol.path)) continue
    if (key && !symbol.path.toLocaleLowerCase().includes(key)
      && !symbol.type_name.toLocaleLowerCase().includes(key)) continue
    const groupName = symbol.parent_path?.split('.')[0] || '全局变量'
    const values = grouped.get(groupName) ?? []
    values.push(symbol)
    grouped.set(groupName, values)
  }
  return [...grouped.entries()].map(([name, items]) => ({ name, items }))
})

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
  } catch (cause) {
    ;(event.target as HTMLInputElement).checked = !checked
    toast.error(cause instanceof Error ? cause.message : String(cause))
  } finally {
    selectionBusy.value = withSet(selectionBusy.value, path, false)
  }
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
    summary.removed.forEach(path => next.delete(path))
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
.variable-groups { min-height: 0; overflow: auto; }
.variable-group h3 { margin: 0; padding: 7px 10px; color: var(--muted); background: var(--bg); font-size: 11px; font-weight: 600; }
.variable-row { border-bottom: 1px solid var(--border); }
.variable-row.selected { background: color-mix(in srgb, var(--accent) 7%, transparent); }
.variable-main { display: grid; grid-template-columns: 18px minmax(100px, 1fr) 64px 66px 42px; align-items: center; gap: 5px; min-height: 36px; padding: 4px 8px; }
.variable-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border: 0; background: transparent; color: var(--fg); cursor: pointer; text-align: left; font: 12px Consolas, monospace; }
.variable-type, .variable-value { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); font: 11px Consolas, monospace; }
.variable-value { color: var(--info); text-align: right; }
.edit-button { border: 0; background: transparent; color: var(--accent); cursor: pointer; font-size: 11px; }
.edit-button:disabled { color: var(--muted); cursor: default; }
.write-editor { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 6px; padding: 0 8px 8px 31px; }
.write-editor input, .write-editor select { min-width: 0; height: 28px; }
.write-editor .btn { min-height: 28px; padding: 3px 8px; }
.write-success { padding: 0 8px 7px 31px; color: var(--success); font-size: 11px; }
.empty-state { padding: 24px 12px; color: var(--muted); text-align: center; font-size: 12px; }
</style>
