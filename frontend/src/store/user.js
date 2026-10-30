import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  getMe,
  login as loginApi,
  logout as logoutApi,
  updateMe,
  uploadAvatar,
} from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('access_token') || '')
  const profile = ref(null)
  const isProfileComplete = computed(() => Boolean(
    // 手机号已停止采集，资料完整度只看姓名
    profile.value?.real_name?.trim(),
  ))

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

  async function updateProfile(payload) {
    profile.value = await updateMe(payload)
    return profile.value
  }

  async function updateAvatar(file) {
    profile.value = await uploadAvatar(file)
    return profile.value
  }

  function logout() {
    // P5-A2：尽力通知后端吊销 token（refresh 进黑名单 + access 作废线前移）。
    // 请求失败（已失效/网络断）都不影响本地清理，登出永远成功。
    const refresh = localStorage.getItem('refresh_token')
    logoutApi(refresh).catch(() => {})
    token.value = ''
    profile.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  const isTeacher = () => profile.value?.role === 'teacher'
  const isStudent = () => profile.value?.role === 'student'
  // 组织层（建班、导入、学籍）只对管理员开放，页面用它决定入口是否渲染
  const isAdmin = () => profile.value?.role === 'admin'

  // ---- 学籍门控（P4 流转）----
  // 与后端 apps/common/access.py 的两条拦截线一一对应：
  //   提交类（交作业/开考/提问/实验）仅 enrolled 放行；学习类只拦 suspended。
  // 提示语由页面传入动作名拼成，与后端 403 逐字一致（如「已毕业，不能提交作业」）。
  const eduStatus = computed(() => profile.value?.edu_status || 'enrolled')
  const canSubmit = computed(() => eduStatus.value === 'enrolled')
  const eduStatusLabel = computed(() => profile.value?.edu_status_display || '')
  function submitBlockReason(action) {
    const labels = { suspended: '休学中', graduated: '已毕业', withdrawn: '已退学' }
    const label = labels[eduStatus.value] || '学籍状态异常'
    return `${label}，不能${action}`
  }

  return {
    token,
    profile,
    isProfileComplete,
    login,
    fetchProfile,
    updateProfile,
    updateAvatar,
    logout,
    isTeacher,
    isStudent,
    isAdmin,
    eduStatus,
    canSubmit,
    eduStatusLabel,
    submitBlockReason,
  }
})
