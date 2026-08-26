import { getApiBase } from '@/config.js'

let refreshTask = null
let redirecting = false

function raw({ url, method = 'GET', data, token, timeout = 60000 }) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${getApiBase()}/api${url}`,
      method,
      data,
      timeout,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: resolve,
      fail: reject,
    })
  })
}

function clearSession() {
  uni.removeStorageSync('access_token')
  uni.removeStorageSync('refresh_token')
  uni.removeStorageSync('user')
}

function toLogin() {
  if (redirecting) return
  redirecting = true
  clearSession()
  uni.reLaunch({ url: '/pages/login/index' })
  setTimeout(() => { redirecting = false }, 1200)
}

function refreshToken() {
  if (refreshTask) return refreshTask
  const refresh = uni.getStorageSync('refresh_token')
  if (!refresh) return Promise.reject(new Error('missing refresh token'))
  refreshTask = raw({ url: '/auth/refresh/', method: 'POST', data: { refresh } })
    .then((response) => {
      const access = response.data?.access || response.data?.data?.access
      if (!access) throw new Error('refresh failed')
      uni.setStorageSync('access_token', access)
      return access
    })
    .finally(() => { refreshTask = null })
  return refreshTask
}

function messageFrom(body, fallback = '请求失败') {
  if (!body) return fallback
  if (typeof body.message === 'string' && body.message) return body.message
  const data = body.data || body
  if (typeof data === 'string') return data
  if (data && typeof data === 'object') {
    const first = Object.values(data)[0]
    if (Array.isArray(first)) return String(first[0])
    if (first) return String(first)
  }
  return fallback
}

function unwrap(response) {
  const body = response.data
  if (response.statusCode >= 200 && response.statusCode < 300) {
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body.data
      throw new Error(messageFrom(body))
    }
    return body
  }
  throw new Error(messageFrom(body, `请求失败（${response.statusCode}）`))
}

export async function request(options) {
  const token = uni.getStorageSync('access_token')
  let response
  try {
    response = await raw({ ...options, token })
  } catch (error) {
    uni.showToast({ title: '网络连接失败', icon: 'none' })
    throw error
  }

  if (response.statusCode === 401 && token) {
    try {
      const access = await refreshToken()
      response = await raw({ ...options, token: access })
    } catch {
      toLogin()
      throw new Error('登录已过期')
    }
  }

  try {
    return unwrap(response)
  } catch (error) {
    uni.showToast({ title: error.message || '请求失败', icon: 'none', duration: 2400 })
    throw error
  }
}

export const get = (url, data) => request({ url, data })
export const post = (url, data, timeout) => request({ url, method: 'POST', data, timeout })
export const patch = (url, data) => request({ url, method: 'PATCH', data })
