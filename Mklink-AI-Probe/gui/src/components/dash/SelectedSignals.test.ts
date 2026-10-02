import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import SelectedSignals from './SelectedSignals.vue'
import { useWatchWorkspace } from '../../composables/useWatchWorkspace'

afterEach(() => vi.unstubAllGlobals())
it('persists Chinese aliases and folding/assignments without acquisition calls', async () => {
  let revision=0
  let workspace:any={version:1,groups:[{id:'motor',name:'电机',collapsed:false,height:200}],panes:[{id:'a',name:'速度',height:200},{id:'b',name:'电流',height:200},{id:'c',name:'电压',height:200}],signals:{rpm:{alias:'目标转速',group:'motor',pane:'a',emphasis:false}}}
  const fetch=vi.fn(async (_url:any,init?:RequestInit)=> {
    if(init) {workspace=JSON.parse(String(init.body)).workspace;revision++}
    return {ok:true,json:async()=>({workspace:structuredClone(workspace),revision:String(revision)})}
  })
  vi.stubGlobal('fetch',fetch)
  const wrapper=mount(SelectedSignals,{props:{paths:['rpm','amps'],values:{rpm:800,amps:3}}})
  await flushPromises()
  expect(wrapper.text()).toContain('目标转速')
  const fold=wrapper.findAll('.group-heading')[0]
  await fold.trigger('click');await flushPromises()
  expect((wrapper.find('.selected-signal').element as HTMLElement).style.display).toBe('none')
  expect(workspace.groups[0].collapsed).toBe(true)
  await fold.trigger('click');await flushPromises()
  await wrapper.get('[aria-label="强调 rpm"]').trigger('click');await flushPromises()
  expect(workspace.signals.rpm.emphasis).toBe(true)
  await wrapper.findAll('header button')[0].trigger('click')
  const aliasInput=wrapper.get<HTMLInputElement>('[aria-label="名称 rpm"]')
  aliasInput.element.value='主轴转速'
  await aliasInput.trigger('input')
  await wrapper.setProps({values:{rpm:900,amps:4}})
  expect(aliasInput.element.value).toBe('主轴转速')
  await aliasInput.trigger('change');await flushPromises()
  await wrapper.get('[aria-label="波形区 rpm"]').setValue('c');await flushPromises()
  expect(workspace.signals.rpm).toMatchObject({alias:'主轴转速',pane:'c'})
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
