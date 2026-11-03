<template>
  <view class="page">
    <view class="orb orb-one"></view>
    <view class="orb orb-two"></view>

    <view class="top-brand">
      <view class="logo-wrap"><image class="logo" src="/static/smart-course-logo.svg" mode="aspectFit" /></view>
      <view>
        <view class="brand-name">智课平台</view>
        <view class="brand-en">SMART COURSE</view>
      </view>
    </view>

    <view class="content">
      <view class="eyebrow">{{ mode === 'login' ? '欢迎回来' : '加入智课' }}</view>
      <view class="title">{{ mode === 'login' ? '登录账号' : '创建账号' }}</view>
      <view class="subtitle">{{ mode === 'login' ? '继续你的教学与学习进度' : '用唯一用户名开启学习' }}</view>

      <view class="form-card">
        <view class="field" :class="{ focused: focus === 'username' }">
          <uni-icons type="person" color="#94a3b8" size="20" />
          <input v-model.trim="form.username" class="input" placeholder="请输入用户名" placeholder-class="placeholder" :maxlength="30" @focus="focus = 'username'" @blur="focus = ''" />
        </view>

        <view class="field" :class="{ focused: focus === 'password' }">
          <uni-icons type="locked" color="#94a3b8" size="20" />
          <input v-model="form.password" class="input" :password="!passwordVisible" placeholder="请输入密码" placeholder-class="placeholder" :maxlength="12" @focus="focus = 'password'" @blur="passwordTouched = true; focus = ''" />
          <view class="eye" @click="passwordVisible = !passwordVisible">
            <uni-icons :type="passwordVisible ? 'eye-filled' : 'eye-slash-filled'" color="#94a3b8" size="20" />
          </view>
        </view>
        <view v-if="mode === 'register' && passwordTouched && !registerPasswordValid" class="field-hint">密码长度需为 8–12 位</view>

        <view v-if="mode === 'register'" class="role-group">
          <view class="role-card" :class="{ active: form.role === 'teacher' }" @click="form.role = 'teacher'">
            <view class="role-icon"><uni-icons type="staff" :color="form.role === 'teacher' ? '#2563eb' : '#64748b'" size="23" /></view>
            <view><view class="role-name">教师</view><view class="role-desc">创建与管理课程</view></view>
          </view>
          <view class="role-card" :class="{ active: form.role === 'student' }" @click="form.role = 'student'">
            <view class="role-icon"><uni-icons type="medal" :color="form.role === 'student' ? '#2563eb' : '#64748b'" size="23" /></view>
            <view><view class="role-name">学生</view><view class="role-desc">加入班级开始学习</view></view>
          </view>
        </view>

        <button class="primary" :disabled="submitting || !canSubmit" :loading="submitting" @click="submit">
          {{ mode === 'login' ? '登录' : '注册并登录' }}
        </button>
      </view>

      <view class="switch-row">
        <text>{{ mode === 'login' ? '还没有账号？' : '已经有账号？' }}</text>
        <text class="switch" @click="toggleMode">{{ mode === 'login' ? '立即注册' : '返回登录' }}</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { login, register } from '@/api/auth.js'

const mode = ref('login')
const form = reactive({ username: '', password: '', role: 'student' })
const focus = ref('')
const passwordTouched = ref(false)
const passwordVisible = ref(false)
const submitting = ref(false)
const registerPasswordValid = computed(() => form.password.length >= 8 && form.password.length <= 12)
const canSubmit = computed(() => form.username.length > 0 && (mode.value === 'login' ? form.password.length > 0 : registerPasswordValid.value))

function toggleMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  passwordTouched.value = false
}

function saveSession(data) {
  const token = data.token || {}
  uni.setStorageSync('access_token', token.access)
  uni.setStorageSync('refresh_token', token.refresh)
  uni.setStorageSync('user', data.user)
}

