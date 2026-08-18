<template>
  <view class="page">
    <view class="identity">
      <image v-if="user?.avatar" class="avatar" :src="mediaURL(user.avatar)" mode="aspectFill" />
      <view v-else class="avatar avatar-fallback">{{ avatarText }}</view>
      <view class="name">{{ user?.username || '智课用户' }}</view>
      <view class="sub">姓名 · {{ user?.real_name || '未填写' }}</view>
      <text class="role">{{ user?.role_display || '平台用户' }}</text>
    </view>

    <view class="card">
      <view class="row">
        <text class="row-label">手机号</text>
        <text class="row-value">{{ user?.phone || '-' }}</text>
      </view>
      <view class="row">
        <text class="row-label">账号类型</text>
        <text class="row-value">{{ user?.role_display || '-' }}</text>
      </view>
      <view class="row">
        <text class="row-label">加入时间</text>
        <text class="row-value">{{ joinedDate }}</text>
      </view>
    </view>

    <button class="edit" @click="goEdit">编辑资料</button>
    <button class="logout" @click="logout">退出登录</button>
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { getMe } from '@/api/auth.js'
import { mediaURL } from '@/config.js'

const user = ref(uni.getStorageSync('user') || null)

const avatarText = computed(() => (user.value?.username || '智')[0])
const joinedDate = computed(() => {
  if (!user.value?.date_joined) return '-'
  const d = new Date(user.value.date_joined)
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`
})

onShow(async () => {
  try {
    const me = await getMe()
    user.value = me
    uni.setStorageSync('user', me)
  } catch {
    // 拉取失败沿用缓存
  }
})

function goEdit() {
  uni.navigateTo({ url: '/pages/profile/edit' })
}

function logout() {
  uni.showModal({
    title: '退出登录',
    content: '确定要退出当前账号吗？',
    confirmColor: '#ef4444',
    success: (res) => {
      if (!res.confirm) return
      uni.removeStorageSync('access_token')
      uni.removeStorageSync('refresh_token')
      uni.removeStorageSync('user')
      uni.reLaunch({ url: '/pages/login/index' })
    },
  })
}
</script>

<style scoped>
.page {
  padding: 28rpx;
}

.identity {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 28rpx;
  padding: 48rpx 32rpx 40rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 8rpx rgba(15, 23, 42, 0.06);
}

.avatar {
  width: 150rpx;
  height: 150rpx;
  margin-bottom: 20rpx;
  border-radius: 50%;
  border: 6rpx solid #ffffff;
  box-shadow: 0 8rpx 20rpx rgba(15, 23, 42, 0.15);
}

.avatar-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #2563eb;
  color: #ffffff;
  font-size: 56rpx;
  font-weight: 700;
}

.name {
  font-size: 36rpx;
  font-weight: 800;
  color: #0f172a;
}

.sub {
  margin-top: 8rpx;
  font-size: 24rpx;
  color: #94a3b8;
}

.role {
  margin-top: 16rpx;
  padding: 6rpx 22rpx;
  border-radius: 999rpx;
  background: #eff6ff;
  color: #2563eb;
  font-size: 23rpx;
  font-weight: 700;
}

.card {
  padding: 8rpx 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.04);
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 26rpx 0;
  border-bottom: 1rpx solid #f1f5f9;
}

.row:last-child {
  border-bottom: none;
}

.row-label {
  font-size: 26rpx;
  color: #94a3b8;
}

.row-value {
  font-size: 26rpx;
  font-weight: 600;
  color: #334155;
}

.edit {
  margin-top: 36rpx;
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 24rpx;
  background: #2563eb;
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 600;
}

.edit::after {
  border: none;
}

.logout {
  margin-top: 20rpx;
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 24rpx;
  background: #ffffff;
  border: 1rpx solid #fecaca;
  color: #ef4444;
  font-size: 28rpx;
  font-weight: 600;
}

.logout::after {
  border: none;
}
</style>
