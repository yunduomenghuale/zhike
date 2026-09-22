import request from './request'

export const listClasses = (params) => request.get('/classes/', { params })
export const createClass = (data) => request.post('/classes/', data)
export const updateClass = (id, data) => request.put(`/classes/${id}/`, data)
export const deleteClass = (id) => request.delete(`/classes/${id}/`)
export const joinClass = (invite_code) => request.post('/classes/join/', { invite_code })
export const regenerateCode = (id) => request.post(`/classes/${id}/regenerate-code/`)
export const addStudent = (id, username) => request.post(`/classes/${id}/add-student/`, { username })

// 班级学生
export const listClassStudents = (params) => request.get('/class-students/', { params })
export const removeClassStudent = (id) => request.delete(`/class-students/${id}/`)
export const searchClassStudents = (id, keyword) => request.get(`/classes/${id}/search-students/`, { params: { keyword } })
export const addStudentsBatch = (id, usernames) => request.post(`/classes/${id}/add-students-batch/`, { usernames })
