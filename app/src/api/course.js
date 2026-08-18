import { get, post, put, patch, del } from '@/utils/request.js'

// 课程
export const listCourses = (params) => get('/courses/', params)
export const createCourse = (data) => post('/courses/', data)
export const updateCourse = (id, data) => put(`/courses/${id}/`, data)
export const deleteCourse = (id) => del(`/courses/${id}/`)

// 课程目录（章节）
export const listCatalogs = (params) => get('/catalogs/', params)
export const createCatalog = (data) => post('/catalogs/', data)
export const updateCatalog = (id, data) => patch(`/catalogs/${id}/`, data)
export const deleteCatalog = (id) => del(`/catalogs/${id}/`)

// 课件 / 视频
export const listPpts = (params) => get('/ppts/', params)
export const listVideos = (params) => get('/videos/', params)

// 视频学习进度
export const listWatchProgress = (params) => get('/watch-progress/', params)
export const reportVideoProgress = (videoId, data) =>
  post(`/videos/${videoId}/report-progress/`, data)
