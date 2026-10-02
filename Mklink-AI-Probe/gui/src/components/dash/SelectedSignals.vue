<template>
  <section class="selected-workspace">
    <header><strong>{{ tr('已选信号', 'Selected signals') }} · {{ paths.length }}</strong>
      <button @click="settings = !settings">{{ settings ? tr('完成', 'Done') : tr('整理', 'Organize') }}</button>
      <button @click="prefs.load()" :disabled="prefs.busy.value">{{ tr('刷新配置', 'Reload settings') }}</button>
    </header>
    <p v-if="prefs.error.value" role="alert">{{ prefs.error.value }}</p>
    <fieldset v-if="settings" :disabled="!prefs.ready.value || prefs.busy.value">
      <p class="hint">{{ tr('分组即波形区；空组不占图，折叠不影响采样。', 'One plot per group. Empty groups take no plot space; folding keeps sampling.') }}</p>
      <div class="section-editor">
        <input v-model="newName" maxlength="128" :placeholder="tr('分组名称', 'Group name')" @keydown.enter.prevent="add()" />
        <button :disabled="prefs.workspace.value.groups.length >= 128" @click="add()">{{ tr('新增分组', 'New group') }}</button>
      </div>
      <div class="section-editor">
        <button @click="checked = checked.length === paths.length ? [] : [...paths]">{{ checked.length === paths.length && paths.length ? tr('清空勾选','Clear checks') : tr('全选','Select all') }}</button>
        <select aria-label="批量分组" :value="''" :disabled="!checked.length" @change="batch($event)">
          <option value="" disabled>{{ tr('移动到分组…', 'Move to group…') }} ({{ checked.length }})</option>
          <option v-for="g in prefs.workspace.value.groups" :key="g.id" :value="g.id">{{ g.name }}</option>
        </select>
      </div>
    </fieldset>
    <div class="selected-groups">
      <section v-for="group in groups" :key="group.id" @dragover.prevent @drop="dropSignal(group.id)">
        <div class="group-heading">
          <button :aria-label="`折叠 ${group.name}`" :aria-expanded="!group.collapsed" @click="collapse(group.id)">{{ group.collapsed ? '▸' : '▾' }}</button>
          <span class="group-name">{{ group.name }}</span><small>{{ group.paths.length }}</small>
        </div>
        <fieldset v-if="settings" class="section-editor" :disabled="!prefs.ready.value || prefs.busy.value">
          <input aria-label="分组名称" :value="drafts['group:' + group.id] ?? group.name" maxlength="128" @input="drafts['group:' + group.id] = value($event)" @change="rename(group.id,$event)" @keydown.enter="($event.target as HTMLInputElement).blur()" />
          <button :disabled="groups[0].id === group.id" title="上移分组" @click="move(group.id,-1)">↑</button>
          <button :disabled="groups[groups.length-1].id === group.id" title="下移分组" @click="move(group.id,1)">↓</button>
          <button :disabled="groups.length === 1" title="删除分组，信号移入第一个分组" @click="remove(group.id)">×</button>
        </fieldset>
        <p v-if="!group.paths.length" class="hint empty-group">{{ tr('空组：移入信号后显示波形', 'Empty: move signals here to show a plot') }}</p>
        <div v-show="!group.collapsed" v-for="path in group.paths" :key="path" class="selected-signal" :class="{ emphasized: prefs.style(path).emphasis }">
          <div class="signal-heading">
            <span v-if="settings" class="drag-handle" draggable="true" title="拖动到分组" @dragstart.stop="dragPath = path" @dragend="dragPath = ''">⠿</span>
            <input v-if="settings" type="checkbox" :value="path" v-model="checked" :aria-label="`选择 ${path}`" />
            <button :title="tr('显示或隐藏波形', 'Show or hide waveform')" @click="$emit('visibility', path, hidden?.has(path) ?? false)">{{ hidden?.has(path) ? '○' : '●' }}</button>
            <span :title="path">{{ prefs.style(path).alias || path }}</span><output>{{ formatValue(values[path]) }}</output>
            <button :aria-label="`强调 ${path}`" :aria-pressed="prefs.style(path).emphasis" @click="toggleStyle(path,'emphasis')"><b>B</b></button>
            <button :aria-label="`采样点 ${path}`" :title="tr('仅显示采样点，不连线', 'Sample points only, no lines')" :aria-pressed="prefs.style(path).renderMode === 'points'" @click="toggleStyle(path,'renderMode')">{{ tr('点','Dots') }}</button>
          </div>
          <div v-if="settings" class="signal-settings">
            <input :aria-label="`名称 ${path}`" :placeholder="path" :value="drafts[path] ?? prefs.style(path).alias" @input="drafts[path] = value($event)" @change="alias(path,$event)" @keydown.enter="($event.target as HTMLInputElement).blur()" maxlength="128" />
            <select :aria-label="`分组 ${path}`" :value="prefs.style(path).group" @change="assign(path,$event)"><option v-for="g in prefs.workspace.value.groups" :key="g.id" :value="g.id">{{ g.name }}</option></select>
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
const prefs = useWatchWorkspace(), settings = ref(false), newName = ref(''), checked = ref<string[]>([])
let dragPath = ''
const groups = computed(() => prefs.workspace.value.groups.map(g => ({...g, paths: props.paths.filter(p => prefs.style(p).group === g.id)})))
const formatValue = (v: number | boolean | undefined) => typeof v === 'number' ? Number.isInteger(v) ? String(v) : v.toPrecision(7) : v === undefined ? '—' : String(v)
const value = (event: Event) => (event.target as HTMLInputElement).value
async function add() {
  if(prefs.workspace.value.groups.length >= 128) return
  const id=crypto.randomUUID(); let name=newName.value.trim()
  if(!name) {let n=1; do {name=tr('分组 ','Group ')+n++} while(prefs.workspace.value.groups.some(g=>g.name===name))}
  const saved=await prefs.update(w => {
    w.groups.push({id, name, collapsed: false, height: 200})
    for(const path of checked.value.filter(p=>props.paths.includes(p))) w.signals[path]={...prefs.style(path),group:id,pane:id}
  })
  if(saved) {newName.value='';checked.value=[]}
}
function toggleStyle(path: string, key: 'emphasis'|'renderMode') { void prefs.update(w=>{const current=w.signals[path] || {...prefs.style(path)}; w.signals[path]={...current,...(key==='emphasis' ? {emphasis:!current.emphasis} : {renderMode:current.renderMode==='points' ? 'line' as const : 'points' as const})} }) }
function collapse(id: string) { void prefs.update(w => { const g=w.groups.find(g=>g.id===id)!;g.collapsed=!g.collapsed }) }
function assign(path: string, e: Event) { void prefs.setStyle([path],{group:value(e)}) }
async function alias(path: string,e: Event) { const saved=await prefs.setStyle([path],{alias:value(e)}); if(saved)delete drafts[path] }
async function batch(e: Event) { await prefs.setStyle(checked.value.filter(p=>props.paths.includes(p)),{group:value(e)}); (e.target as HTMLSelectElement).value='' }
async function rename(id: string,e: Event) { const name=value(e).trim();const saved=await prefs.update(w=>{const group=w.groups.find(p=>p.id===id)!;group.name=name || group.name});if(saved)delete drafts['group:'+id] }
function remove(id: string) { void prefs.update(w=>{w.groups=w.groups.filter(p=>p.id!==id); if(w.defaultGroup===id)w.defaultGroup=w.groups[0].id; for(const s of Object.values(w.signals)) if(s.group===id){s.group=w.groups[0].id;s.pane=s.group} }) }
function move(id: string,delta: number) { void prefs.update(w=>{const a=w.groups,index=a.findIndex(g=>g.id===id);const [item]=a.splice(index,1);a.splice(index+delta,0,item)}) }
function dropSignal(group: string) { if(dragPath)void prefs.setStyle([dragPath],{group});dragPath='' }
let timer: ReturnType<typeof setInterval>
onMounted(() => { void prefs.load(); timer=setInterval(() => { if (!settings.value) void prefs.load() },3000) })
onUnmounted(() => clearInterval(timer))
</script>
<style scoped>
.selected-workspace { border-bottom: 1px solid var(--border); min-height: 80px; overflow: auto; max-height: 55%; flex-shrink: 0; }
header,.signal-heading,.section-editor,.signal-settings { display:flex; align-items:center; gap:5px; padding:4px; }
header strong,.signal-heading span { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
button { white-space:nowrap; flex-shrink:0; }
.section-editor select { flex:1; min-width:0; }
button,input,select { background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:4px; padding:3px; min-width:0; }
input { width:100%; } input[type=checkbox] { width:auto; } fieldset { border:0; padding:4px; }
.section-editor input { flex:1; } .group-heading { display:flex; align-items:center; gap:6px; padding:4px; background:var(--bg); }
.group-name { flex:1; user-select:text; cursor:text; overflow-wrap:anywhere; }
.drag-handle { flex:0 !important; cursor:grab; user-select:none; }
.hint { font-size:12px; color:var(--text-muted); margin:4px; }
button[aria-pressed=true] { color:var(--accent); border-color:var(--accent); }
.signal-settings { flex-wrap:wrap; } .signal-settings select { flex:1; width:40%; }
.emphasized .signal-heading { font-weight:700; } output { font-family:monospace; } p[role=alert] { color:var(--danger,#e66); }
</style>
