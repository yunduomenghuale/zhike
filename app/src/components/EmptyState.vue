<template>
  <view class="empty" :class="{ compact }">
    <view class="icon"><uni-icons :type="icon" color="#94a3b8" size="28" /></view>
    <view class="copy">
      <view class="title">{{ title }}</view>
      <view v-if="description" class="description">{{ description }}</view>
    </view>
  </view>
</template>

<script setup>
defineProps({
  icon: { type: String, default: 'info' },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})
</script>

<style scoped>
.empty { padding: 82rpx 30rpx 96rpx; text-align: center; }
.icon { width: 80rpx; height: 80rpx; display: flex; align-items: center; justify-content: center; margin: 0 auto; border-radius: 24rpx; background: #eef2f7; }
.title { margin-top: 20rpx; color: #475569; font-size: 25rpx; font-weight: 700; }
.description { margin-top: 8rpx; color: #94a3b8; font-size: 20rpx; line-height: 1.5; }
.compact { display: flex; align-items: center; gap: 18rpx; padding: 23rpx; border: 1rpx solid #e8edf5; border-radius: 25rpx; background: #fff; text-align: left; }
.compact .icon { width: 62rpx; height: 62rpx; flex: 0 0 62rpx; margin: 0; border-radius: 19rpx; }
.compact .copy { min-width: 0; flex: 1; }
.compact .title { margin-top: 0; color: #334155; font-size: 23rpx; }
.compact .description { margin-top: 4rpx; font-size: 18rpx; }
</style>
