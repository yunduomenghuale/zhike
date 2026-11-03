import { get, post } from '@/utils/request.js'

// 我的错题（自动收录：练习/作业/考试中的错题）
export const getMyWrongQuestions = (params) => get('/analytics/my-wrong-questions/', params)

// 教师：班级学习统计 / 学生明细 / AI 班级报告
export const getClassStats = (classId, params) => get(`/analytics/class/${classId}/`, params)
export const getClassStudentDetail = (classId, studentId, params) =>
  get(`/analytics/class/${classId}/students/${studentId}/`, params)
export const generateClassAiReport = (classId, courseId) =>
  post(`/analytics/class/${classId}/ai-report/${courseId ? `?course=${courseId}` : ''}`)
