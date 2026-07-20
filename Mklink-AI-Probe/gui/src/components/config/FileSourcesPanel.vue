<script setup lang="ts">
import { FolderOpen, Save, ScanSearch } from '@lucide/vue'
import { isMapFilePath, isSymbolFilePath } from '../../lib/desktopSettings'
import type { AxlStatus } from '../../types/mklink'

const props = defineProps<{
  symbolPath: string
  mapPath: string
  connected: boolean
  symbolStatus: AxlStatus
  browsing?: boolean
  saving?: boolean
  parsing?: boolean
}>()

const emit = defineEmits<{
  (event: 'update:symbolPath', value: string): void
  (event: 'update:mapPath', value: string): void
  (event: 'browse-symbol'): void
  (event: 'browse-map'): void
  (event: 'save'): void
  (event: 'parse'): void
}>()

function inputValue(event: Event): string {
  return (event.target as HTMLInputElement).value
}
</script>

<template>
  <section class="card source-panel" aria-labelledby="file-sources-title">
    <header class="panel-header">
      <div>
        <h2 id="file-sources-title">文件来源</h2>
        <span :class="['badge', symbolStatus.loaded ? 'badge-ok' : 'badge-warn']">
          {{ symbolStatus.loaded ? '符号已加载' : '符号未加载' }}
        </span>
      </div>
      <span v-if="symbolStatus.loaded" class="symbol-counts">
        {{ symbolStatus.variable_count || 0 }} 个固定可读变量 · {{ symbolStatus.struct_count || 0 }} 种结构体类型 · {{ symbolStatus.enum_count || 0 }} 种枚举类型
      </span>
    </header>

    <div class="source-row">
      <label for="symbol-path">AXF / ELF</label>
      <div class="path-control">
        <input
          id="symbol-path"
          class="form-input path-input"
          data-testid="symbol-path"
          :value="props.symbolPath"
          placeholder=".axf 或 .elf 文件路径"
          @input="emit('update:symbolPath', inputValue($event))"
        />
        <button
          class="btn icon-command"
          type="button"
          title="浏览 AXF 或 ELF 文件"
          data-testid="browse-symbol"
          :disabled="browsing"
          @click="emit('browse-symbol')"
        >
          <FolderOpen :size="15" aria-hidden="true" />
          浏览
        </button>
      </div>
    </div>
    <div
      data-testid="symbol-path-validation"
      :class="['path-validation', { invalid: symbolPath.trim() && !isSymbolFilePath(symbolPath) }]"
    >
      {{ !symbolPath.trim() ? '未配置 AXF / ELF 文件' : isSymbolFilePath(symbolPath) ? '路径格式有效' : '仅支持 .axf、.elf 或 .out 文件' }}
    </div>

    <div class="source-row">
      <label for="map-path">MAP</label>
      <div class="path-control">
        <input
          id="map-path"
          class="form-input path-input"
          data-testid="map-path"
          :value="props.mapPath"
          placeholder=".map 文件路径"
          @input="emit('update:mapPath', inputValue($event))"
        />
        <button
          class="btn icon-command"
          type="button"
          title="浏览 MAP 文件"
          data-testid="browse-map"
          :disabled="browsing"
          @click="emit('browse-map')"
        >
          <FolderOpen :size="15" aria-hidden="true" />
          浏览
        </button>
      </div>
    </div>
    <div
      data-testid="map-path-validation"
      :class="['path-validation', { invalid: mapPath.trim() && !isMapFilePath(mapPath) }]"
    >
      {{ !mapPath.trim() ? '未配置 MAP 文件' : isMapFilePath(mapPath) ? '路径格式有效' : '仅支持 .map 文件' }}
    </div>

    <div v-if="symbolStatus.error" class="alert alert-error">{{ symbolStatus.error }}</div>

    <footer class="panel-actions">
      <button
        class="btn"
        type="button"
        data-testid="save-files"
        :disabled="saving"
        @click="emit('save')"
      >
        <Save :size="15" aria-hidden="true" />
        {{ saving ? '保存中...' : '保存文件路径' }}
      </button>
      <button
        class="btn btn-primary"
        type="button"
        data-testid="parse-symbols"
        :disabled="parsing || !connected || !isSymbolFilePath(symbolPath)"
        @click="emit('parse')"
      >
        <ScanSearch :size="15" aria-hidden="true" />
        {{ parsing ? '解析中...' : '解析符号' }}
      </button>
      <span v-if="!connected" class="action-state">需先连接设备</span>
    </footer>
  </section>
</template>

<style scoped>
.source-panel {
  min-height: 270px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}

.panel-header > div {
  display: flex;
  align-items: center;
  gap: 10px;
}

.panel-header h2 {
  font-size: 15px;
  font-weight: 600;
}

.symbol-counts,
.action-state {
  color: var(--dim);
  font-size: 12px;
}

.source-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.path-validation {
  margin: -8px 0 12px 104px;
  color: var(--dim);
  font-size: 11px;
}

.path-validation.invalid {
  color: var(--danger, #dc2626);
}

.source-row label {
  color: var(--muted);
  font-size: 13px;
  text-align: right;
}

.path-control {
  display: flex;
  gap: 8px;
  min-width: 0;
}

.path-input {
  min-width: 0;
  font-family: var(--font-mono);
  font-size: 12px;
}

.icon-command,
.panel-actions .btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 20px;
  padding-left: 104px;
}

@media (max-width: 720px) {
  .panel-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .source-row {
    grid-template-columns: 1fr;
    gap: 6px;
  }

  .source-row label {
    text-align: left;
  }

  .panel-actions {
    padding-left: 0;
    flex-wrap: wrap;
  }

  .path-validation {
    margin-left: 0;
  }
}
</style>
