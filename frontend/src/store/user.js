import { defineStore } from 'pinia'
import { ref } from 'vue'
import { login as loginApi, getMe } from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('access_token') || '')
  const profile = ref(null)

  async function login(payload) {
    const data = await loginApi(payload)
    token.value = data.token.access
    localStorage.setItem('access_token', data.token.access)
    localStorage.setItem('refresh_token', data.token.refresh)
    profile.value = data.user
    return data.user
  }

  async function fetchProfile() {
    profile.value = await getMe()
    return profile.value
  }

  function logout() {
    token.value = ''
    profile.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  const isTeacher = () => profile.value?.role === 'teacher'
  const isStudent = () => profile.value?.role === 'student'

  return { token, profile, login, fetchProfile, logout, isTeacher, isStudent }
})
