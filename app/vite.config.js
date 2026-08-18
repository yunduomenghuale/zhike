import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'
// https://vitejs.dev/config/
export default defineConfig({
  // H5 产物部署在 nginx /m/ 子路径（与 manifest.json h5.router.base 一致）
  base: '/m/',
  plugins: [
    uni(),
  ],
  server: {
    // H5 开发环境把 /api、/media 代理到 Django 后端
    proxy: {
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
