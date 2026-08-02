// 极简的 Tauri 桥接：在 Tauri 环境（window.__TAURI__）调原生能力；
// 浏览器环境降级为 toast 警告。
import { useToast } from './useToast'
import { tr } from './useLanguage'

export function useTauri() {
  const toast = useToast()

  async function openInExplorer(path: string | null): Promise<void> {
    if (!path) {
      toast.warn(tr('无固件目录路径', 'Firmware directory path is unavailable'))
      return
    }
    const tauri: any = (window as any).__TAURI__
    if (!tauri?.opener?.openPath) {
      toast.warn(tr('仅 Tauri 桌面应用支持打开目录', 'Opening folders is supported only in the Tauri desktop app'))
      return
    }
    try {
      await tauri.opener.openPath(path)
    } catch (e: any) {
      toast.warn(tr(`打开目录失败：${e?.message ?? e}`, `Failed to open folder: ${e?.message ?? e}`))
    }
  }

  return { openInExplorer }
}
