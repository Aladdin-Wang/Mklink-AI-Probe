import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('global application language', () => {
  beforeEach(() => {
    const values = new Map<string, string>()
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        clear: () => values.clear(),
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
      },
    })
    window.localStorage.clear()
    document.documentElement.removeAttribute('lang')
    vi.resetModules()
  })

  it('defaults to Chinese and switches all shared translations to English', async () => {
    const locale = await import('./useLanguage')

    expect(locale.language.value).toBe('zh')
    expect(locale.tr('配置', 'Config')).toBe('配置')
    locale.toggleLanguage()
    expect(locale.language.value).toBe('en')
    expect(locale.tr('配置', 'Config')).toBe('Config')
    expect(window.localStorage.getItem('mklink_lang')).toBe('en')
    expect(document.documentElement.lang).toBe('en')
  })

  it('loads the persisted English preference', async () => {
    window.localStorage.setItem('mklink_lang', 'en')
    const locale = await import('./useLanguage')

    expect(locale.language.value).toBe('en')
    expect(locale.tr('在线烧录', 'Online Flash')).toBe('Online Flash')
  })
})
