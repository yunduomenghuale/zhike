import request from './request'

// 异步 AI 任务轮询（班级学情分析 / 章节学习总结共用）
export const getAiTask = (taskId) => request.get(`/ai-tasks/${taskId}/`)
