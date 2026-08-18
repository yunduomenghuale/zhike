/**
 * 全局配置。
 * H5 开发环境走 Vite 代理（baseURL 为空串）；微信小程序 / App 需要完整后端地址。
 *
 * 环境切换：
 * - 本地后端联调：把 DEV_BASE 改成电脑的局域网 IP，例如 http://192.168.1.10:8005
 *   （127.0.0.1 在真机/小程序里指向设备自身，无法访问电脑上的后端）
 * - 生产环境：确认 PROD_BASE 指向线上 nginx（对外 8088，/api 反代到后端）
 */
const DEV_BASE = 'http://127.0.0.1:8005'
const PROD_BASE = 'http://124.70.107.64:8088'

// 打包发布时改为 true（或用 process.env.NODE_ENV === 'production'）
const USE_PROD = false

let baseURL = ''

// #ifndef H5
baseURL = USE_PROD ? PROD_BASE : DEV_BASE
// #endif

// H5 生产构建若与后端不同源，也需要完整地址
// #ifdef H5
if (typeof process !== 'undefined' && process.env?.NODE_ENV === 'production' && USE_PROD) {
  baseURL = PROD_BASE
}
// #endif

export const BASE_URL = baseURL

export const apiURL = (path) => `${BASE_URL}/api${path}`

/** 后端返回的 /media/... 相对路径转可访问地址 */
export const mediaURL = (path) => {
  if (!path) return ''
  if (/^https?:\/\//.test(path)) return path
  return `${BASE_URL}${path}`
}
