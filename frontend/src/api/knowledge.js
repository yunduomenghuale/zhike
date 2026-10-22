import request from './request'

// ===== 教辅资料（知识库）=====
export const listMaterials = (params) => request.get('/materials/', { params })

// 上传资料（multipart，自动解析入库）；catalog 可选，关联后 AI 助教参考来源展示章节名
export const uploadMaterial = ({ course, classroom, catalog, file, onProgress }) => {
  const form = new FormData()
  form.append('course', course)
  if (classroom) form.append('classroom', classroom)
  if (catalog) form.append('catalog', catalog)
  form.append('file', file)
  form.append('file_name', file.name)
  return request.post('/materials/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
}

export const updateMaterial = (id, data) => request.patch(`/materials/${id}/`, data)

export const reparseMaterial = (id) => request.post(`/materials/${id}/reparse/`)
export const toggleQa = (id) => request.post(`/materials/${id}/toggle-qa/`)
export const deleteMaterial = (id) => request.delete(`/materials/${id}/`)

// 重建课程/资料向量（换向量模型后必须执行；全量重算耗时较长，超时放到 10 分钟）
export const rebuildVectors = (data) => request.post('/materials/rebuild-vectors/', data, { timeout: 600000 })

// 在线预览（PDF/Word/PPT 逐页图；txt 返回文本）
export const previewMaterial = (id) => request.get(`/materials/${id}/preview/`)

// 下载资料（blob 透传：响应拦截器对非统一 {code,message,data} 结构直接返回）
export const downloadMaterial = (id) =>
  request.get(`/materials/${id}/download/`, { responseType: 'blob', timeout: 300000 })

// ===== 问答记录 =====
export const listQaRecords = (params) => request.get('/qa-records/', { params })
export const askQuestion = (data) => request.post('/qa-records/ask/', data)

// ===== 教师端问答质量（质量看板 Phase 2）=====
// 指标口径同管理端（为空率/改写率/好评率/兜底率/降级/来源/课程排行/告警），
// 仅收窄本人课程、无成本段；params: { days } 或 { start, end } 日历窗
export const getTeacherQAQualityStats = (params) => request.get('/qa-quality-stats/', { params })

// 问题下钻：type=all|empty|disliked，course 可选（须本人课程，否则 404），
// 窗口参数同统计端点，另支持 page/page_size 分页
export const listTeacherQAIssues = (params) => request.get('/qa-issues/', { params })

// 当前对话模型是否支持图片（多模态）：不支持时前端隐藏图片上传入口，
// 避免用户发送图片后被接口拒绝；拉取失败按不支持处理（fail-closed）
export const getQaVisionCapability = () => request.get('/qa-records/vision-capability/')

// 问答反馈：value 1 有用 / -1 无用 / 0 取消（幂等覆盖）
export const submitQaFeedback = (id, value) => request.post(`/qa-records/${id}/feedback/`, { value })

// ===== 问答会话（QASession）=====
// params: { course, catalog?（空字符串=只看课程级）, status? }
export const listQaSessions = (params) => request.get('/qa-sessions/', { params })
export const createQaSession = (data) => request.post('/qa-sessions/', data)
export const updateQaSession = (id, data) => request.patch(`/qa-sessions/${id}/`, data)
export const deleteQaSession = (id) => request.delete(`/qa-sessions/${id}/`)
export const listQaSessionRecords = (id) => request.get(`/qa-sessions/${id}/records/`)