async function submit() {
  passwordTouched.value = true
  if (!canSubmit.value || submitting.value) return
  submitting.value = true
  try {
    const data = mode.value === 'login'
      ? await login({ username: form.username, password: form.password })
      : await register({ username: form.username, password: form.password, role: form.role })
    saveSession(data)
    uni.showToast({ title: mode.value === 'login' ? '登录成功' : '欢迎加入智课平台', icon: 'success' })
    setTimeout(() => uni.reLaunch({ url: '/pages/home/index' }), 450)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped lang="scss">
.page { position: relative; min-height: 100vh; overflow: hidden; padding: calc(var(--app-safe-top) + 24rpx) 38rpx 42rpx; background: linear-gradient(165deg, #f2f7ff 0%, #fff 48%, #f7f9fc 100%); }
.orb { position: absolute; border-radius: 50%; pointer-events: none; }
.orb-one { top: -170rpx; right: -210rpx; width: 520rpx; height: 520rpx; background: rgba(191, 219, 254, 0.44); }
.orb-two { left: -220rpx; bottom: 100rpx; width: 440rpx; height: 440rpx; background: rgba(224, 231, 255, 0.38); }
.top-brand { position: relative; display: flex; align-items: center; gap: 16rpx; }
.logo-wrap { width: 68rpx; height: 68rpx; display: flex; align-items: center; justify-content: center; border-radius: 21rpx; background: #fff; box-shadow: $shadow-card; }
.logo { width: 48rpx; height: 48rpx; }
.brand-name { color: $text-main; font-size: 28rpx; font-weight: 800; }
.brand-en { color: $text-light; font-size: 14rpx; font-weight: 700; letter-spacing: 2.2rpx; }
.content { position: relative; max-width: 680rpx; margin: 78rpx auto 0; }
.eyebrow { color: $brand; font-size: 20rpx; font-weight: 700; letter-spacing: 1.5rpx; }
.title { margin-top: 10rpx; color: $text-main; font-size: 48rpx; font-weight: 850; line-height: 1.18; }
.subtitle { margin-top: 13rpx; color: $text-sub; font-size: 22rpx; }
.form-card { margin-top: 40rpx; }
.field { height: 92rpx; display: flex; align-items: center; gap: 16rpx; margin-bottom: 18rpx; padding: 0 24rpx; border: 2rpx solid transparent; border-radius: 25rpx; background: rgba(255, 255, 255, 0.94); box-shadow: 0 10rpx 28rpx rgba(15, 23, 42, 0.052); }
.field.focused { border-color: #60a5fa; box-shadow: 0 0 0 7rpx rgba(59, 130, 246, 0.08); }
.input { min-width: 0; flex: 1; height: 100%; color: $text-main; font-size: 25rpx; }
.placeholder { color: #a7b0bf; }
.eye { width: 56rpx; height: 56rpx; display: flex; align-items: center; justify-content: center; }
.field-hint { margin: -8rpx 8rpx 20rpx; color: $danger; font-size: 21rpx; }
.role-group { display: flex; gap: 18rpx; margin: 10rpx 0 28rpx; }
.role-card { min-width: 0; flex: 1; min-height: 140rpx; padding: 20rpx; border: 2rpx solid $line; border-radius: 25rpx; background: rgba(255, 255, 255, 0.78); }
.role-card.active { border-color: #60a5fa; background: $brand-soft; }
.role-icon { width: 54rpx; height: 54rpx; display: flex; align-items: center; justify-content: center; border-radius: 16rpx; background: #fff; }
.role-name { margin-top: 13rpx; color: $text-main; font-size: 24rpx; font-weight: 750; }
.role-desc { margin-top: 4rpx; overflow: hidden; color: $text-light; font-size: 18rpx; text-overflow: ellipsis; white-space: nowrap; }
.primary { height: 92rpx; line-height: 92rpx; border-radius: 25rpx; background: linear-gradient(135deg, $brand-deep, #3b82f6); color: #fff; font-size: 26rpx; font-weight: 750; box-shadow: 0 15rpx 32rpx rgba(37, 99, 235, 0.22); }
.primary[disabled] { background: #bfdbfe; box-shadow: none; color: #fff; }
.switch-row { margin-top: 28rpx; color: $text-light; font-size: 21rpx; text-align: center; }
.switch { margin-left: 8rpx; color: $brand; font-weight: 700; }
</style>
