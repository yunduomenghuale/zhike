import { fileURLToPath, URL } from 'node:url'
import path from 'node:path'
import fs from 'node:fs'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const kebab = (s) => s.replace(/\B([A-Z])/g, '-$1').toLowerCase()

// 启动时一次性扫描全部源码，预构建所有依赖。
// 背景：路由懒加载 + unplugin 按需注入 element-plus 组件样式，导致 vite 运行中
// 反复 "new dependencies optimized + full reload"，浏览新页面即白屏卡顿。
// 这里主动扫出：1) 所有裸包导入 2) 模板里用到的 el-* 组件样式子路径。
function scanDeps() {
  const deps = new Set()
  const elComponents = new Set(['base', 'config-provider']) // 基础样式必含
  const skip = new Set(['node_modules', 'dist', '.git'])
  const exts = ['.js', '.ts', '.vue', '.jsx', '.tsx', '.mjs']
  const addPkg = (spec) => {
    const seg = spec.split('/')
    deps.add(spec.startsWith('@') ? seg.slice(0, 2).join('/') : seg[0])
  }
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (skip.has(entry.name)) continue
      const p = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        walk(p)
        continue
      }
      if (!exts.some((e) => entry.name.endsWith(e))) continue
      const code = fs.readFileSync(p, 'utf-8')
      for (const m of code.matchAll(/(?:import|export)[^'"]*?from\s+['"]([^./'"][^'"]*)['"]/g)) {
        if (!m[1].startsWith('@/')) addPkg(m[1])
      }
      for (const m of code.matchAll(/import\(\s*['"]([^./'"][^'"]*)['"]\s*\)/g)) {
        if (!m[1].startsWith('@/')) addPkg(m[1])
      }
      for (const m of code.matchAll(/^\s*import\s+['"]([^./'"][^'"]*)['"]/gm)) {
        if (!m[1].startsWith('@/')) addPkg(m[1])
      }
      // 模板中的 el-xxx 组件（含 ElXxx 大写写法）
      for (const m of code.matchAll(/<el-([a-z][a-z0-9-]*)/g)) elComponents.add(m[1])
      for (const m of code.matchAll(/<(El[A-Z]\w*)/g)) elComponents.add(kebab(m[1].slice(2)))
    }
  }
  walk(path.resolve(__dirname, 'src'))
  for (const c of elComponents) deps.add(`element-plus/es/components/${c}/style/css`)
  return [...deps]
}

export default defineConfig({
  // 登录页的 three.js 背景已通过路由懒加载；其独立分包约 524 kB（gzip 约 133 kB）。
  build: {
    chunkSizeWarningLimit: 550,
  },
  // 启动即预构建全部依赖，杜绝浏览过程中反复 optimize+reload 造成的卡顿/白屏
  optimizeDeps: {
    include: scanDeps(),
  },
  plugins: [
    vue(),
    // Element Plus 组件与 API 按需自动导入
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
    // 开发期模拟生产 nginx 的 /resources/ 静态目录（课程思维导图/交互演示），
    // 生产环境由 nginx 直接挂载 deploy/resources，无需此插件。
    {
      name: 'dev-resources-static',
      configureServer(server) {
        server.middlewares.use('/resources', (req, res, next) => {
          const root = path.resolve(__dirname, '../deploy/resources')
          const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '')
          const fsPath = path.resolve(root, rel)
          if (!fsPath.startsWith(root)) {
            res.statusCode = 403
            return res.end('Forbidden')
          }
          if (!fs.existsSync(fsPath) || !fs.statSync(fsPath).isFile()) {
            res.statusCode = 404
            return res.end('Not Found: ' + rel)
          }
          res.setHeader('Content-Type', 'text/html; charset=utf-8')
          fs.createReadStream(fsPath).pipe(res)
        })
        // 虚拟实验静态页（含 lab-bridge.js）：生产由 nginx 挂载 deploy/labs，
        // 开发环境同样直读该目录，避免 SPA fallback 把实验页变成 404。
        server.middlewares.use('/labs', (req, res, next) => {
          const root = path.resolve(__dirname, '../deploy/labs')
          const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '')
          const fsPath = path.resolve(root, rel)
          if (!fsPath.startsWith(root)) {
            res.statusCode = 403
            return res.end('Forbidden')
          }
          if (!fs.existsSync(fsPath) || !fs.statSync(fsPath).isFile()) {
            res.statusCode = 404
            return res.end('Not Found: ' + rel)
          }
          const ext = path.extname(fsPath).toLowerCase()
          const type = ext === '.js' ? 'text/javascript; charset=utf-8'
            : ext === '.css' ? 'text/css; charset=utf-8'
            : ext === '.svg' ? 'image/svg+xml'
            : ext === '.png' ? 'image/png'
            : ext === '.jpg' || ext === '.jpeg' ? 'image/jpeg'
            : 'text/html; charset=utf-8'
          res.setHeader('Content-Type', type)
          fs.createReadStream(fsPath).pipe(res)
        })
      },
    },
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
