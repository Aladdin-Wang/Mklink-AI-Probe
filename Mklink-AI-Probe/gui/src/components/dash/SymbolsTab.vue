<template>
  <div class="symbols-tab">
    <div v-if="!deviceConnected" class="alert alert-warn">请先连接设备。</div>
    <template v-else>
      <div class="sym-controls">
        <input
          v-model="query"
          data-testid="symbol-search"
          class="form-input"
          placeholder="搜索变量名或类型"
        />
        <button
          v-if="catalog.stale.value"
          class="btn btn-secondary"
          type="button"
          :disabled="catalog.reparsing.value"
          @click="reparseSymbols"
        >
          {{ catalog.reparsing.value ? '解析中' : '重新解析' }}
        </button>
      </div>

      <div class="sym-summary">
        <span>第 {{ catalog.generation.value }} 代</span>
        <span>{{ filtered.length }} 个变量</span>
        <span v-if="catalog.stale.value" class="stale-label">AXF 已变化</span>
      </div>

      <div v-if="catalog.loading.value" class="sym-empty">正在加载符号表...</div>
      <div v-else-if="visibleItems.length" class="sym-results">
        <button
          v-for="symbol in visibleItems"
          :key="symbol.path"
          class="sym-item"
          type="button"
          :data-symbol="symbol.path"
          @click="selectSymbol(symbol.path)"
        >
          <span class="sym-name">{{ symbol.path }}</span>
          <span class="sym-type">{{ symbol.type_name }}</span>
          <span class="sym-addr">{{ formatAddr(symbol.address) }}</span>
          <span class="sym-size">{{ symbol.size }}B</span>
        </button>
      </div>
      <div v-else class="sym-empty">
        {{ query ? '无匹配变量' : '当前 AXF 中没有可运行时读取的变量' }}
      </div>

      <div v-if="filtered.length > visibleItems.length" class="sym-limit">
        仅显示前 {{ visibleItems.length }} 项，请缩小搜索范围。
      </div>

      <div v-if="selectedType" class="sym-detail">
        <h4>类型信息: {{ selectedType.name }}</h4>
        <table v-if="selectedType.found" class="desc-table">
          <tbody>
            <tr><th>类型</th><td>{{ selectedType.type }}</td></tr>
            <tr><th>大小</th><td>{{ selectedType.size }} bytes</td></tr>
            <tr><th>地址</th><td>{{ formatAddr(selectedType.address) }}</td></tr>
          </tbody>
        </table>
        <div v-if="selectedType.members?.length" class="sym-members">
          <h5>成员</h5>
          <div v-for="(member, index) in selectedType.members" :key="index" class="sym-member">
            {{ JSON.stringify(member) }}
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useSymbolsApi } from '../../composables/useDashboard'
import { useSymbolCatalog } from '../../composables/useSymbolCatalog'
import { useToast } from '../../composables/useToast'
import type { SymbolTypeInfo } from '../../types/mklink'

const props = defineProps<{ deviceConnected: boolean }>()

const catalog = useSymbolCatalog()
const symbols = useSymbolsApi()
const toast = useToast()
const query = ref('')
const selectedType = ref<SymbolTypeInfo | null>(null)

const filtered = computed(() => {
  const key = query.value.trim().toLocaleLowerCase()
  if (!key) return catalog.items.value
  return catalog.items.value.filter(symbol => (
    symbol.path.toLocaleLowerCase().includes(key)
    || symbol.type_name.toLocaleLowerCase().includes(key)
  ))
})
const visibleItems = computed(() => filtered.value.slice(0, 500))

async function loadCatalog(): Promise<void> {
  if (!props.deviceConnected) return
  try {
    await catalog.ensureLoaded()
    await catalog.refreshStatus().catch(() => undefined)
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause)
    if (!message.includes('No DWARF')) toast.error(message)
  }
}

async function reparseSymbols(): Promise<void> {
  try {
    const summary = await catalog.reparse()
    toast.success(
      `符号已更新：保留 ${summary.preserved.length}，更新 ${summary.updated.length}，移除 ${summary.removed.length}`,
    )
  } catch (cause) {
    toast.error(cause instanceof Error ? cause.message : String(cause))
  }
}

async function selectSymbol(path: string): Promise<void> {
  try {
    selectedType.value = await symbols.typeinfo(path)
  } catch (cause) {
    toast.error(cause instanceof Error ? cause.message : String(cause))
  }
}

function formatAddr(address: unknown): string {
  if (address == null) return '-'
  if (typeof address === 'number') {
    return `0x${address.toString(16).toUpperCase().padStart(8, '0')}`
  }
  return String(address)
}

onMounted(loadCatalog)
watch(() => props.deviceConnected, connected => {
  if (connected) void loadCatalog()
})
</script>

<style scoped>
.symbols-tab { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
.sym-controls { display: flex; gap: 8px; }
.sym-controls .form-input { flex: 1; min-width: 0; }
.sym-summary { display: flex; gap: 14px; color: var(--muted); font-size: 12px; }
.stale-label { color: var(--warn); }
.sym-results { max-height: 420px; overflow-y: auto; border: 1px solid var(--border); }
.sym-item {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 120px 100px 44px;
  gap: 12px;
  width: 100%;
  padding: 7px 9px;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
  font-family: Consolas, monospace;
  font-size: 12px;
}
.sym-item:last-child { border-bottom: 0; }
.sym-item:hover { background: var(--surface); }
.sym-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--fg); }
.sym-type, .sym-addr { color: var(--info); }
.sym-size { color: var(--muted); text-align: right; }
.sym-empty, .sym-limit { color: var(--muted); padding: 16px; text-align: center; }
.sym-limit { padding: 6px; font-size: 12px; }
.sym-detail { border-top: 1px solid var(--border); padding-top: 12px; }
.sym-detail h4 { margin: 0 0 8px; font-size: 13px; }
.sym-members { margin-top: 8px; }
.sym-members h5 { margin: 0 0 4px; font-size: 12px; }
.sym-member { padding: 2px 0; color: var(--muted); font: 11px Consolas, monospace; }
.alert-warn { color: var(--warn); padding: 8px; border: 1px solid var(--warn); border-radius: 4px; }

@media (max-width: 720px) {
  .sym-item { grid-template-columns: minmax(140px, 1fr) 90px 44px; }
  .sym-addr { display: none; }
}
</style>
