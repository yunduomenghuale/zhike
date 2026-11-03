import { get, post } from '@/utils/request.js'

export const listNotifications = (params) => get('/notifications/', params)
export const markNotificationRead = (id) => post(`/notifications/${id}/read/`)
export const markAllNotificationsRead = () => post('/notifications/read-all/')
