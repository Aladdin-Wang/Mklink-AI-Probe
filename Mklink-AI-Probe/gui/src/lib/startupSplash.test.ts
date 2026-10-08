import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

const indexSource = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')
const mainSource = readFileSync(resolve(process.cwd(), 'src/main.ts'), 'utf8')

describe('desktop startup splash', () => {
  it('uses a one-shot probe transition instead of replaying the cold startup', () => {
    vi.useFakeTimers()
    vi.stubGlobal('localStorage', { getItem: () => null })
    const previous = window.location.href
    history.replaceState(null, '', '/?runtime_transition=probe#/config')
    document.body.innerHTML = indexSource.slice(indexSource.indexOf('<body>') + 6, indexSource.indexOf('<script>'))
    const script = indexSource.split('<script>')[1]!.split('</script>')[0]!
    try {
      new Function(script)()
      expect(document.getElementById('startup-splash')?.classList.contains('is-probe-switch')).toBe(true)
      window.__MKLINK_STARTUP__?.update(22, 'Starting local service…')
      expect(document.getElementById('startup-status')?.textContent).toContain('切换下载器')
      expect(window.location.search).toBe('')
      expect(window.location.hash).toBe('#/config')
      window.__MKLINK_STARTUP__?.finish()
      vi.runAllTimers()
      expect(document.getElementById('startup-splash')).toBeNull()
    } finally {
      vi.clearAllTimers(); vi.useRealTimers()
      vi.unstubAllGlobals()
      document.body.innerHTML = ''
      history.replaceState(null, '', previous)
    }
  })
  it('renders the vector animation and progress UI before loading the application module', () => {
    const splashOffset = indexSource.indexOf('id="startup-splash"')
    const moduleOffset = indexSource.indexOf('src="/src/main.ts"')

    expect(splashOffset).toBeGreaterThan(0)
    expect(moduleOffset).toBeGreaterThan(splashOffset)
    expect(indexSource).toContain('class="startup-circuit"')
    expect(indexSource).toContain('prefers-reduced-motion:reduce')
    expect(indexSource).not.toContain('startup-probe.png')
    expect(indexSource).toContain('role="progressbar"')
    expect(indexSource).toContain('window.__MKLINK_STARTUP__')
  })

  it('keeps the splash visible through endpoint discovery and removes it after mount', () => {
    expect(mainSource.indexOf("updateStartup(22")).toBeLessThan(
      mainSource.indexOf('await initializeRuntimeEndpoint()'),
    )
    expect(mainSource.indexOf("updateStartup(80")).toBeGreaterThan(
      mainSource.indexOf('await initializeRuntimeEndpoint()'),
    )
    expect(mainSource.indexOf('createApp(App).use(router).mount')).toBeLessThan(
      mainSource.indexOf("window.__MKLINK_STARTUP__?.finish()"),
    )
  })
})
