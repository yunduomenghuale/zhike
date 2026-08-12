import request from './request'

export const listQuestions = (params) => request.get('/questions/', { params })
export const createQuestion = (data) => request.post('/questions/', data)
export const updateQuestion = (id, data) => request.patch(`/questions/${id}/`, data)
export const deleteQuestion = (id) => request.delete(`/questions/${id}/`)
export const generateQuestions = (data) => request.post('/questions/generate/', data)

// 章节练习提交（学生）
export const practiceSubmit = (data) => request.post('/questions/practice-submit/', data)

// 手动错题（学生错题本）
export const listWrongNotes = (params) => request.get('/wrong-notes/', { params })
export const createWrongNote = (data) => request.post('/wrong-notes/', data)
export const deleteWrongNote = (id) => request.delete(`/wrong-notes/${id}/`)

// 错题巩固状态（学生错题本）
export const listWrongMastery = (params) => request.get('/wrong-mastery/', { params })
export const toggleWrongMastery = (data) => request.post('/wrong-mastery/', data)
