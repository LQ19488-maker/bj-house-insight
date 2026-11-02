import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { fileURLToPath, URL } from 'node:url'

// base 由环境变量注入：GitHub Pages 上设 VITE_BASE=/bj-house-insight/
// 本地 / 后端托管时保持默认 '/'
const base = process.env.VITE_BASE || '/'

export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 按需引入：只打包模板里真正用到的组件与其样式，
    // 相比全量引入（约 1.0 MB JS + 365 KB CSS）可省下约 70% 体积
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] })
  ],
  base,
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  server: {
    port: 5173,
    proxy: {
      // 开发期把 /api 代理到后端，避免跨域；生产期同源
      '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true }
    }
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers']
        }
      }
    }
  }
})
