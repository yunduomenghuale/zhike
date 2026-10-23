import request from './request'

// 异步 AI 任务轮询（班级学情分析 / 章节学习总结 / AI 生题共用）
export const getAiTask = (taskId) => request.get(`/ai-tasks/${taskId}/`)
// 进行中任务列表（「离开页面不丢失」的恢复入口；默认只 question_gen，task_type=all 查全部）
export const listActiveAiTasks = (params) => request.get('/ai-tasks/active/', { params })
