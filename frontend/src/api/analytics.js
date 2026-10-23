import request from './request'

export const getClassStats = (classId, params) => request.get(`/analytics/class/${classId}/`, { params })
export const getClassStudentDetail = (classId, studentId, params) =>
  request.get(`/analytics/class/${classId}/students/${studentId}/`, { params })
export const generateClassAiReport = (classId, params) =>
  request.post(`/analytics/class/${classId}/ai-report/`, null, { params })
// P3：班级 AI 报告历史（按 AITask 查）+ 教师端查看班级学生章节总结
export const getClassAiReportHistory = (classId) =>
  request.get(`/analytics/class/${classId}/ai-reports/`)
export const getClassChapterSummaries = (classId, params) =>
  request.get(`/analytics/class/${classId}/chapter-summaries/`, { params })
export const getMyWrongQuestions = (params) =>
  request.get('/analytics/my-wrong-questions/', { params })
