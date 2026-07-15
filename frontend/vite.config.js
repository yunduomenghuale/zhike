import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 组件与 API 按需自动导入
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5273,
    strictPort: true, // 端口被占用时直接报错，不自动改端口
    proxy: {
      // 开发环境把 /api 代理到 Django 后端
      '/api': {
        target: 'http://127.0.0.1:8005',
        changeOrigin: true,
      },
      '/media': {
        target: 'http://127.0.0.1:8005',
        changeOrigin: true,
      },
    },
  },
})
