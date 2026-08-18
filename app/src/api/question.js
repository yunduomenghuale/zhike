import { get, post, del, patch } from '@/utils/request.js'

export const listQuestions = (params) => get('/questions/', params)
export const createQuestion = (data) => post('/questions/', data)
export const updateQuestion = (id, data) => patch(`/questions/${id}/`, data)
export const deleteQuestion = (id) => del(`/questions/${id}/`)

// 章节练习提交（学生）：{ answers: { questionId: answerObj } }
export const practiceSubmit = (data) => post('/questions/practice-submit/', data)

// 手动错题（学生错题本）
export const listWrongNotes = (params) => get('/wrong-notes/', params)
export const createWrongNote = (data) => post('/wrong-notes/', data)
export const deleteWrongNote = (id) => del(`/wrong-notes/${id}/`)

// 错题巩固/移除标记
export const listWrongMastery = (params) => get('/wrong-mastery/', params)
export const toggleWrongMastery = (data) => post('/wrong-mastery/', data)
