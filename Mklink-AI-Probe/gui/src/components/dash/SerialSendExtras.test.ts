import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Panel from './SerialSendExtras.vue'
const props = () => ({port:'A',ports:['A','B'],running:true,fileActive:false,busy:false,error:'',notice:'',results:null})
async function choose(w:any,file:File) {
  Object.defineProperty(w.get('[data-testid="raw-file"]').element,'files',{value:[file],configurable:true})
  await w.get('[data-testid="raw-file"]').trigger('change')
}
describe('shared broadcast and file controls',()=>{
  it('shows explicit broadcast targets and per-port partial failure',async()=>{
    const w=mount(Panel,{props:props()})
    await w.get('[data-testid="broadcast-data"]').setValue('Q')
    await w.get('[data-testid="broadcast-send"]').trigger('click')
    expect(w.emitted('broadcast')).toEqual([[{data:'Q',hex:false}]])
    await w.setProps({results:{A:{ok:false,error:'unknown result, no retry'},B:{ok:true,bytes:1}}})
    expect(w.get('[data-testid="broadcast-results"]').text()).toContain('unknown result')
    expect(w.text()).toContain('A, B')
    w.unmount()
  })
  it('captures selected file and port without reading or resending it in the browser',async()=>{
    const onFile=vi.fn();const w=mount(Panel,{props:{...props(),onFile}});const file=new File([new Uint8Array([0,255])],'raw.bin')
    await choose(w,file);await w.get('[data-testid="raw-file-send"]').trigger('click')
    await w.setProps({port:'B'})
    expect(w.emitted('file')).toEqual([[file,false,'A']])
    w.unmount();expect(onFile).toHaveBeenCalledTimes(1)
  })
  it('rejects oversized files and locks an active sequence',async()=>{
    const w=mount(Panel,{props:props()})
    await choose(w,new File([new Uint8Array(65537)],'large.bin'))
    await w.get('[data-testid="raw-file-send"]').trigger('click')
    expect(w.get('[role="alert"]').exists()).toBe(true)
    expect(w.emitted('file')).toBeUndefined()
    await w.setProps({fileActive:true})
    expect(w.get('[data-testid="raw-file-send"]').attributes('disabled')).toBeDefined()
    w.unmount()
  })
})
