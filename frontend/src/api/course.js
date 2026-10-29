import request from './request'

export const listCourses = (params) => request.get('/courses/', { params })
export const listCatalogs = (params) => request.get('/catalogs/', { params })
export const createCourse = (data) => request.post('/courses/', data)
export const updateCourse = (id, data) => request.put(`/courses/${id}/`, data)
export const deleteCourse = (id) => request.delete(`/courses/${id}/`)

// 课程目录（章节）
export const createCatalog = (data) => request.post('/catalogs/', data)
export const updateCatalog = (id, data) => request.patch(`/catalogs/${id}/`, data)
export const deleteCatalog = (id) => request.delete(`/catalogs/${id}/`)

// 授课计划 -> AI 识别目录
export const generateCatalog = (data) =>
  request.post('/catalogs/generate-from-plan/', data)

export const previewCatalogFromFile = (file) => {
  const form = new FormData()
  form.append('file', file)
  return request.post('/catalogs/preview-from-file/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// 章节 PPT 课件
export const listPpts = (params) => request.get('/ppts/', { params })
export const uploadPpt = ({ course, catalog, file, onUploadProgress }) => {
  const form = new FormData()
  form.append('course', course)
  form.append('catalog', catalog)
  form.append('file', file)
  form.append('file_name', file.name)
  return request.post('/ppts/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress,
  })
}
export const deletePpt = (id) => request.delete(`/ppts/${id}/`)

// 教学视频 / 讲解稿
export const listVideos = (params) => request.get('/videos/', { params })
// 分批生成讲解稿：每批最多 limit 页（后端默认 6），前端循环调用直至 done=true
// 超时 5 分钟：本地模型（vLLM/Ollama）推理慢，需大于后端 AI_SCRIPT_TIMEOUT×重试次数
export const generateScript = (catalogId, data = {}) =>
  request.post(`/catalogs/${catalogId}/generate-script/`, data, { timeout: 300000 })
// 分段配音：每批最多 limit 页（后端默认 3），前端循环调用直至 done=true
// 超时 5 分钟：本地 TTS（尤其 CPU 推理）合成慢，需大于后端 AI_TTS_TIMEOUT
export const generateAudio = (catalogId, limit = 3) =>
  request.post(`/catalogs/${catalogId}/generate-audio/`, { limit }, { timeout: 300000 })
export const updateVideoScript = (videoId, data) =>
  request.post(`/videos/${videoId}/update-script/`, data)
export const regenerateVideoScriptPage = (videoId, data) =>
  request.post(`/videos/${videoId}/regenerate-script-page/`, data, { timeout: 300000 })
// 单页重新合成配音（讲稿不变）
export const regenerateVideoAudioPage = (videoId, data) =>
  request.post(`/videos/${videoId}/regenerate-audio-page/`, data, { timeout: 300000 })

// 视频学习进度（PPT+配音连播）
export const listWatchProgress = (params) => request.get('/watch-progress/', { params })
export const reportVideoProgress = (videoId, data) =>
  request.post(`/videos/${videoId}/report-progress/`, data)

// ===== 课程教学资源（思维导图/交互演示/文档，直接归属课程，不挂章节） =====
export const listCourseResources = (params) => request.get('/course-resources/', { params })
// 预置类走 JSON；文档/自定义 HTML 类走 multipart（file 上传）
export const createCourseResource = (data) => request.post('/course-resources/', data)
export const uploadCourseResourceFile = ({ course, kind, title, file, onProgress }) => {
  const form = new FormData()
  form.append('course', course)
  form.append('kind', kind)
  form.append('title', title)
  form.append('file', file)
  return request.post('/course-resources/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress,
  })
}
export const uploadCourseDocument = ({ course, title, file, onProgress }) =>
  uploadCourseResourceFile({ course, kind: 'document', title, file, onProgress })
export const deleteCourseResource = (id) => request.delete(`/course-resources/${id}/`)
export const publishCourseResource = (id) => request.post(`/course-resources/${id}/publish/`)
export const unpublishCourseResource = (id) => request.post(`/course-resources/${id}/unpublish/`)
// 签发资源访问 URL（2 小时有效；学生仅限已发布资源，教师可预览本人未发布资源）
export const signCourseResource = (id) => request.post(`/course-resources/${id}/sign/`)
// 教师添加资源前预览平台预置页（按路径签发）
export const signPresetPage = (path) => request.post('/course-resources/preset-sign/', { path })
