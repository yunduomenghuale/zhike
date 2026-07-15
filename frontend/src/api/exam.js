import request from './request'

// ===== 教师 =====
export const listExams = (params) => request.get('/exams/', { params })
export const createExam = (data) => request.post('/exams/', data)
export const updateExam = (id, data) => request.put(`/exams/${id}/`, data)
export const deleteExam = (id) => request.delete(`/exams/${id}/`)
export const composePaper = (id, data) => request.post(`/exams/${id}/compose/`, data)
export const monitorExam = (id) => request.get(`/exams/${id}/monitor/`)

// ===== 学生 =====
export const startExam = (exam) => request.post('/exam-submissions/start/', { exam })
export const submitExam = (subId, data) =>
  request.post(`/exam-submissions/${subId}/submit/`, data)
export const reviewExam = (subId) => request.get(`/exam-submissions/${subId}/review/`)
export const reportCheat = (data) => request.post('/exam-logs/', data)
