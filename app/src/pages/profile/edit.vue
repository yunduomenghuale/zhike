<template>
  <view class="page">
    <AppHeader title="编辑资料" back />
    <scroll-view class="scroll" scroll-y>
      <view class="content">
        <view class="intro"><view class="intro-icon"><uni-icons type="person" color="#2563eb" size="24" /></view><view><view class="intro-title">完善个人资料</view><view class="intro-desc">姓名和手机号用于班级身份识别</view></view></view>
        <view class="form-card">
          <view class="field-label">用户名</view>
          <view class="field disabled"><uni-icons type="person" color="#94a3b8" size="19" /><input v-model="form.username" class="input" disabled /></view>
          <view class="field-note">用户名是唯一登录标识</view>

          <view class="field-label required">姓名</view>
          <view class="field" :class="{ focused: focus === 'name' }"><uni-icons type="staff" color="#94a3b8" size="19" /><input v-model.trim="form.real_name" class="input" placeholder="请输入真实姓名" placeholder-class="placeholder" :maxlength="64" @focus="focus = 'name'" @blur="focus = ''" /></view>

          <view class="field-label required">手机号</view>
          <view class="field" :class="{ focused: focus === 'phone' }"><uni-icons type="phone" color="#94a3b8" size="19" /><input v-model.trim="form.phone" class="input" type="number" placeholder="请输入手机号" placeholder-class="placeholder" :maxlength="20" @focus="focus = 'phone'" @blur="focus = ''" /></view>
        </view>
        <button class="save" :disabled="saving || !canSave" :loading="saving" @click="save">保存资料</button>
        <view class="privacy"><uni-icons type="locked" color="#94a3b8" size="15" /><text>你的资料仅用于平台教学与班级管理</text></view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import { getMe, updateMe } from '@/api/auth.js'

const form = reactive({ username: '', real_name: '', phone: '' })
const focus = ref('')
const saving = ref(false)
const canSave = computed(() => form.real_name.trim().length > 0 && /^\+?\d{6,20}$/.test(form.phone.trim()))

async function load() {
  const user = await getMe()
  Object.assign(form, { username: user.username || '', real_name: user.real_name || '', phone: user.phone || '' })
}
async function save() {
  if (!canSave.value || saving.value) return
  saving.value = true
  try {
    const user = await updateMe({ username: form.username, real_name: form.real_name.trim(), phone: form.phone.trim() })
    uni.setStorageSync('user', user)
    uni.showToast({ title: '资料已保存', icon: 'success' })
    setTimeout(() => uni.navigateBack(), 450)
  } finally { saving.value = false }
}
onLoad(load)
</script>

<style scoped lang="scss">
.page { min-height: 100vh; }
.scroll { height: calc(100vh - var(--app-safe-top) - 92rpx); }
.content { padding: 28rpx 28rpx 60rpx; }
.intro { display: flex; align-items: center; gap: 18rpx; padding: 26rpx; border: 1rpx solid rgba(37, 99, 235, .1); border-radius: 28rpx; background: linear-gradient(135deg, #edf5ff, #fff); }
.intro-icon { width: 74rpx; height: 74rpx; display: flex; align-items: center; justify-content: center; border-radius: 22rpx; background: #fff; }
.intro-title { color: $text-main; font-size: 27rpx; font-weight: 850; }
.intro-desc { margin-top: 6rpx; color: $text-sub; font-size: 20rpx; }
.form-card { margin-top: 26rpx; padding: 28rpx; border: 1rpx solid $line; border-radius: 29rpx; background: #fff; }
.field-label { margin: 26rpx 5rpx 12rpx; color: $text-main; font-size: 22rpx; font-weight: 750; }
.field-label:first-child { margin-top: 0; }
.field-label.required::after { content: '*'; margin-left: 5rpx; color: $danger; }
.field { height: 92rpx; display: flex; align-items: center; gap: 16rpx; padding: 0 22rpx; border: 2rpx solid transparent; border-radius: 23rpx; background: #f5f7fb; }
.field.focused { border-color: #60a5fa; background: #fff; box-shadow: 0 0 0 6rpx rgba(59, 130, 246, .07); }
.field.disabled { color: $text-light; }
.input { min-width: 0; flex: 1; height: 100%; color: $text-main; font-size: 25rpx; }
.placeholder { color: #a7b0bf; }
.field-note { margin: 9rpx 5rpx 0; color: $text-light; font-size: 18rpx; }
.save { margin-top: 30rpx; height: 96rpx; line-height: 96rpx; border-radius: 26rpx; background: linear-gradient(135deg, $brand-deep, #3b82f6); color: #fff; font-size: 26rpx; font-weight: 750; box-shadow: 0 16rpx 34rpx rgba(37, 99, 235, .2); }
.save[disabled] { background: #bfdbfe; box-shadow: none; color: #fff; }
.privacy { display: flex; align-items: center; justify-content: center; gap: 8rpx; margin-top: 24rpx; color: $text-light; font-size: 18rpx; }
</style>
