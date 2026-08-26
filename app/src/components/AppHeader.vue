<template>
  <view class="header" :class="{ compact: back }">
    <view v-if="back" class="back" hover-class="tap" @click="goBack">
      <uni-icons type="left" color="#172033" size="21" />
    </view>
    <view v-else class="brand">
      <view class="logo-wrap">
        <image class="logo" src="/static/smart-course-logo.svg" mode="aspectFit" />
      </view>
      <view>
        <view class="brand-name">智课平台</view>
        <view class="brand-en">SMART COURSE</view>
      </view>
    </view>
    <view v-if="back" class="title">{{ title }}</view>
    <view class="right">
      <slot name="right" />
    </view>
  </view>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  back: { type: Boolean, default: false },
})

function goBack() {
  const pages = getCurrentPages()
  if (pages.length > 1) uni.navigateBack()
  else uni.reLaunch({ url: '/pages/home/index' })
}
</script>

<style scoped lang="scss">
.header {
  position: relative;
  z-index: 10;
  min-height: calc(var(--app-safe-top) + 96rpx);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--app-safe-top) 26rpx 0;
  background: rgba(246, 248, 252, 0.96);
}

.header.compact {
  min-height: calc(var(--app-safe-top) + 92rpx);
  background: rgba(255, 255, 255, 0.97);
  border-bottom: 1rpx solid #eef2f7;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.logo-wrap {
  width: 60rpx;
  height: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 19rpx;
  background: #fff;
  box-shadow: 0 10rpx 28rpx rgba(37, 99, 235, 0.1);
}

.logo { width: 43rpx; height: 43rpx; }
.brand-name { color: #172033; font-size: 26rpx; font-weight: 800; }
.brand-en { color: #94a3b8; font-size: 13rpx; font-weight: 700; letter-spacing: 1.8rpx; }

.back {
  width: 68rpx;
  height: 68rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 22rpx;
  background: #f8fafc;
}

.tap { opacity: 0.58; transform: scale(0.95); }
.title { position: absolute; left: 120rpx; right: 120rpx; overflow: hidden; color: #172033; font-size: 29rpx; font-weight: 800; text-align: center; text-overflow: ellipsis; white-space: nowrap; }
.right { min-width: 68rpx; display: flex; justify-content: flex-end; }
</style>
