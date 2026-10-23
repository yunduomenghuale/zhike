import request from './request'

export const listQuestions = (params) => request.get('/questions/', { params })
export const createQuestion = (data) => request.post('/questions/', data)
export const updateQuestion = (id, data) => request.patch(`/questions/${id}/`, data)
export const deleteQuestion = (id) => request.delete(`/questions/${id}/`)
// AI 多类型生题（异步）：提交 groups → 轮询 /ai-tasks/{id}/ → result.batch_id
export const generateQuestions = (data) => request.post('/questions/generate/', data)

// 章节练习提交（学生）
export const practiceSubmit = (data) => request.post('/questions/practice-submit/', data)

// ---- 题目草稿批次（文档导入 / AI 生题共用的待入库池）----
// 上传题目文档 → 规则解析 → 建批次（multipart：file + course + catalog 可选）
export const importQuestions = (formData) => request.post('/questions/import/', formData)
export const listDraftBatches = (params) => request.get('/question-draft-batches/', { params })
export const getDraftBatch = (id) => request.get(`/question-draft-batches/${id}/`)
// 预览编辑防抖回传：{ drafts: [...], catalog }（origin/course/stats/status 只读）
export const updateDraftBatch = (id, data) => request.patch(`/question-draft-batches/${id}/`, data)
export const deleteDraftBatch = (id) => request.delete(`/question-draft-batches/${id}/`)
// 批量入库：{ items: [草稿...] } → { saved, skipped, failed, remaining }
export const saveDraftBatch = (id, items) => request.post(`/question-draft-batches/${id}/save/`, { items })

// 手动错题（学生错题本）
export const listWrongNotes = (params) => request.get('/wrong-notes/', { params })
export const createWrongNote = (data) => request.post('/wrong-notes/', data)
export const deleteWrongNote = (id) => request.delete(`/wrong-notes/${id}/`)

// 错题巩固状态（学生错题本）
export const listWrongMastery = (params) => request.get('/wrong-mastery/', { params })
export const toggleWrongMastery = (data) => request.post('/wrong-mastery/', data)
