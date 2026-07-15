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
export const uploadPpt = ({ course, catalog, file }) => {
  const form = new FormData()
  form.append('course', course)
  form.append('catalog', catalog)
  form.append('file', file)
  form.append('file_name', file.name)
  return request.post('/ppts/', form, { headers: { 'Content-Type': 'multipart/form-data' } })
}
export const deletePpt = (id) => request.delete(`/ppts/${id}/`)

// 教学视频 / 讲解稿
export const listVideos = (params) => request.get('/videos/', { params })
export const generateScript = (catalogId, data = {}) =>
  request.post(`/catalogs/${catalogId}/generate-script/`, data, { timeout: 180000 })
export const generateAudio = (catalogId) =>
  request.post(`/catalogs/${catalogId}/generate-audio/`, {}, { timeout: 300000 })
export const updateVideoScript = (videoId, data) =>
  request.post(`/videos/${videoId}/update-script/`, data)
export const regenerateVideoScriptPage = (videoId, data) =>
  request.post(`/videos/${videoId}/regenerate-script-page/`, data, { timeout: 180000 })
