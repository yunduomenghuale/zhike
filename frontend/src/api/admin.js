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

// 大模型配置（按能力：chat / embed / tts 分别配置与测试）
export const getAdminAIConfiguration = () => request.get('/admin-panel/ai-configuration/')
export const saveAdminAIConfiguration = (capabilities) => (
  request.put('/admin-panel/ai-configuration/', { capabilities })
)
// 测试连接：overrides 传当前表单值（provider/base_url/model_name/api_key，Key 留空沿用已生效配置）
// timeout 600s：系统内置模型（local）首次测试可能触发权重下载（BGE-M3 约 2.3GB）
export const testAdminAIConnection = (capability, overrides = {}) => (
  request.post('/admin-panel/ai-configuration/test/', { capability, ...overrides }, { timeout: 600000 })
)

// AI 调用统计与追溯（流水 / 汇总 / 导出 / 配置变更记录）
export const listAdminAICallLogs = (params) => request.get('/admin-panel/ai-call-logs/', { params })
// CSV 导出走后端限流上限 5 万条；blob 下载（文件名由后端 Content-Disposition 决定）
export const exportAdminAICallLogs = (params) => (
  request.get('/admin-panel/ai-call-logs/export/', { params, responseType: 'blob' })
)
export const getAdminAICallStats = (params) => request.get('/admin-panel/ai-call-stats/', { params })
// 问答质量看板（为空率/改写率/好评率/兜底率/降级/来源/课程排行/告警）
export const getAdminQAQualityStats = (params) => (
  request.get('/admin-panel/qa-quality-stats/', { params })
)
// 已废弃：审计双轨合并（2026-10-19）后配置变更记录读操作审计单轨
// （listAdminActionLogs + action=ai_config_save）；此端点仅查合并前存量，勿在新代码使用
export const listAdminAIConfigChanges = (params) => (
  request.get('/admin-panel/ai-config-changes/', { params })
)

// ---- 督管增强（2026-10-19）：趋势/异常/三维监管/操作审计 ----
export const getAdminTrends = (params) => (
  request.get('/admin-panel/overview/trends/', { params })
)
export const getAdminAlerts = () => request.get('/admin-panel/overview/alerts/')

export const getAdminCourseDetail = (id) => (
  request.get(`/admin-panel/courses/${id}/detail/`)
)
export const getAdminClassDetail = (id, params) => (
  request.get(`/admin-panel/classes/${id}/detail/`, { params })
)
export const updateAdminClassStatus = (id, status) => (
  request.patch(`/admin-panel/classes/${id}/status/`, { status })
)

export const listAdminTeachers = (params) => request.get('/admin-panel/teachers/', { params })
export const getAdminTeacherDetail = (id) => (
  request.get(`/admin-panel/teachers/${id}/detail/`)
)

// CSV 导出：课程/班级/教师上限 5000 行、审计 5 万行；blob 下载
export const exportAdminCourses = (params) => (
  request.get('/admin-panel/courses/export/', { params, responseType: 'blob' })
)
export const exportAdminClasses = (params) => (
  request.get('/admin-panel/classes/export/', { params, responseType: 'blob' })
)
export const exportAdminTeachers = (params) => (
  request.get('/admin-panel/teachers/export/', { params, responseType: 'blob' })
)
export const listAdminActionLogs = (params) => (
  request.get('/admin-panel/action-logs/', { params })
)
export const exportAdminActionLogs = (params) => (
  request.get('/admin-panel/action-logs/export/', { params, responseType: 'blob' })
)
