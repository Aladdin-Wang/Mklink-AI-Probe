import { readonly, ref } from 'vue'

export type AppLanguage = 'zh' | 'en'

const STORAGE_KEY = 'mklink_lang'

function initialLanguage(): AppLanguage {
  try {
    return typeof window !== 'undefined' && window.localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'zh'
  } catch {
    return 'zh'
  }
}

const activeLanguage = ref<AppLanguage>(initialLanguage())

function applyDocumentLanguage(language: AppLanguage): void {
  if (typeof document !== 'undefined') document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en'
}

applyDocumentLanguage(activeLanguage.value)

export const language = readonly(activeLanguage)

export function tr(chinese: string, english: string): string {
  return activeLanguage.value === 'zh' ? chinese : english
}

export function setLanguage(next: AppLanguage): void {
  if (activeLanguage.value === next) return
  activeLanguage.value = next
  applyDocumentLanguage(next)
  try { window.localStorage.setItem(STORAGE_KEY, next) } catch { /* persistence is optional */ }
}

export function toggleLanguage(): void {
  setLanguage(activeLanguage.value === 'zh' ? 'en' : 'zh')
}
