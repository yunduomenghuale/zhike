<template>
  <view class="page">
    <AppHeader>
      <template #right><view v-if="unread" class="read-all" @click="readAll">全部已读</view></template>
    </AppHeader>
    <scroll-view class="scroll" scroll-y refresher-enabled :refresher-triggered="refreshing" @refresherrefresh="refresh">
      <view class="content">
        <view v-if="loading" class="loading">正在加载消息…</view>
        <EmptyState v-else-if="!rows.length" icon="notification" title="暂无新消息" description="作业和考试发布后会在这里提醒你" />
        <view v-else class="message-list">
          <view v-for="item in rows" :key="item.id" class="message-card" :class="{ unread: !item.is_read }" hover-class="tap" @click="readOne(item)">
            <view class="type-icon" :class="item.ntype"><uni-icons :type="iconFor(item.ntype)" :color="colorFor(item.ntype)" size="21" /></view>
            <view class="message-copy"><view class="message-head"><view class="message-title">{{ item.title }}</view><view v-if="!item.is_read" class="dot"></view></view><view class="message-content">{{ item.content || item.ntype_display }}</view><view class="message-time">{{ formatTime(item.created_at) }}</view></view>
          </view>
        </view>
      </view>
    </scroll-view>
    <BottomNav active="notifications" :unread="unread" />
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import BottomNav from '@/components/BottomNav.vue'
import EmptyState from '@/components/EmptyState.vue'
import { listNotifications, markAllRead, markRead } from '@/api/notifications.js'

const rows = ref([])
const loading = ref(false)
const refreshing = ref(false)
const unread = computed(() => rows.value.filter((item) => !item.is_read).length)

async function load() {
  loading.value = true
  try { const data = await listNotifications({ page_size: 100 }); rows.value = data.results ?? data }
  finally { loading.value = false; refreshing.value = false }
}
async function readOne(item) { if (!item.is_read) { await markRead(item.id); item.is_read = true } }
async function readAll() { await markAllRead(); rows.value.forEach((item) => { item.is_read = true }); uni.showToast({ title: '已全部标记已读', icon: 'none' }) }
function refresh() { refreshing.value = true; load() }
function iconFor(type) { return type === 'homework' ? 'compose' : type === 'exam' ? 'medal' : 'notification' }
function colorFor(type) { return type === 'homework' ? '#2563eb' : type === 'exam' ? '#f59e0b' : '#6366f1' }
function formatTime(value) { if (!value) return ''; const date = new Date(value); return date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) + ' ' + date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }
onShow(load)
</script>

<style scoped lang="scss">
.page { min-height: 100vh; }
.scroll { height: calc(100vh - var(--app-safe-top) - 96rpx); }
.content { padding: 24rpx 24rpx 126rpx; }
.read-all { color: $brand; font-size: 21rpx; font-weight: 700; }
.message-card { display: flex; align-items: flex-start; gap: 18rpx; margin-bottom: 16rpx; padding: 24rpx; border: 1rpx solid $line; border-radius: 27rpx; background: rgba(255, 255, 255, .8); }
.message-card.unread { border-color: #cfe1ff; background: #fff; box-shadow: 0 9rpx 26rpx rgba(37, 99, 235, .055); }
.type-icon { width: 66rpx; height: 66rpx; flex: 0 0 66rpx; display: flex; align-items: center; justify-content: center; border-radius: 20rpx; background: #eef2ff; }
.type-icon.homework { background: $brand-soft; }
.type-icon.exam { background: #fff7ed; }
.message-copy { min-width: 0; flex: 1; }
.message-head { display: flex; align-items: center; gap: 11rpx; }
.message-title { min-width: 0; overflow: hidden; color: $text-main; font-size: 25rpx; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.dot { width: 11rpx; height: 11rpx; flex: 0 0 11rpx; border-radius: 50%; background: $brand; }
.message-content { margin-top: 8rpx; display: -webkit-box; overflow: hidden; color: $text-sub; font-size: 21rpx; line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.message-time { margin-top: 11rpx; color: $text-light; font-size: 18rpx; }
.loading { padding: 100rpx; color: $text-light; font-size: 23rpx; text-align: center; }
.tap { opacity: .62; transform: scale(.985); }
</style>
