import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

const request = axios.create({
  baseURL: '/api',
  timeout: 180000,
})

// 记录已经处理过的失效令牌，避免多个并发请求重复提示、重复跳转。
let handledUnauthorizedToken = ''

// 请求拦截：附带 JWT
request.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
    if (token !== handledUnauthorizedToken) handledUnauthorizedToken = ''
  }
  return config
})

// 响应拦截：解包统一结构 { code, message, data }，集中处理错误
request.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body.data
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(body)
    }
    return body
  },
  (error) => {
    const status = error.response?.status
    const msg = error.response?.data?.message || error.message
    if (status === 401) {
      const authorization = error.config?.headers?.Authorization
      const requestToken = typeof authorization === 'string'
        ? authorization.replace(/^Bearer\s+/i, '')
        : ''

      // 只有携带访问令牌的请求才代表会话过期。登录失败同样会返回 401，
      // 此时应展示后端返回的账号/密码错误信息，而不是“登录已过期”。
      if (requestToken) {
        const currentToken = localStorage.getItem('access_token')
        // 用户重新登录后，旧请求迟到的 401 不能清除或打断新会话。
        if (currentToken && currentToken !== requestToken) {
          return Promise.reject(error)
        }
        if (requestToken !== handledUnauthorizedToken) {
          handledUnauthorizedToken = requestToken
          if (currentToken === requestToken) {
            localStorage.removeItem('access_token')
            localStorage.removeItem('refresh_token')
          }

          const currentRoute = router.currentRoute.value
          if (currentRoute.path !== '/login') {
            router.replace({
              path: '/login',
              query: { redirect: currentRoute.fullPath },
            })
          }
          ElMessage.error('登录已过期，请重新登录')
        }
      } else {
        ElMessage.error(msg || '请求失败')
      }
    } else {
      ElMessage.error(msg || '网络错误')
    }
    return Promise.reject(error)
  },
)

export default request
