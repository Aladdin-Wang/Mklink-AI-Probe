<template>
  <section ref="workspaceElement" class="selected-workspace">
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
      <section v-for="group in groups" :key="group.id" :data-watch-group="group.id" :class="{ 'drop-target': dragTarget === group.id }">
        <div class="group-heading">
          <button :aria-label="`折叠 ${group.name}`" :aria-expanded="!group.collapsed" @click="collapse(group.id)">{{ group.collapsed ? '▸' : '▾' }}</button>
          <InlineWatchName :value="group.name" :label="`重命名分组 ${group.name}`" :commit="name => rename(group.id,name)" />
          <small>{{ group.paths.length }}</small>
          <template v-if="settings">
            <button :disabled="prefs.busy.value || groups[0].id === group.id" title="上移分组" @click="move(group.id,-1)">↑</button>
            <button :disabled="prefs.busy.value || groups[groups.length-1].id === group.id" title="下移分组" @click="move(group.id,1)">↓</button>
            <button :disabled="prefs.busy.value || groups.length === 1" title="删除分组，信号移入第一个分组" @click="remove(group.id)">×</button>
          </template>
        </div>
        <p v-if="!group.paths.length" class="hint empty-group">{{ tr('空组：移入信号后显示波形', 'Empty: move signals here to show a plot') }}</p>
        <div v-show="!group.collapsed" v-for="path in group.paths" :key="path" class="selected-signal" :class="{ emphasized: prefs.style(path).emphasis }">
          <div class="signal-heading">
            <button class="drag-handle" :aria-label="`移动 ${path} 到分组`" :disabled="!prefs.ready.value" :title="tr('按住拖入目标分组', 'Drag into a group')" @pointerdown="startDrag(path,$event)" @pointermove="dragMove" @pointerup="finishDrag" @pointercancel="cancelDrag" @lostpointercapture="cancelDrag" @dragstart.prevent>⠿</button>
            <input v-if="settings" type="checkbox" :value="path" v-model="checked" :aria-label="`选择 ${path}`" />
            <button :title="tr('显示或隐藏波形', 'Show or hide waveform')" @click="$emit('visibility', path, hidden?.has(path) ?? false)">{{ hidden?.has(path) ? '○' : '●' }}</button>
            <InlineWatchName :value="prefs.style(path).alias" :fallback="path" :title="path" :label="`重命名变量 ${path}`" :commit="name => prefs.setStyle([path],{alias:name})" /><output>{{ formatValue(values[path]) }}</output>
            <button :aria-label="`强调 ${path}`" :aria-pressed="prefs.style(path).emphasis" @click="toggleStyle(path,'emphasis')"><b>B</b></button>
            <button :aria-label="`采样点 ${path}`" :title="tr('仅显示采样点，不连线', 'Sample points only, no lines')" :aria-pressed="prefs.style(path).renderMode === 'points'" @click="toggleStyle(path,'renderMode')">{{ tr('点','Dots') }}</button>
          </div>

        </div>
      </section>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useWatchWorkspace } from '../../composables/useWatchWorkspace'
