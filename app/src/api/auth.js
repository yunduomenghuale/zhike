import { BASE_URL } from '@/config.js'
import { get, post, patch } from '@/utils/request.js'

export const login = (data) => post('/auth/login/', data)
export const register = (data) => post('/auth/register/', data)
export const getMe = () => get('/auth/me/')
export const updateMe = (data) => patch('/auth/me/', data)
export const changePassword = (data) => post('/auth/password/', data)

/** 上传头像（multipart），返回 { avatar } */
export function uploadAvatar(filePath) {
  const token = uni.getStorageSync('access_token')
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: `${BASE_URL}/api/auth/avatar/`,
      filePath,
      name: 'avatar',
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: (res) => {
        let body = res.data
        try { body = JSON.parse(res.data) } catch { /* 保留原文 */ }
        if (res.statusCode >= 200 && res.statusCode < 300 && body && body.code === 0) {
          return resolve(body.data)
        }
        uni.showToast({ title: body?.message || '上传失败', icon: 'none' })
        reject(body)
      },
      fail: (err) => {
        uni.showToast({ title: '网络错误，请稍后重试', icon: 'none' })
        reject(err)
      },
    })
  })
}
