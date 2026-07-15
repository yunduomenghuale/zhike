import request from './request'

export const getClassStats = (classId, params) => request.get(`/analytics/class/${classId}/`, { params })
export const getMyWrongQuestions = (params) =>
  request.get('/analytics/my-wrong-questions/', { params })
