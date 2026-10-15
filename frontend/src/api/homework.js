import request from './request'

export const listHomeworks = (params) => request.get('/homeworks/', { params })
export const createHomework = (data) => request.post('/homeworks/', data)
export const updateHomework = (id, data) => request.patch(`/homeworks/${id}/`, data)
export const deleteHomework = (id) => request.delete(`/homeworks/${id}/`)
// 教师附件即传：上传走视图内 XHR（需要真实进度条）；移除按 url 删除单个附件
export const removeHomeworkAttachment = (id, url) =>
  request.delete(`/homeworks/${id}/attachments/`, { data: { url } })
// PDF 附件预览：后端逐页渲染为图片，前端无工具栏连续滚动
export const previewHomeworkAttachment = (id, url) =>
  request.get(`/homeworks/${id}/attachments/preview/`, { params: { url } })

export const listSubmissions = (params) => request.get('/homework-submissions/', { params })
export const submitHomework = (data) => request.post('/homework-submissions/', data)
// 学生提交前暂存附件：上传走视图内 XHR（需要真实进度条），提交时以 uploaded 字段引用
export const gradeSubmission = (id, data) =>
  request.post(`/homework-submissions/${id}/grade/`, data)
export const releaseSubmission = (id) =>
  request.post(`/homework-submissions/${id}/release/`)
export const releaseAllSubmissions = (homeworkId) =>
  request.post('/homework-submissions/release-all/', { homework: homeworkId })
