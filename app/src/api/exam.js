import { get, post, put } from '@/utils/request.js'

// ===== 教师 =====
export const listExams = (params) => get('/exams/', params)
export const createExam = (data) => post('/exams/', data)
export const updateExam = (id, data) => put(`/exams/${id}/`, data)
export const composePaper = (id, data) => post(`/exams/${id}/compose/`, data)
export const monitorExam = (id) => get(`/exams/${id}/monitor/`)
export const releaseExamScores = (id) => post(`/exams/${id}/release-scores/`)
export const examGradingDetail = (subId) => get(`/exam-submissions/${subId}/grading-detail/`)
export const gradeExamSubmission = (subId, data) => post(`/exam-submissions/${subId}/grade/`, data)
export const releaseExamScore = (subId) => post(`/exam-submissions/${subId}/release/`)

// ===== 学生 =====
export const startExam = (exam) => post('/exam-submissions/start/', { exam })
export const submitExam = (subId, data) => post(`/exam-submissions/${subId}/submit/`, data)
export const reviewExam = (subId) => get(`/exam-submissions/${subId}/review/`)
export const reportCheat = (data) => post('/exam-logs/', data)
