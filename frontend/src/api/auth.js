import request from './request'

export const login = (data) => request.post('/auth/login/', data)
// 登出（P5-A2）：吊销 refresh 并推进 access 作废线；请求可能因 token 已失效而失败，调用方须自行吞错。
// access 由调用方显式传入：登出会先清 localStorage，而 axios 请求拦截器在微任务里才执行，
// 那时已经读不到 token，只能靠这里显式带上 Authorization（否则后端 401「身份认证信息未提供」）。
// silent: 该请求的失败不弹提示、不触发续期/跳登录页。
export const logout = (refresh, access) =>
  request.post(
    '/auth/logout/',
    refresh ? { refresh } : {},
    {
      silent: true,
      headers: access ? { Authorization: `Bearer ${access}` } : {},
    },
  )
export const register = (data) => request.post('/auth/register/', data)
// 登录页公开配置（AllowAny）：注册通道开关（register_open=false 时隐藏注册入口）
export const getAuthConfig = () => request.get('/auth/config/')
export const getMe = () => request.get('/auth/me/')
export const updateMe = (data) => request.patch('/auth/me/', data)
export const changePassword = (data) => request.post('/auth/password/', data)

export const uploadAvatar = (file) => {
  const data = new FormData()
  data.append('avatar', file)
  return request.post('/auth/avatar/', data)
}
