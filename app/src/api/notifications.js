import { get, post } from '@/utils/request.js'

export const listNotifications = (params) => get('/notifications/', params)
export const markRead = (id) => post(`/notifications/${id}/read/`)
export const markAllRead = () => post('/notifications/read-all/')
