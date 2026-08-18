import { BASE_URL } from '@/config.js'
import { get, post } from '@/utils/request.js'

export const listHomeworks = (params) => get('/homeworks/', params)
export const createHomework = (data) => post('/homeworks/', data)
export const listSubmissions = (params) => get('/homework-submissions/', params)
export const submitHomework = (data) => post('/homework-submissions/', data)

// 教师批改与成绩发布
export const gradeSubmission = (id, data) => post(`/homework-submissions/${id}/grade/`, data)
export const releaseSubmission = (id) => post(`/homework-submissions/${id}/release/`)
export const releaseAllSubmissions = (homeworkId) =>
  post('/homework-submissions/release-all/', { homework: homeworkId })

/**
 * 带附件的作业提交（multipart）。
 * uni.request 不支持文件上传，这里用 uni.uploadFile 并手工解包统一响应。
 */
export function submitHomeworkWithFile({ homework, content, filePath }) {
  const token = uni.getStorageSync('access_token')
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: `${BASE_URL}/api/homework-submissions/`,
      filePath,
      name: 'attachment',
      formData: { homework, content: content || '' },
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: (res) => {
        let body = res.data
        try { body = JSON.parse(res.data) } catch { /* 保留原文 */ }
        if (res.statusCode >= 200 && res.statusCode < 300 && body && body.code === 0) {
          return resolve(body.data)
        }
        uni.showToast({ title: body?.message || '提交失败', icon: 'none' })
        reject(body)
      },
      fail: (err) => {
        uni.showToast({ title: '网络错误，请稍后重试', icon: 'none' })
        reject(err)
      },
    })
  })
}
