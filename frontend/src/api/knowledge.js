import request from './request'

// ===== 教辅资料（知识库）=====
export const listMaterials = (params) => request.get('/materials/', { params })

// 上传资料（multipart，自动解析入库）
export const uploadMaterial = ({ course, classroom, file, onProgress }) => {
  const form = new FormData()
  form.append('course', course)
  if (classroom) form.append('classroom', classroom)
  form.append('file', file)
  form.append('file_name', file.name)
  return request.post('/materials/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
}

export const reparseMaterial = (id) => request.post(`/materials/${id}/reparse/`)
export const toggleQa = (id) => request.post(`/materials/${id}/toggle-qa/`)
export const deleteMaterial = (id) => request.delete(`/materials/${id}/`)

// ===== 问答记录 =====
export const listQaRecords = (params) => request.get('/qa-records/', { params })
export const askQuestion = (data) => request.post('/qa-records/ask/', data)
