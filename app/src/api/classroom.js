import { get, post, put, patch, del } from '@/utils/request.js'

export const listClasses = (params) => get('/classes/', params)
export const createClass = (data) => post('/classes/', data)
export const updateClass = (id, data) => put(`/classes/${id}/`, data)
export const patchClass = (id, data) => patch(`/classes/${id}/`, data)
export const deleteClass = (id) => del(`/classes/${id}/`)
export const joinClass = (inviteCode) => post('/classes/join/', { invite_code: inviteCode })
export const regenerateCode = (id) => post(`/classes/${id}/regenerate-code/`)
export const addStudent = (id, username) => post(`/classes/${id}/add-student/`, { username })

// 班级学生
export const listClassStudents = (params) => get('/class-students/', params)
export const removeClassStudent = (id) => del(`/class-students/${id}/`)
