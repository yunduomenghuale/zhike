import request from './request'

export const listClasses = (params) => request.get('/classes/', { params })
// 单班详情：班级多到翻页时，靠列表里「找一下」会漏（只加载了当前页）
export const getClass = (id) => request.get(`/classes/${id}/`)
export const createClass = (data) => request.post('/classes/', data)
export const updateClass = (id, data) => request.put(`/classes/${id}/`, data)
// 局部更新：教师选班只提交 courses（PUT 会因缺必填字段 400，且带全量字段会被
// 后端的组织字段校验挡下）
export const patchClass = (id, data) => request.patch(`/classes/${id}/`, data)
export const deleteClass = (id) => request.delete(`/classes/${id}/`)
// 邀请码入班已于 P1 下线（/classes/join/ 返回 410），前端不再调用

// 班级学生
export const listClassStudents = (params) => request.get('/class-students/', { params })
export const removeClassStudent = (id) => request.delete(`/class-students/${id}/`)
export const searchClassStudents = (id, keyword) => request.get(`/classes/${id}/search-students/`, { params: { keyword } })
export const addStudentsBatch = (id, usernames) => request.post(`/classes/${id}/add-students-batch/`, { usernames })
