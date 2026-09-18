import request from './request'

export const getAdminOverview = () => request.get('/admin-panel/overview/')

export const listAdminUsers = (params) => request.get('/admin-panel/users/', { params })
export const createAdminUser = (data) => request.post('/admin-panel/users/', data)
export const updateAdminUser = (id, data) => request.patch(`/admin-panel/users/${id}/`, data)
export const resetAdminUserPassword = (id, data) => (
  request.post(`/admin-panel/users/${id}/reset-password/`, data)
)

// 学生批量导入：模板下载（blob）、上传解析预览、确认导入
export const downloadAdminUserImportTemplate = () => (
  request.get('/admin-panel/users/import-template/', { responseType: 'blob' })
)
export const previewAdminUserImport = (file) => {
  const data = new FormData()
  data.append('file', file)
  return request.post('/admin-panel/users/import-preview/', data)
}
export const confirmAdminUserImport = (rows) => (
  request.post('/admin-panel/users/import-confirm/', { rows })
)

export const listAdminCourses = (params) => request.get('/admin-panel/courses/', { params })
export const updateAdminCourseStatus = (id, status) => (
  request.patch(`/admin-panel/courses/${id}/status/`, { status })
)

export const listAdminClasses = (params) => request.get('/admin-panel/classes/', { params })

export const getAdminAIConfiguration = () => request.get('/admin-panel/ai-configuration/')
export const saveAdminAIConfiguration = (data) => request.put('/admin-panel/ai-configuration/', data)
export const testAdminAIConnection = () => request.post('/admin-panel/ai-configuration/test/')
