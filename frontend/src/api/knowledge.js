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
