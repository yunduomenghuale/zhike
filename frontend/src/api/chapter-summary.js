import request from './request'

// 学生端章节学习 AI 总结（设计 §4.4）
// POST：{course_id, catalog_id, force?} → {task_id, cached}（幂等：已有成功/进行中记录直接复用）
// GET ?course_id=&catalog_id= → {summary}（本人最新成功版本，没有则 null）
export const submitChapterSummary = (data) =>
  request.post('/analytics/chapter-summaries/', data)

export const getChapterSummary = (params) =>
  request.get('/analytics/chapter-summaries/', { params })
