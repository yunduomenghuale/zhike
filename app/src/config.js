// 真机安装包默认连接线上服务器；调试局域网后端时可在设置中覆盖 api_base_url。
export const DEFAULT_API_BASE = 'http://39.105.44.181:8005'
export const DEFAULT_MEDIA_BASE = 'http://39.105.44.181:5273'

export function getApiBase() {
  return String(uni.getStorageSync('api_base_url') || DEFAULT_API_BASE).replace(/\/$/, '')
}

export function getMediaBase() {
  const customMediaBase = uni.getStorageSync('media_base_url')
  if (customMediaBase) return String(customMediaBase).replace(/\/$/, '')
  const apiBase = getApiBase()
  // 线上 8005 只提供 API，媒体文件由 5273 的 Nginx 暴露；
  // 自定义局域网后端则继续默认使用同源媒体地址。
  return apiBase === DEFAULT_API_BASE ? DEFAULT_MEDIA_BASE : apiBase
}

export function mediaUrl(path) {
  if (!path) return ''
  if (/^https?:\/\//i.test(path)) return path
  return `${getMediaBase()}${path.startsWith('/') ? '' : '/'}${path}`
}
