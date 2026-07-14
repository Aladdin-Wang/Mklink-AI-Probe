import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

const host = process.env.TAURI_DEV_HOST;

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'happy-dom',
    globals: true,
    // Memory gates use process.memoryUsage(); parallel files contaminate their baseline.
    fileParallelism: false,
  },
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 5174,
        }
      : undefined,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
})
