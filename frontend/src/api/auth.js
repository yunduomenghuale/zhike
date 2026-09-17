import request from './request'

export const login = (data) => request.post('/auth/login/', data)
export const register = (data) => request.post('/auth/register/', data)
export const getMe = () => request.get('/auth/me/')
export const updateMe = (data) => request.patch('/auth/me/', data)
export const changePassword = (data) => request.post('/auth/password/', data)

export const uploadAvatar = (file) => {
  const data = new FormData()
  data.append('avatar', file)
  return request.post('/auth/avatar/', data)
}