import InlineWatchName from './InlineWatchName.vue'
import { tr } from '../../composables/useLanguage'
const props = defineProps<{ paths: string[]; values: Record<string, number | boolean>; hidden?: ReadonlySet<string> }>()
defineEmits<{ visibility: [path: string, visible: boolean] }>()
const prefs = useWatchWorkspace(), settings = ref(false), newName = ref(''), checked = ref<string[]>([])
const workspaceElement = ref<HTMLElement>(), dragTarget = ref('')
let drag: {path:string; pointerId:number; x:number; y:number; moved:boolean; handle:HTMLElement} | undefined
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
async function batch(e: Event) { await prefs.setStyle(checked.value.filter(p=>props.paths.includes(p)),{group:value(e)}); (e.target as HTMLSelectElement).value='' }
function rename(id: string,name: string) { return prefs.update(w=>{const group=w.groups.find(p=>p.id===id);if(group)group.name=name || group.name}) }
function remove(id: string) { void prefs.update(w=>{w.groups=w.groups.filter(p=>p.id!==id); if(w.defaultGroup===id)w.defaultGroup=w.groups[0].id; for(const s of Object.values(w.signals)) if(s.group===id){s.group=w.groups[0].id;s.pane=s.group} }) }
function move(id: string,delta: number) { void prefs.update(w=>{const a=w.groups,index=a.findIndex(g=>g.id===id);const [item]=a.splice(index,1);a.splice(index+delta,0,item)}) }
function startDrag(path: string,event: PointerEvent) {
  if(event.button !== 0 || drag || !prefs.ready.value) return
  event.preventDefault()
  const handle=event.currentTarget as HTMLElement
  drag={path,pointerId:event.pointerId,x:event.clientX,y:event.clientY,moved:false,handle}
  handle.setPointerCapture(event.pointerId)
}
function dragMove(event: PointerEvent) {
  if(!drag || drag.pointerId !== event.pointerId) return
  if(Math.hypot(event.clientX-drag.x,event.clientY-drag.y)<5 && !drag.moved) return
  drag.moved=true
  const root=workspaceElement.value
  if(!root) return
  const bounds=root.getBoundingClientRect()
  if(event.clientX>=bounds.left && event.clientX<=bounds.right) {
    if(event.clientY<bounds.top+24 && event.clientY>=bounds.top)root.scrollTop-=12
    if(event.clientY>bounds.bottom-24 && event.clientY<=bounds.bottom)root.scrollTop+=12
  }
  const target=document.elementFromPoint(event.clientX,event.clientY)?.closest<HTMLElement>('[data-watch-group]')
  const id=target && root.contains(target) ? target.dataset.watchGroup || '' : ''
  dragTarget.value=id !== prefs.style(drag.path).group ? id : ''
}
function finishDrag(event: PointerEvent) {
  if(!drag || drag.pointerId !== event.pointerId) return
  dragMove(event)
  const path=drag.path, group=drag.moved ? dragTarget.value : ''
  cancelDrag()
  if(group && props.paths.includes(path))void prefs.setStyle([path],{group})
}
function cancelDrag() {
  const previous=drag;drag=undefined;dragTarget.value=''
  if(previous?.handle.hasPointerCapture(previous.pointerId))previous.handle.releasePointerCapture(previous.pointerId)
}
function cancelDragKey(event: KeyboardEvent) { if(event.key==='Escape')cancelDrag() }
let timer: ReturnType<typeof setInterval>
onMounted(() => { window.addEventListener('keydown',cancelDragKey); window.addEventListener('blur',cancelDrag); void prefs.load(); timer=setInterval(() => { if (!settings.value) void prefs.load() },3000) })
onUnmounted(() => {clearInterval(timer);cancelDrag();window.removeEventListener('keydown',cancelDragKey);window.removeEventListener('blur',cancelDrag)})
</script>
<style scoped>
.selected-workspace { border-bottom: 1px solid var(--border); min-height: 80px; overflow: auto; max-height: 55%; flex-shrink: 0; }
header,.signal-heading,.section-editor { display:flex; align-items:center; gap:5px; padding:4px; }
header strong { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
button { white-space:nowrap; flex-shrink:0; }
.section-editor select { flex:1; min-width:0; }
button,input,select { background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:4px; padding:3px; min-width:0; }
input { width:100%; } input[type=checkbox] { width:auto; } fieldset { border:0; padding:4px; }
.section-editor input { flex:1; } .group-heading { display:flex; align-items:center; gap:6px; padding:4px; background:var(--bg); }

.drag-handle { cursor:grab; user-select:none; touch-action:none; padding:2px; border-color:transparent; }
.drag-handle:active { cursor:grabbing; }
.drop-target { outline:2px solid var(--accent); outline-offset:-2px; background:var(--surface); }
.hint { font-size:12px; color:var(--text-muted); margin:4px; }
button[aria-pressed=true] { color:var(--accent); border-color:var(--accent); }

.emphasized .signal-heading { font-weight:700; } output { font-family:monospace; max-width:28%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } p[role=alert] { color:var(--danger,#e66); }
</style>
