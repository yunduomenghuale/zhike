<template>
  <view class="page">
    <AppHeader />
    <scroll-view class="scroll" scroll-y>
      <view class="content">
        <view class="profile-card">
          <view class="avatar">{{ avatarText }}</view>
          <view class="profile-copy"><view class="name">{{ user?.real_name || user?.username || '用户' }}</view><view class="username">@{{ user?.username || '-' }}</view></view>
          <view class="role">{{ user?.role_display || '平台用户' }}</view>
        </view>

        <view v-if="profileIncomplete" class="complete-card"><view class="complete-icon"><uni-icons type="info-filled" color="#f59e0b" size="21" /></view><view class="complete-copy"><view class="complete-title">资料待完善</view><view class="complete-desc">填写姓名和手机号后才能加入班级</view></view></view>

        <view class="group-title">账号与资料</view>
        <view class="settings">
          <view class="row"><view class="row-icon blue"><uni-icons type="person" color="#2563eb" size="19" /></view><view class="row-copy"><view class="row-label">姓名</view><view class="row-value">{{ user?.real_name || '未填写' }}</view></view></view>
          <view class="row"><view class="row-icon green"><uni-icons type="phone" color="#10b981" size="19" /></view><view class="row-copy"><view class="row-label">手机号</view><view class="row-value">{{ user?.phone || '未填写' }}</view></view></view>
          <view class="row action" hover-class="tap" @click="uni.navigateTo({ url: '/pages/profile/edit' })"><view class="row-icon purple"><uni-icons type="compose" color="#6366f1" size="19" /></view><view class="row-copy"><view class="row-label">编辑资料</view><view class="row-value">修改姓名和手机号</view></view><uni-icons type="right" color="#cbd5e1" size="14" /></view>
        </view>

        <view class="group-title">其他</view>
        <view class="settings">
          <view class="row"><view class="row-icon gray"><uni-icons type="info" color="#64748b" size="19" /></view><view class="row-copy"><view class="row-label">当前版本</view><view class="row-value">1.0.5</view></view></view>
        </view>
        <button class="logout" @click="logout">退出登录</button>
      </view>
    </scroll-view>
    <BottomNav active="profile" />
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import BottomNav from '@/components/BottomNav.vue'
import { getMe } from '@/api/auth.js'

const user = ref(uni.getStorageSync('user') || null)
const avatarText = computed(() => String(user.value?.real_name || user.value?.username || '智').slice(0, 1))
const profileIncomplete = computed(() => user.value?.role === 'student' && (!user.value?.real_name?.trim() || !user.value?.phone?.trim()))
async function load() { try { user.value = await getMe(); uni.setStorageSync('user', user.value) } catch {} }
function logout() { uni.showModal({ title: '退出登录', content: '确定要退出当前账号吗？', success: ({ confirm }) => { if (!confirm) return; uni.clearStorageSync(); uni.reLaunch({ url: '/pages/login/index' }) } }) }
onShow(load)
</script>

<style scoped lang="scss">
.page { min-height: 100vh; }
.scroll { height: calc(100vh - var(--app-safe-top) - 96rpx); }
.content { padding: 8rpx 24rpx 130rpx; }
.profile-card { display: flex; align-items: center; gap: 20rpx; padding: 30rpx 27rpx; border: 1rpx solid rgba(37, 99, 235, .1); border-radius: 31rpx; background: linear-gradient(135deg, #edf5ff, #fff); box-shadow: $shadow-card; }
.avatar { width: 92rpx; height: 92rpx; flex: 0 0 92rpx; border-radius: 29rpx; background: linear-gradient(135deg, #1d4ed8, #60a5fa); color: #fff; font-size: 38rpx; font-weight: 850; line-height: 92rpx; text-align: center; box-shadow: 0 12rpx 30rpx rgba(37, 99, 235, .2); }
.profile-copy { min-width: 0; flex: 1; }
.name { overflow: hidden; color: $text-main; font-size: 31rpx; font-weight: 850; text-overflow: ellipsis; white-space: nowrap; }
.username { margin-top: 6rpx; color: $text-light; font-size: 20rpx; }
.role { padding: 7rpx 15rpx; border-radius: 999rpx; background: $brand-soft; color: $brand; font-size: 19rpx; font-weight: 700; }
.complete-card { display: flex; align-items: center; gap: 16rpx; margin-top: 22rpx; padding: 22rpx; border: 1rpx solid #fde7bd; border-radius: 24rpx; background: #fffaf0; }
.complete-icon { width: 58rpx; height: 58rpx; display: flex; align-items: center; justify-content: center; border-radius: 18rpx; background: #fff3d6; }
.complete-copy { min-width: 0; flex: 1; }
.complete-title { color: #92400e; font-size: 23rpx; font-weight: 750; }
.complete-desc { margin-top: 5rpx; color: #b45309; font-size: 19rpx; }
.group-title { margin: 42rpx 7rpx 16rpx; color: $text-light; font-size: 20rpx; font-weight: 700; }
.settings { overflow: hidden; padding: 0 24rpx; border: 1rpx solid $line; border-radius: 28rpx; background: #fff; }
.row { min-height: 112rpx; display: flex; align-items: center; gap: 17rpx; border-bottom: 1rpx solid $line; }
.row:last-child { border-bottom: 0; }
.row-icon { width: 60rpx; height: 60rpx; display: flex; align-items: center; justify-content: center; border-radius: 19rpx; }
.row-icon.blue { background: $brand-soft; }.row-icon.green { background: #ecfdf5; }.row-icon.purple { background: #eef2ff; }.row-icon.gray { background: #f1f5f9; }
.row-copy { min-width: 0; flex: 1; }
.row-label { color: $text-main; font-size: 24rpx; font-weight: 700; }
.row-value { margin-top: 5rpx; color: $text-light; font-size: 19rpx; }
.logout { margin-top: 32rpx; height: 92rpx; line-height: 92rpx; border-radius: 25rpx; background: #fff; color: $danger; font-size: 25rpx; font-weight: 750; }
.tap { opacity: .6; }
</style>
