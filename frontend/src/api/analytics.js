import axios from 'axios'

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

// 班级学习数据 Excel 导出：二进制下载不走统一响应解包（独立 axios + 手动带 token），
// 文件名取自 Content-Disposition（RFC 5987）。出错时后端 JSON 错误体也是 blob，由调用方解析。
export async function downloadClassExport(classId, params) {
  const { data, headers } = await axios.get(`/api/analytics/class/${classId}/export/`, {
    params,
    responseType: 'blob',
    headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
  })
  const dispo = headers['content-disposition'] || ''
  const m = dispo.match(/filename\*=UTF-8''([^;]+)/)
  const filename = m ? decodeURIComponent(m[1]) : `学习数据导出_${Date.now()}.xlsx`
  const blob = data instanceof Blob ? data : new Blob([data])
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
