import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import SelectedSignals from './SelectedSignals.vue'
import { useWatchWorkspace } from '../../composables/useWatchWorkspace'

afterEach(() => vi.unstubAllGlobals())
it('persists Chinese aliases and folding/assignments without acquisition calls', async () => {
  let revision=0
  let workspace:any={version:2,groups:[{id:'motor',name:'电机',collapsed:false,height:200},{id:'c',name:'电压',collapsed:false,height:200}],panes:[{id:'a',name:'速度',height:200},{id:'b',name:'电流',height:200},{id:'c',name:'电压',height:200}],signals:{rpm:{alias:'目标转速',group:'motor',pane:'a',emphasis:false}}}
  const fetch=vi.fn(async (_url:any,init?:RequestInit)=> {
    if(init) {workspace=JSON.parse(String(init.body)).workspace;revision++}
    return {ok:true,json:async()=>({workspace:structuredClone(workspace),revision:String(revision)})}
  })
  vi.stubGlobal('fetch',fetch)
  const wrapper=mount(SelectedSignals,{props:{paths:['rpm','amps'],values:{rpm:800,amps:3}}})
  await flushPromises()
  expect(wrapper.text()).toContain('目标转速')
  const fold=wrapper.findAll('.group-heading button')[0]
  await fold.trigger('click');await flushPromises()
  expect((wrapper.find('.selected-signal').element as HTMLElement).style.display).toBe('none')
  expect(workspace.groups[0].collapsed).toBe(true)
  await fold.trigger('click');await flushPromises()
  await wrapper.get('[aria-label="强调 rpm"]').trigger('click');await flushPromises()
  expect(workspace.signals.rpm.emphasis).toBe(true)
  await wrapper.findAll('header button')[0].trigger('click')
  await wrapper.get('button[aria-label="重命名变量 rpm"]').trigger('click')
  const aliasInput=wrapper.get<HTMLInputElement>('input[aria-label="重命名变量 rpm"]')
  aliasInput.element.value='主轴转速'
  await aliasInput.trigger('input')
  await wrapper.setProps({values:{rpm:900,amps:4}})
  expect(aliasInput.element.value).toBe('主轴转速')
  await aliasInput.trigger('blur');await flushPromises()
  await wrapper.get('[aria-label="选择 rpm"]').setValue(true)
  await wrapper.get('[aria-label="批量分组"]').setValue('c');await flushPromises()
  await wrapper.get('[aria-label="选择 rpm"]').setValue(false)
  expect(workspace.signals.rpm).toMatchObject({alias:'主轴转速',pane:'c',group:'c'})
  await wrapper.get('[aria-label="采样点 rpm"]').trigger('click');await flushPromises()
  expect(workspace.signals.rpm.renderMode).toBe('points')
  expect(workspace.signals.rpm.emphasis).toBe(true)
  expect(wrapper.text()).not.toContain('新增波形区')
  expect(wrapper.find('.signal-settings').exists()).toBe(false)
  expect(wrapper.find('.group-heading .name-text').element.tagName).toBe('SPAN')
  expect(wrapper.find('[aria-label="分组 rpm"]').exists()).toBe(false)
  await wrapper.get('[aria-label="选择 amps"]').setValue(true)
  await wrapper.get('[placeholder="分组名称"]').setValue('电流')
  await wrapper.get('[placeholder="分组名称"]').trigger('keydown', {key:'Enter'});await flushPromises()
  expect(workspace.groups.at(-1).name).toBe('电流')
  expect(workspace.signals.amps.group).toBe(workspace.groups.at(-1).id)
  expect(workspace.signals.amps.pane).toBe(workspace.signals.amps.group)
  const handle=wrapper.get('[aria-label="移动 rpm 到分组"]')
  Object.assign(handle.element,{setPointerCapture:vi.fn(),hasPointerCapture:()=>true,releasePointerCapture:vi.fn()})
  const destination=wrapper.findAll('.selected-groups > section').at(-1)!.element
  Object.defineProperty(document,'elementFromPoint',{configurable:true,value:vi.fn(()=>destination)})
  await handle.trigger('pointerdown',{button:0,pointerId:1,clientX:10,clientY:10})
  await handle.trigger('pointermove',{pointerId:1,clientX:30,clientY:40})
  expect(wrapper.find('.drop-target').exists()).toBe(true)
  await handle.trigger('pointerup',{pointerId:1,clientX:30,clientY:40});await flushPromises()
  expect(workspace.signals.rpm.group).toBe(workspace.groups.at(-1).id)
  expect(wrapper.find('.drop-target').exists()).toBe(false)
  const movedHandle=wrapper.get('[aria-label="移动 rpm 到分组"]')
  Object.assign(movedHandle.element,{setPointerCapture:vi.fn(),hasPointerCapture:()=>true,releasePointerCapture:vi.fn()})
  Object.defineProperty(document,'elementFromPoint',{configurable:true,value:vi.fn(()=>wrapper.find('.selected-groups > section').element)})
  const savedGroup=workspace.signals.rpm.group
  await movedHandle.trigger('pointerdown',{button:0,pointerId:2,clientX:10,clientY:10})
  await movedHandle.trigger('pointermove',{pointerId:2,clientX:30,clientY:40})
  window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))
  await movedHandle.trigger('pointerup',{pointerId:2,clientX:30,clientY:40});await flushPromises()
  expect(workspace.signals.rpm.group).toBe(savedGroup)
  Object.defineProperty(document,'elementFromPoint',{configurable:true,value:vi.fn(()=>document.body)})
  await movedHandle.trigger('pointerdown',{button:0,pointerId:3,clientX:10,clientY:10})
  await movedHandle.trigger('pointerup',{pointerId:3,clientX:200,clientY:200});await flushPromises()
  expect(workspace.signals.rpm.group).toBe(savedGroup)
  delete (document as any).elementFromPoint
  expect(fetch.mock.calls.every(([url])=>String(url).endsWith('/workspace'))).toBe(true)
  wrapper.unmount()
})
it('keeps current presentation on failed save and exposes a reload path',async()=>{
  const prefs=useWatchWorkspace()
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,json:async()=>({detail:'Workspace changed in another window'})})))
  const before=JSON.stringify(prefs.workspace.value)
  await prefs.setStyle(['rpm'],{alias:'不可覆盖'})
  expect(JSON.stringify(prefs.workspace.value)).toBe(before)
  expect(prefs.error.value).toContain('another window')
})


