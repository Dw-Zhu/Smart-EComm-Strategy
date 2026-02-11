import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue' // 注意这里多了一个 /plugin-

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    }
  }
})