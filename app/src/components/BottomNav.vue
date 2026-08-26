<template>
  <view class="nav-shell">
    <view class="nav">
      <view v-for="item in items" :key="item.key" class="nav-item" :class="{ active: active === item.key }" @click="open(item)">
        <view class="icon-wrap">
          <uni-icons :type="item.icon" :color="active === item.key ? '#2563eb' : '#94a3b8'" size="22" />
          <view v-if="item.badge" class="badge">{{ item.badge > 9 ? '9+' : item.badge }}</view>
        </view>
        <text>{{ item.label }}</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  active: { type: String, required: true },
  unread: { type: Number, default: 0 },
})

const items = computed(() => [
  { key: 'home', label: '工作台', icon: 'home', url: '/pages/home/index' },
  { key: 'courses', label: '课程', icon: 'list', url: '/pages/courses/index' },
  { key: 'notifications', label: '消息', icon: 'notification', url: '/pages/notifications/index', badge: props.unread },
  { key: 'profile', label: '我的', icon: 'person', url: '/pages/profile/index' },
])

function open(item) {
  if (item.key === props.active) return
  uni.reLaunch({ url: item.url })
}
</script>

<style scoped lang="scss">
.nav-shell {
  position: fixed;
  z-index: 30;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 6rpx 20rpx calc(6rpx + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.96);
  border-top: 1rpx solid rgba(226, 232, 240, 0.88);
}

.nav { height: 84rpx; display: flex; align-items: center; }
.nav-item { min-height: 76rpx; flex: 1; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 4rpx; color: #94a3b8; font-size: 17rpx; }
.nav-item.active { color: #2563eb; font-weight: 700; }
.icon-wrap { position: relative; width: 48rpx; height: 40rpx; display: flex; align-items: center; justify-content: center; }
.badge { position: absolute; top: -5rpx; right: -5rpx; min-width: 26rpx; height: 26rpx; padding: 0 6rpx; border: 3rpx solid #fff; border-radius: 999rpx; background: #ef4444; color: #fff; font-size: 16rpx; line-height: 26rpx; text-align: center; }
</style>
