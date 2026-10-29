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

// 整班毕业（P4 流转，管理员专属）
// preview 不写库：返回将毕业名单 + 被排除的转班生 + 在途考试/未截止作业清单
export const graduatePreview = (id) => request.get(`/classes/${id}/graduate-preview/`)
// 执行毕业：有在途考试/未截止作业时后端 409，带 force=true 才放行（X-14）
export const graduateClass = (id, data) => request.post(`/classes/${id}/graduate/`, data)
// 撤销整班毕业：只回滚本批标记的学生（个别提前毕业者不受影响）
export const revokeGraduation = (id, data) => request.post(`/classes/${id}/graduate-revoke/`, data)
// 个别学籍变更（休学/复学/毕业/退学），与整班毕业互补
export const changeEduStatus = (id, data) => request.post(`/classes/${id}/edu-status/`, data)
