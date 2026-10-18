import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 构建产物直接服务两个场景：
// 1) Web 端：FastAPI 静态托管（server/web_dist/）
// 2) Android：file:///android_asset/www/index.html 本地加载 + 按 manifest 热更新
// 因此 base 必须相对，target 需兼容旧系统 WebView（Android 8+）
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  base: './',
  build: {
    target: 'chrome80',
    cssTarget: 'chrome80',
    outDir: '../server/web_dist/app',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: {
          vue: ['vue', 'vue-router'],
        }
      }
    }
  },
  server: {
    port: 8638,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8637', changeOrigin: true }
    }
  }
})
