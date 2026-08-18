<template>
  <view class="page">
    <!-- 头像 -->
    <view class="card avatar-card">
      <image v-if="user?.avatar" class="avatar" :src="mediaURL(user.avatar)" mode="aspectFill" />
      <view v-else class="avatar fallback">{{ (user?.username || '智')[0] }}</view>
      <text class="avatar-btn" @click="pickAvatar">更换头像</text>
    </view>

    <!-- 资料 -->
    <view class="card">
      <view class="card-title">基本资料</view>
      <view class="field">
        <text class="label">用户名</text>
        <view class="input readonly">{{ user?.username }}</view>
      </view>
      <view class="field">
        <text class="label">真实姓名</text>
        <input v-model="form.real_name" class="input" placeholder="请输入真实姓名" placeholder-class="ph" />
      </view>
      <view class="field">
        <text class="label">手机号</text>
        <input v-model="form.phone" class="input" type="number" maxlength="11" placeholder="请输入手机号" placeholder-class="ph" />
      </view>
      <button class="primary-btn" :disabled="saving" :loading="saving" @click="saveProfile">保存资料</button>
    </view>

    <!-- 改密码 -->
    <view class="card">
      <view class="card-title">修改密码</view>
      <view class="field">
        <text class="label">当前密码</text>
        <input v-model="pwd.current_password" class="input" password placeholder="请输入当前密码" placeholder-class="ph" />
      </view>
      <view class="field">
        <text class="label">新密码</text>
        <input v-model="pwd.new_password" class="input" password maxlength="12" placeholder="8~12 位，不能全数字" placeholder-class="ph" />
      </view>
      <view class="field">
        <text class="label">确认新密码</text>
        <input v-model="pwd.confirm_password" class="input" password maxlength="12" placeholder="再次输入新密码" placeholder-class="ph" />
      </view>
      <button class="primary-btn" :disabled="changing" :loading="changing" @click="savePassword">修改密码</button>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { getMe, updateMe, changePassword, uploadAvatar } from '@/api/auth.js'
import { mediaURL } from '@/config.js'

const user = ref(null)
const form = ref({ real_name: '', phone: '' })
const pwd = ref({ current_password: '', new_password: '', confirm_password: '' })
const saving = ref(false)
const changing = ref(false)

onShow(async () => {
  try {
    const me = await getMe()
    user.value = me
    uni.setStorageSync('user', me)
    form.value = { real_name: me.real_name || '', phone: me.phone || '' }
  } catch {
    user.value = uni.getStorageSync('user') || null
    form.value = { real_name: user.value?.real_name || '', phone: user.value?.phone || '' }
  }
})

function pickAvatar() {
  uni.chooseImage({
    count: 1,
    success: async (res) => {
      try {
        await uploadAvatar(res.tempFilePaths[0])
        const me = await getMe()
        user.value = me
        uni.setStorageSync('user', me)
        uni.showToast({ title: '头像已更新', icon: 'success' })
      } catch {
        // toast 已提示
      }
    },
  })
}

async function saveProfile() {
  saving.value = true
  try {
    const me = await updateMe({ real_name: form.value.real_name.trim(), phone: form.value.phone.trim() })
    user.value = me
    uni.setStorageSync('user', me)
    uni.showToast({ title: '已保存', icon: 'success' })
  } finally {
    saving.value = false
  }
}

async function savePassword() {
  const p = pwd.value
  if (!p.current_password || !p.new_password) return uni.showToast({ title: '请填写完整', icon: 'none' })
  if (p.new_password.length < 8 || p.new_password.length > 12) {
    return uni.showToast({ title: '新密码需 8~12 位', icon: 'none' })
  }
  if (/^\d+$/.test(p.new_password)) return uni.showToast({ title: '新密码不能全为数字', icon: 'none' })
  if (p.new_password !== p.confirm_password) return uni.showToast({ title: '两次输入不一致', icon: 'none' })
  changing.value = true
  try {
    await changePassword(p)
    uni.showToast({ title: '密码已修改', icon: 'success' })
    pwd.value = { current_password: '', new_password: '', confirm_password: '' }
  } finally {
    changing.value = false
  }
}
</script>

<style scoped>
.page { padding: 28rpx; }
.card { margin-bottom: 20rpx; padding: 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.avatar-card { display: flex; flex-direction: column; align-items: center; }
.avatar { width: 140rpx; height: 140rpx; border-radius: 50%; }
.avatar.fallback { display: flex; align-items: center; justify-content: center; background: #2563eb; color: #fff; font-size: 52rpx; font-weight: 700; }
.avatar-btn { margin-top: 16rpx; font-size: 24rpx; color: #2563eb; }
.card-title { margin-bottom: 20rpx; font-size: 28rpx; font-weight: 700; color: #0f172a; }
.field { margin-bottom: 18rpx; }
.label { display: block; margin-bottom: 10rpx; font-size: 24rpx; color: #64748b; }
.input { height: 80rpx; line-height: 80rpx; padding: 0 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; color: #334155; box-sizing: border-box; }
.input.readonly { color: #94a3b8; }
.ph { color: #94a3b8; }
.primary-btn { height: 84rpx; line-height: 84rpx; border-radius: 20rpx; background: #2563eb; color: #fff; font-size: 28rpx; font-weight: 600; }
.primary-btn::after { border: none; }
</style>
