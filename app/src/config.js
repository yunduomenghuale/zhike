// 真机安装包默认连接线上服务器；调试局域网后端时可在设置中覆盖 api_base_url。
export const DEFAULT_API_BASE = 'http://39.105.44.181:8005'

export function getApiBase() {
  return String(uni.getStorageSync('api_base_url') || DEFAULT_API_BASE).replace(/\/$/, '')
}

export function mediaUrl(path) {
  if (!path) return ''
  if (/^https?:\/\//i.test(path)) return path
  return `${getApiBase()}${path.startsWith('/') ? '' : '/'}${path}`
}
