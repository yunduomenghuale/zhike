import request from './request'

// ===== 教师 =====
export const listExams = (params) => request.get('/exams/', { params })
export const createExam = (data) => request.post('/exams/', data)
export const updateExam = (id, data) => request.put(`/exams/${id}/`, data)
export const deleteExam = (id) => request.delete(`/exams/${id}/`)
export const composePaper = (id, data) => request.post(`/exams/${id}/compose/`, data)
export const getExamPaper = (id) => request.get(`/exams/${id}/paper/`)
export const monitorExam = (id) => request.get(`/exams/${id}/monitor/`)
export const getExamStats = (id) => request.get(`/exams/${id}/stats/`)
export const releaseExamScores = (id) => request.post(`/exams/${id}/release-scores/`)
// 教师批改与发布
export const examGradingDetail = (subId) => request.get(`/exam-submissions/${subId}/grading-detail/`)
export const gradeExamSubmission = (subId, data) =>
  request.post(`/exam-submissions/${subId}/grade/`, data)
export const releaseExamScore = (subId) => request.post(`/exam-submissions/${subId}/release/`)

// ===== 学生 =====
export const startExam = (exam) => request.post('/exam-submissions/start/', { exam })
export const saveExamAnswers = (subId, data) =>
  request.post(`/exam-submissions/${subId}/save/`, data)
export const submitExam = (subId, data) =>
  request.post(`/exam-submissions/${subId}/submit/`, data)
export const reviewExam = (subId) => request.get(`/exam-submissions/${subId}/review/`)
export const listExamSubmissions = (params) => request.get('/exam-submissions/', { params })
export const reportCheat = (data) => request.post('/exam-logs/', data)
