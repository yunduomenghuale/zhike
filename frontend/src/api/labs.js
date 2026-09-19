import request from './request'

// ===== 模板库 =====
export const listLabTemplates = (params) => request.get('/lab-templates/', { params })

// ===== 教师：实验管理 =====
export const listLabs = (params) => request.get('/labs/', { params })
export const createLab = (data) => request.post('/labs/', data)
export const updateLab = (id, data) => request.patch(`/labs/${id}/`, data)
export const deleteLab = (id) => request.delete(`/labs/${id}/`)
export const addLabQuestions = (id, questionIds) =>
  request.post(`/labs/${id}/questions/`, { question_ids: questionIds })
export const clearLabQuestions = (id) => request.delete(`/labs/${id}/questions/`)
export const publishLab = (id) => request.post(`/labs/${id}/publish/`)
export const closeLab = (id) => request.post(`/labs/${id}/close/`)

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
export const gradeLabSubmission = (subId, data) =>
  request.post(`/lab-submissions/${subId}/grade/`, data)
export const getLabAnswers = (subId) => request.get(`/lab-submissions/${subId}/answers/`)
export const getMyLabSchedule = (labId) => request.get(`/labs/${labId}/my-schedule/`)

// ===== 二期A：实验报告 =====
export const generateLabReport = (subId) =>
  request.post(`/lab-submissions/${subId}/generate-report/`)
export const downloadLabReportUrl = (subId, type = 'pdf') =>
  `/api/lab-submissions/${subId}/download-report/?type=${type}`
