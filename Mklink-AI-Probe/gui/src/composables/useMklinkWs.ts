import { ref } from 'vue'
import type { JsonRpcRequest, JsonRpcResponse } from '../types/mklink'
import { WS_BASE } from '../lib/runtimeEndpoint'

let ws: WebSocket | null = null
let rpcId = 0
const pending = new Map<number | string, {
  resolve: (v: unknown) => void
  reject: (e: Error) => void
}>()

const connected = ref(false)
const lastError = ref<string | null>(null)

export function useMklinkWs() {
  function connect(token?: string, url?: string) {
    if (ws && ws.readyState === WebSocket.OPEN) return

    const base = url || WS_BASE
    const wsUrl = base ? `${base}/ws` : `${location.protocol.replace('http', 'ws')}//${location.host}/ws`
    ws = new WebSocket(wsUrl)
    ws.onopen = () => {
      connected.value = true
      lastError.value = null
      if (token) {
        rpc('auth', { token }).catch(() => {})
      }
    }
    ws.onclose = () => {
      connected.value = false
      for (const [, p] of pending) {
        p.reject(new Error('WebSocket closed'))
      }
      pending.clear()
    }
    ws.onerror = () => {
      lastError.value = 'WebSocket connection error'
    }
    ws.onmessage = (event) => {
      try {
        const msg: JsonRpcResponse = JSON.parse(event.data)
        if (msg.id != null && pending.has(msg.id)) {
          const p = pending.get(msg.id)!
          pending.delete(msg.id)
          if (msg.error) {
            p.reject(new Error(msg.error.message))
          } else {
            p.resolve(msg.result)
          }
        }
      } catch {
        // ignore non-JSON messages
      }
    }
  }

  function disconnect() {
    if (ws) {
      ws.close()
      ws = null
    }
  }

  function rpc(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
    return new Promise((resolve, reject) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket not connected'))
        return
      }
      const id = ++rpcId
      const msg: JsonRpcRequest = {
        jsonrpc: '2.0',
        method,
        params,
        id,
      }
      pending.set(id, { resolve, reject })
      ws.send(JSON.stringify(msg))
    })
  }

  return {
    wsConnected: connected,
    wsLastError: lastError,
    connect,
    disconnect,
    rpc,
  }
}
