<template>
  <div class="inline-name">
    <input v-if="editing" ref="input" v-model="draft" :aria-label="label" :placeholder="fallback" maxlength="128"
      :readonly="saving" @blur="save" @keydown="key" @compositionstart="composing = true" @compositionend="composing = false" />
    <template v-else>
      <span class="name-text" :title="title || display" @dblclick="edit">{{ display }}</span>
      <button class="rename" :aria-label="label" :title="tr('重命名（双击名称）', 'Rename (double-click name)')" @click="edit">✎</button>
    </template>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { tr } from '../../composables/useLanguage'
const props = defineProps<{ value: string; fallback?: string; title?: string; label: string; commit: (name: string) => Promise<boolean> }>()
const editing = ref(false), saving = ref(false), draft = ref(''), composing = ref(false), input = ref<HTMLInputElement>()
const display = computed(() => props.value || props.fallback || '')
async function edit() {
  if (editing.value) return
  draft.value = props.value; editing.value = true
  await nextTick(); input.value?.focus(); input.value?.select()
}
async function save() {
  if (!editing.value || saving.value || composing.value) return
  const name = draft.value.trim()
  if (name === props.value) { editing.value = false; return }
  saving.value = true
  try { if (await props.commit(name)) editing.value = false }
  finally { saving.value = false }
}
function key(event: KeyboardEvent) {
  if (event.isComposing || composing.value || event.keyCode === 229) return
  if (event.key === 'Escape' && !saving.value) { event.preventDefault(); editing.value = false }
  if (event.key === 'Enter') { event.preventDefault(); void save() }
}
</script>
<style scoped>
.inline-name { display:flex; align-items:center; flex:1; min-width:0; gap:2px; }
.name-text { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; user-select:text; cursor:text; }
.rename { opacity:0; flex-shrink:0; border:0; background:transparent; color:var(--text-muted); cursor:pointer; padding:2px; }
.inline-name:hover .rename,.inline-name:focus-within .rename { opacity:1; }
input { width:100%; min-width:0; box-sizing:border-box; background:var(--surface); color:var(--text); border:1px solid var(--accent); border-radius:4px; padding:3px; font:inherit; }
@media (hover:none) { .rename { opacity:1; } }
</style>
