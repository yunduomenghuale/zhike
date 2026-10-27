import request from './request'

export const listQuestions = (params) => request.get('/questions/', { params })
export const createQuestion = (data) => request.post('/questions/', data)
export const updateQuestion = (id, data) => request.patch(`/questions/${id}/`, data)
export const deleteQuestion = (id) => request.delete(`/questions/${id}/`)
// 题目配图上传（教师）：选择即上传，返回 {path, url}；保存题目/草稿时回传 path
export const uploadQuestionImage = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/question-images/upload/', formData)
}
// AI 多类型生题（异步）：提交 groups → 轮询 /ai-tasks/{id}/ → result.batch_id
export const generateQuestions = (data) => request.post('/questions/generate/', data)

// 章节练习提交（学生）
export const practiceSubmit = (data) => request.post('/questions/practice-submit/', data)

// ---- 题目草稿批次（文档导入 / AI 生题共用的待入库池）----
// 上传题目文档 → 规则解析 → 建批次（multipart：file + course + catalog 可选；选择即上传，onUploadProgress 报字节进度）
export const importQuestions = (formData, onUploadProgress) =>
  request.post('/questions/import/', formData, { onUploadProgress })
export const listDraftBatches = (params) => request.get('/question-draft-batches/', { params })
export const getDraftBatch = (id) => request.get(`/question-draft-batches/${id}/`)
// 预览编辑防抖回传：{ drafts: [...], catalog }（origin/course/stats/status 只读）
export const updateDraftBatch = (id, data) => request.patch(`/question-draft-batches/${id}/`, data)
export const deleteDraftBatch = (id) => request.delete(`/question-draft-batches/${id}/`)
// 批量入库：{ items: [草稿...], publish } → { saved, skipped, failed, remaining }；publish=true 时入库即发布
export const saveDraftBatch = (id, items, publish = false) =>
  request.post(`/question-draft-batches/${id}/save/`, { items, publish })

// 手动错题（学生错题本）
export const listWrongNotes = (params) => request.get('/wrong-notes/', { params })
export const createWrongNote = (data) => request.post('/wrong-notes/', data)
export const deleteWrongNote = (id) => request.delete(`/wrong-notes/${id}/`)

// 错题巩固状态（学生错题本）
export const listWrongMastery = (params) => request.get('/wrong-mastery/', { params })
export const toggleWrongMastery = (data) => request.post('/wrong-mastery/', data)
