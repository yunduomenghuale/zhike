<template>
  <view class="login-page">
    <!-- 品牌色氛围背景（对齐 web 端登录页配色，纯 CSS 轻量实现） -->
    <view class="blob blob-1"></view>
    <view class="blob blob-2"></view>
    <view class="blob blob-3"></view>

    <view class="brand">
      <image class="brand-logo" src="/static/smart-course-logo.svg" mode="aspectFit" />
      <view class="brand-name">智课平台</view>
    </view>

    <view class="login-card">
      <view class="field">
        <text class="field-label">用户名 / 手机号</text>
        <input
          v-model="form.username"
          class="field-input"
          placeholder="请输入用户名或手机号"
          placeholder-class="ph"
        />
      </view>
      <view class="field">
        <text class="field-label">密码</text>
        <input
          v-model="form.password"
          class="field-input"
          password
          placeholder="请输入密码"
          placeholder-class="ph"
          @confirm="submit"
        />
      </view>
      <button class="login-btn" :disabled="loading" :loading="loading" @click="submit">
        {{ loading ? '登录中…' : '登 录' }}
      </button>
    </view>
  </view>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { login } from '@/api/auth.js'

const form = reactive({ username: '', password: '' })
const loading = ref(false)

onShow(() => {
  if (uni.getStorageSync('access_token')) {
    uni.reLaunch({ url: '/pages/home/index' })
  }
})

async function submit() {
  if (!form.username.trim() || !form.password) {
    uni.showToast({ title: '请输入用户名和密码', icon: 'none' })
    return
  }
  loading.value = true
  try {
    const data = await login({ username: form.username.trim(), password: form.password })
    uni.setStorageSync('access_token', data.token.access)
    uni.setStorageSync('refresh_token', data.token.refresh)
    if (data.user) uni.setStorageSync('user', data.user)
    uni.reLaunch({ url: '/pages/home/index' })
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 48rpx;
  padding-bottom: 22vh; /* 视觉重心上移，避免内容沉在下半屏 */
  box-sizing: border-box;
  background: #f8fafc;
}

/* 品牌色漂浮光斑（web 端 LoginBackground 的粒子配色） */
.blob {
  position: absolute;
  z-index: 0;
  border-radius: 50%;
  pointer-events: none;
}

.blob-1 {
  width: 620rpx;
  height: 620rpx;
  top: -180rpx;
  right: -160rpx;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.22), transparent 70%);
  animation: drift-1 9s ease-in-out infinite;
}

.blob-2 {
  width: 540rpx;
  height: 540rpx;
  bottom: 6%;
  left: -180rpx;
  background: radial-gradient(circle, rgba(79, 70, 229, 0.16), transparent 70%);
  animation: drift-2 11s ease-in-out infinite;
}

.blob-3 {
  width: 420rpx;
  height: 420rpx;
  bottom: 32%;
  right: -100rpx;
  background: radial-gradient(circle, rgba(52, 211, 153, 0.14), transparent 70%);
  animation: drift-1 13s ease-in-out infinite reverse;
}

@keyframes drift-1 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(-32rpx, 28rpx) scale(1.08); }
}

@keyframes drift-2 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(28rpx, -24rpx) scale(1.06); }
}

.brand,
.login-card {
  position: relative;
  z-index: 1;
}

.brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 22rpx;
  margin-bottom: 64rpx;
}

.brand-logo {
  width: 92rpx;
  height: 92rpx;
  display: block;
}

.brand-name {
  font-size: 56rpx;
  font-weight: 750;
  letter-spacing: -1rpx;
  line-height: 1.2;
  color: #0f172a;
}

.login-card {
  padding: 48rpx 40rpx;
  border-radius: 24rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 4rpx 12rpx rgba(15, 23, 42, 0.08);
}

.field {
  margin-bottom: 32rpx;
}

.field-label {
  display: block;
  margin-bottom: 12rpx;
  font-size: 26rpx;
  font-weight: 600;
  color: #475569;
}

.field-input {
  height: 88rpx;
  padding: 0 28rpx;
  border-radius: 24rpx;
  background: #f1f5f9;
  border: 1rpx solid transparent;
  font-size: 28rpx;
  box-sizing: border-box;
}

.ph {
  color: #94a3b8;
}

.login-btn {
  margin-top: 20rpx;
  height: 96rpx;
  line-height: 96rpx;
  border-radius: 24rpx;
  background: #2563eb;
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 600;
}

.login-btn::after {
  border: none;
}
</style>
