import { get } from '@/utils/request.js'

// ===== 虚拟实验（学生查看成绩用） =====
export const listLabs = (params) => get('/labs/', params)
export const listLabSubmissions = (params) => get('/lab-submissions/', params)
