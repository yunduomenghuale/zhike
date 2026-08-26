import { get, post } from '@/utils/request.js'

export const listCourses = (params) => get('/courses/', params)
export const listClasses = (params) => get('/classes/', params)
export const joinClass = (inviteCode) => post('/classes/join/', { invite_code: inviteCode })
export const listCatalogs = (params) => get('/catalogs/', params)
export const listPpts = (params) => get('/ppts/', params)
export const listVideos = (params) => get('/videos/', params)
