import request from './request'

// ===== 实验必读 =====
export const getLabGuide = () => request.get('/lab-guide/1/')
export const updateLabGuide = (data) => request.patch('/lab-guide/1/', data)
export const resetLabGuide = () => request.post('/lab-guide/1/reset/')
