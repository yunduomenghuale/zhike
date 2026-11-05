import request from './request'

// ===== 模板库 =====
export const listLabTemplates = (params) => request.get('/lab-templates/', { params })

// ===== 教师：实验管理 =====
export const listLabs = (params) => request.get('/labs/', { params })
export const createLab = (data) => request.post('/labs/', data)
export const updateLab = (id, data) => request.patch(`/labs/${id}/`, data)
export const deleteLab = (id) => request.delete(`/labs/${id}/`)
export const publishLab = (id) => request.post(`/labs/${id}/publish/`)
export const closeLab = (id) => request.post(`/labs/${id}/close/`)

// ===== 自定义实验：页面上传 / 预览 / 接入说明 / 在线调试（Stage 4）=====
// 上传命中静态扫描时后端返回 HTTP 400 + require_confirm，需由组件自行读取
// e.response.data 展示命中项并二次确认；故这里统一 silent，不让拦截器抢先弹提示。
export const uploadLabPage = (id, file, confirm = false) => {
  const form = new FormData()
  form.append('file', file)
  if (confirm) form.append('confirm', '1')
  return request.post(`/labs/${id}/page/`, form, { silent: true })
}
export const deleteLabPage = (id) => request.delete(`/labs/${id}/page/`)
export const previewLabPage = (id) => request.get(`/labs/${id}/page/preview/`)
export const getIntegrationSpec = (id) => request.get(`/labs/${id}/integration-spec/`)
export const gradeDebug = (id, data) => request.post(`/labs/${id}/grade-debug/`, data)

// ===== 排课 =====
export const listLabSchedules = (params) => request.get('/lab-schedules/', { params })
export const createLabSchedule = (data) => request.post('/lab-schedules/', data)
export const deleteLabSchedule = (id) => request.delete(`/lab-schedules/${id}/`)

// ===== 作答与成绩 =====
export const listLabSubmissions = (params) => request.get('/lab-submissions/', { params })
export const startLab = (lab) => request.post('/lab-submissions/start/', { lab })
export const bridgeValidate = (token) =>
  request.get('/lab-submissions/bridge-validate/', { params: { token } })
export const submitLab = (subId, data) => request.post(`/lab-submissions/${subId}/submit/`, data)
export const submitLabConclusion = (subId, conclusion) =>
  request.post(`/lab-submissions/${subId}/conclusion/`, { conclusion })
export const reviewLabSubmission = (subId, data) =>
  request.post(`/lab-submissions/${subId}/review/`, data)
export const resetLabSubmission = (subId) => request.post(`/lab-submissions/${subId}/reset/`)
export const getMyLabSchedule = (labId) => request.get(`/labs/${labId}/my-schedule/`)

// ===== 二期A：实验报告 =====
export const generateLabReport = (subId) =>
  request.post(`/lab-submissions/${subId}/generate-report/`)
export const downloadLabReportUrl = (subId, type = 'pdf') =>
  `/api/lab-submissions/${subId}/download-report/?type=${type}`
