import { BASE_URL } from '@/config.js'

// 防止并发 401 重复清理与重复跳转
let handling401 = false
// 刷新令牌单飞：并发 401 共享同一次刷新
let refreshPromise = null

function clearSession() {
  uni.removeStorageSync('access_token')
  uni.removeStorageSync('refresh_token')
  uni.removeStorageSync('user')
}

function toLogin() {
  if (handling401) return
  handling401 = true
  clearSession()
  uni.showToast({ title: '登录已过期，请重新登录', icon: 'none' })
  uni.reLaunch({ url: '/pages/login/index' })
  setTimeout(() => { handling401 = false }, 1500)
}

/**
 * 用 refresh_token 静默换新 access_token。
 * 后端 /auth/refresh/ 是 simplejwt 原生视图，直接返回 { access }（不包统一结构）。
 */
function refreshAccessToken() {
  const refresh = uni.getStorageSync('refresh_token')
  if (!refresh) return Promise.reject(new Error('no refresh token'))
  if (!refreshPromise) {
    refreshPromise = new Promise((resolve, reject) => {
      uni.request({
        url: `${BASE_URL}/api/auth/refresh/`,
        method: 'POST',
        data: { refresh },
        header: { 'Content-Type': 'application/json' },
        success: (res) => {
          const access = res.data?.access || res.data?.data?.access
          if (res.statusCode === 200 && access) {
            uni.setStorageSync('access_token', access)
            resolve(access)
          } else {
            reject(res.data)
          }
        },
        fail: reject,
      })
    }).finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

function rawRequest({ url, method = 'GET', data, header = {}, timeout = 60000, token }) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}/api${url}`,
      method,
      data,
      timeout,
      header: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...header,
      },
      success: resolve,
      fail: reject,
    })
  })
}

function unwrap(res) {
  const body = res.data
  if (body && typeof body === 'object' && 'code' in body) {
    if (body.code === 0) return body.data
    uni.showToast({ title: body.message || '请求失败', icon: 'none' })
    throw body
  }
  return body
}

/**
 * 统一请求封装：对齐 web 端 axios 拦截器行为。
 * - 自动附带 JWT
 * - 401 时先用 refresh_token 静默换新并重试一次，失败才踢回登录页
 * - 解包统一结构 { code, message, data }，code 非 0 弹 toast 并 reject
 */
export async function request({ url, method = 'GET', data, header = {}, timeout = 60000 }) {
  const token = uni.getStorageSync('access_token')
  let res
  try {
    res = await rawRequest({ url, method, data, header, timeout, token })
  } catch (err) {
    uni.showToast({ title: '网络错误，请稍后重试', icon: 'none' })
    throw err
  }

  if (res.statusCode === 401 && token) {
    // access 过期：尝试静默刷新并重放原请求
    try {
      const newToken = await refreshAccessToken()
      res = await rawRequest({ url, method, data, header, timeout, token: newToken })
    } catch {
      toLogin()
      throw res
    }
    if (res.statusCode === 401) {
      toLogin()
      throw res
    }
  }

  return unwrap(res)
}

export const get = (url, data) => request({ url, data })
export const post = (url, data) => request({ url, method: 'POST', data })
export const put = (url, data) => request({ url, method: 'PUT', data })
export const patch = (url, data) => request({ url, method: 'PATCH', data })
export const del = (url) => request({ url, method: 'DELETE' })
