import request from './request'

export const getClassStats = (classId, params) => request.get(`/analytics/class/${classId}/`, { params })
export const getClassStudentDetail = (classId, studentId, params) =>
  request.get(`/analytics/class/${classId}/students/${studentId}/`, { params })
export const generateClassAiReport = (classId, params) =>
  request.post(`/analytics/class/${classId}/ai-report/`, null, { params })
export const getMyWrongQuestions = (params) =>
  request.get('/analytics/my-wrong-questions/', { params })
