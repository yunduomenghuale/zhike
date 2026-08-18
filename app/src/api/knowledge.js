import { get, request } from '@/utils/request.js'

export const listQaRecords = (params) => get('/qa-records/', params)

// AI 回答生成较慢（检索 + 大模型），超时放宽到 120 秒
export const askQuestion = (data) =>
  request({ url: '/qa-records/ask/', method: 'POST', data, timeout: 120000 })