it('serializes rapid display edits and retains both changes with fresh revisions', async()=>{
  const prefs=useWatchWorkspace()
  let revision=0
  let workspace:any={version:2,defaultGroup:'main',groups:[{id:'main',name:'默认分组',collapsed:false,height:200}],panes:[{id:'main',name:'默认分组',height:200}],signals:{}}
  let release: (()=>void)|undefined
  vi.stubGlobal('fetch',vi.fn(async (_url:any,init?:RequestInit)=>{
    if(init){
      const body=JSON.parse(String(init.body))
      expect(body.revision).toBe(String(revision))
      if(revision===0) await new Promise<void>(resolve=>{release=resolve})
      workspace=body.workspace;revision++
    }
    return {ok:true,json:async()=>({workspace:structuredClone(workspace),revision:String(revision)})}
  }))
  await prefs.load()
  const first=prefs.setStyle(['rpm'],{alias:'中文速度'})
  const second=prefs.setStyle(['rpm'],{renderMode:'points'})
  await flushPromises()
  expect(revision).toBe(0)
  release!()
  expect(await first).toBe(true)
  expect(await second).toBe(true)
  expect(revision).toBe(2)
  expect(prefs.style('rpm')).toMatchObject({alias:'中文速度',renderMode:'points'})
  expect(prefs.busy.value).toBe(false)
})
