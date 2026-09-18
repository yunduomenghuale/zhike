import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

export default defineConfig({
  // H5 产物部署在 nginx /m/ 子路径（与 manifest.json h5.router.base 一致）
  base: '/m/',
  plugins: [uni()],
})
