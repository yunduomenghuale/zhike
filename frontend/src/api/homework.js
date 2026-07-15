import request from './request'

export const listHomeworks = (params) => request.get('/homeworks/', { params })
export const createHomework = (data) => request.post('/homeworks/', data)
export const updateHomework = (id, data) => request.put(`/homeworks/${id}/`, data)
export const deleteHomework = (id) => request.delete(`/homeworks/${id}/`)

export const listSubmissions = (params) => request.get('/homework-submissions/', { params })
export const submitHomework = (data) => request.post('/homework-submissions/', data)
export const gradeSubmission = (id, data) =>
  request.post(`/homework-submissions/${id}/grade/`, data)
