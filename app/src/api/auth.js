import { get, patch, post } from '@/utils/request.js'

export const login = (data) => post('/auth/login/', data)
export const register = (data) => post('/auth/register/', data)
export const getMe = () => get('/auth/me/')
export const updateMe = (data) => patch('/auth/me/', data)
