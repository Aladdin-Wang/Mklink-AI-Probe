import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Panel from './SerialRecordingPanel.vue'
const props = () => ({ status: { state: 'idle', active: false }, running: true, port: 'A', busy: false, error: '' })
describe('shared recording controls', () => {
  it('submits a file request with selected port and rotation bytes', async () => {
    const w = mount(Panel, { props: props() })
    await w.get('[data-testid="recording-path"]').setValue('E:/logs/new.csv')
    await w.findAll('select')[0]!.setValue('csv')
    await w.findAll('select')[1]!.setValue('current')
    await w.get('[data-testid="recording-size"]').setValue(2)
    await w.get('[data-testid="recording-start"]').trigger('click')
    expect(w.emitted('start')).toEqual([[{path:'E:/logs/new.csv', format:'csv', ports:['A'], max_size:2097152}]])
    w.unmount()
  })
  it('shows another client recording and permits stop even after UART stopped', async () => {
    const w = mount(Panel, { props: { ...props(), running: false, status: {state:'stopping',active:true,path:'E:/other.csv',ports:['B']} } })
    expect(w.get('[data-testid="recording-result"]').text()).toContain('E:/other.csv')
    expect(w.get('[data-testid="recording-start"]').attributes('disabled')).toBeDefined()
    expect(w.get('[data-testid="recording-path"]').attributes('disabled')).toBeDefined()
    await w.get('[data-testid="recording-stop"]').trigger('click')
    expect(w.emitted('stop')).toHaveLength(1)
    await w.setProps({busy:true})
    expect(w.get('[data-testid="recording-stop"]').attributes('disabled')).toBeDefined()
    w.unmount()
  })
  it('rejects invalid size and displays authoritative failure safely', async () => {
    const w = mount(Panel, { props: props() })
    await w.get('[data-testid="recording-path"]').setValue('E:/new.txt')
    for (const size of [-1, .5, 1048577]) {
      await w.get('[data-testid="recording-size"]').setValue(size)
      expect(w.get('[data-testid="recording-start"]').attributes('disabled')).toBeDefined()
    }
    await w.setProps({ status: {state:'failed',active:false,error:'<script>disk full</script>'} })
    expect(w.get('[role="alert"]').text()).toContain('disk full')
    expect(w.find('script').exists()).toBe(false)
    expect(w.emitted('start')).toBeUndefined()
    w.unmount()
  })
})
