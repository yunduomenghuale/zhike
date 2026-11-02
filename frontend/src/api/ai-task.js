import request from './request'

// 异步 AI 任务轮询（班级学情分析 / 章节学习总结 / AI 生题/讲稿/配音/课件解析共用）
export const getAiTask = (taskId) => request.get(`/ai-tasks/${taskId}/`)
// 进行中任务列表（任务中心恢复入口；默认只 question_gen，task_type=all 查全部）
export const listActiveAiTasks = (params) => request.get('/ai-tasks/active/', { params })
// 取消：pending 立即取消；running 在批次边界退出（§6）
export const cancelAiTask = (taskId) => request.post(`/ai-tasks/${taskId}/cancel/`)
// 重试：仅 failed/cancelled，复用同一行 attempts 归零（§7.2）
export const retryAiTask = (taskId) => request.post(`/ai-tasks/${taskId}/retry/`)
