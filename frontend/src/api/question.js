import request from './request'

export const listQuestions = (params) => request.get('/questions/', { params })
export const createQuestion = (data) => request.post('/questions/', data)
export const updateQuestion = (id, data) => request.patch(`/questions/${id}/`, data)
export const deleteQuestion = (id) => request.delete(`/questions/${id}/`)
export const generateQuestions = (data) => request.post('/questions/generate/', data)

// 章节练习提交（学生）
export const practiceSubmit = (data) => request.post('/questions/practice-submit/', data)
