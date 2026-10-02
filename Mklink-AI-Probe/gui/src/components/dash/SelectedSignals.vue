<template>
  <section class="selected-workspace">
    <header><strong>{{ tr('已选信号', 'Selected signals') }} · {{ paths.length }}</strong>
      <button @click="settings = !settings">{{ tr('整理', 'Organize') }}</button>
      <button @click="prefs.load()" :disabled="prefs.busy.value">{{ tr('刷新配置', 'Reload settings') }}</button>
    </header>
    <p v-if="prefs.error.value" role="alert">{{ prefs.error.value }}</p>
    <fieldset v-if="settings" :disabled="!prefs.ready.value || prefs.busy.value">
      <input v-model="newName" :placeholder="tr('分组或波形区名称', 'Group or plot name')" />
      <button @click="add('groups')">{{ tr('新增分组', 'New group') }}</button>
      <button @click="add('panes')">{{ tr('新增波形区', 'New plot') }}</button>
      <label>{{ tr('批量移动', 'Move checked') }}
        <select aria-label="批量分组" @change="batch('group', $event)"><option value="">{{ tr('未分组', 'Ungrouped') }}</option><option v-for="g in prefs.workspace.value.groups" :value="g.id">{{ g.name }}</option></select>
        <select aria-label="批量波形区" @change="batch('pane', $event)"><option v-for="p in prefs.workspace.value.panes" :value="p.id">{{ p.name }}</option></select>
      </label>
      <div v-for="kind in (['groups','panes'] as const)" :key="kind">
        <div class="section-editor" v-for="(section,index) in prefs.workspace.value[kind]" :key="section.id" draggable="true" @dragstart="drag = {kind, index}" @dragover.prevent @drop="reorder(kind,index)">
          <input :aria-label="kind === 'groups' ? '分组名称' : '波形区名称'" :value="drafts[kind + section.id] ?? section.name" @input="drafts[kind + section.id] = value($event)" @change="rename(kind,section.id,$event)" />
          <input v-if="kind === 'panes'" type="range" min="100" max="1000" step="10" :value="section.height" aria-label="波形区高度" @change="height(section.id,$event)" />
          <button :disabled="index === 0" @click="move(kind,index,-1)">↑</button><button :disabled="index === prefs.workspace.value[kind].length-1" @click="move(kind,index,1)">↓</button>
          <button :disabled="kind === 'panes' && prefs.workspace.value.panes.length === 1" @click="remove(kind,section.id)">×</button>
        </div>
      </div>
    </fieldset>
    <div class="selected-groups">
      <section v-for="group in groups" :key="group.id" @dragover.prevent @drop="dropSignal(group.id)">
        <button class="group-heading" :aria-expanded="!group.collapsed" @click="collapse(group.id)">{{ group.collapsed ? '▸' : '▾' }} {{ group.name }} · {{ group.paths.length }}</button>
        <div v-show="!group.collapsed" v-for="path in group.paths" :key="path" class="selected-signal" :class="{ emphasized: prefs.style(path).emphasis }" draggable="true" @dragstart.stop="dragPath = path">
          <div class="signal-heading">
            <input v-if="settings" type="checkbox" :value="path" v-model="checked" :aria-label="`选择 ${path}`" />
            <button :title="tr('显示或隐藏波形', 'Show or hide waveform')" @click="$emit('visibility', path, hidden?.has(path) ?? false)">{{ hidden?.has(path) ? '○' : '●' }}</button>
            <span :title="path">{{ prefs.style(path).alias || path }}</span><output>{{ formatValue(values[path]) }}</output>
            <button :aria-label="`强调 ${path}`" :aria-pressed="prefs.style(path).emphasis" @click="prefs.setStyle([path], { emphasis: !prefs.style(path).emphasis })"><b>B</b></button>
          </div>
          <div v-if="settings" class="signal-settings">
            <input :aria-label="`名称 ${path}`" :placeholder="path" :value="drafts[path] ?? prefs.style(path).alias" @input="drafts[path] = value($event)" @change="alias(path,$event)" maxlength="128" />
            <select :aria-label="`分组 ${path}`" :value="prefs.style(path).group" @change="assign(path,'group',$event)"><option value="">{{ tr('未分组', 'Ungrouped') }}</option><option v-for="g in prefs.workspace.value.groups" :value="g.id">{{ g.name }}</option></select>
            <select :aria-label="`波形区 ${path}`" :value="prefs.style(path).pane" @change="assign(path,'pane',$event)"><option v-for="p in prefs.workspace.value.panes" :value="p.id">{{ p.name }}</option></select>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useWatchWorkspace } from '../../composables/useWatchWorkspace'
