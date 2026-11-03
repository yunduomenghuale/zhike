import { get, post } from '@/utils/request.js'

export const listMaterials = (params) => get('/materials/', params)
export const askQuestion = (data) => post('/qa-records/ask/', data, 120000)