import { tr } from '../../composables/useLanguage'
const props = defineProps<{ paths: string[]; values: Record<string, number | boolean>; hidden?: ReadonlySet<string> }>()
defineEmits<{ visibility: [path: string, visible: boolean] }>()
const drafts = reactive<Record<string,string>>({})
const prefs = useWatchWorkspace(), settings = ref(false), newName = ref(''), checked = ref<string[]>([]), ungroupedCollapsed = ref(false)
type Kind = 'groups' | 'panes'
const drag = ref<{kind: Kind; index: number} | null>(null)
let dragPath = ''
const groups = computed(() => [...prefs.workspace.value.groups, { id: '', name: tr('未分组','Ungrouped'), collapsed: ungroupedCollapsed.value }].map(g => ({...g, paths: props.paths.filter(p => prefs.style(p).group === g.id)})))
const formatValue = (v: number | boolean | undefined) => typeof v === 'number' ? Number.isInteger(v) ? String(v) : v.toPrecision(7) : v === undefined ? '—' : String(v)
const value = (event: Event) => (event.target as HTMLInputElement).value
function add(kind: Kind) { void prefs.update(w => w[kind].push({id: crypto.randomUUID(), name: newName.value.trim() || (kind==='groups' ? tr('新分组','New group') : tr('新波形区','New plot')), collapsed: false, height: 200})); newName.value='' }
function collapse(id: string) { if (!id) { ungroupedCollapsed.value=!ungroupedCollapsed.value; return }; void prefs.update(w => { const g=w.groups.find(g=>g.id===id)!;g.collapsed=!g.collapsed }) }
function assign(path: string, key: 'group'|'pane', e: Event) { void prefs.setStyle([path],{[key]:value(e)}) }
async function alias(path: string,e: Event) { await prefs.setStyle([path],{alias:value(e)}); if(!prefs.error.value)delete drafts[path] }
function batch(key: 'group'|'pane',e: Event) { void prefs.setStyle(checked.value.filter(p=>props.paths.includes(p)),{[key]:value(e)}) }
async function rename(kind: Kind,id: string,e: Event) { const name=value(e);await prefs.update(w=>{w[kind].find(p=>p.id===id)!.name=name});if(!prefs.error.value)delete drafts[kind+id] }
function height(id: string,e: Event) { const h=Number(value(e));void prefs.update(w=>{w.panes.find(p=>p.id===id)!.height=h}) }
function remove(kind: Kind,id: string) { void prefs.update(w=>{w[kind]=w[kind].filter(p=>p.id!==id); for(const s of Object.values(w.signals)) { if(kind==='groups'&&s.group===id)s.group='';if(kind==='panes'&&s.pane===id)s.pane=w.panes[0].id }}) }
function move(kind: Kind,index: number,delta: number) { void prefs.update(w=>{const a=w[kind];const [item]=a.splice(index,1);a.splice(index+delta,0,item)}) }
function reorder(kind: Kind,index: number) { if(drag.value?.kind===kind)move(kind,drag.value.index,index-drag.value.index);drag.value=null }
function dropSignal(group: string) { if(dragPath)void prefs.setStyle([dragPath],{group});dragPath='' }
let timer: ReturnType<typeof setInterval>
onMounted(() => { void prefs.load(); timer=setInterval(() => { if (!settings.value) void prefs.load() },3000) })
onUnmounted(() => clearInterval(timer))
</script>
<style scoped>
.selected-workspace { border-bottom: 1px solid var(--border); min-height: 80px; overflow: auto; max-height: 55%; flex-shrink: 0; }
header,.signal-heading,.section-editor,.signal-settings { display:flex; align-items:center; gap:5px; padding:4px; }
header strong,.signal-heading span { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
button,input,select { background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:4px; padding:3px; min-width:0; }
input { width:100%; } input[type=checkbox] { width:auto; } fieldset { border:0; padding:4px; }
.section-editor input { flex:1; } .group-heading { width:100%; text-align:left; background:var(--bg); }
.signal-settings { flex-wrap:wrap; } .signal-settings select { flex:1; width:40%; }
.emphasized .signal-heading { font-weight:700; } output { font-family:monospace; } p[role=alert] { color:var(--danger,#e66); }
</style>
