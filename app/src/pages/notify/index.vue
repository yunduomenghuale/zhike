<template>
  <view class="page">
    <view class="toolbar">
      <view class="page-title">消息通知</view>
      <text v-if="hasUnread" class="read-all" @click="readAll">全部已读</text>
    </view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">暂无通知</view>
      <view
        v-for="n in rows"
        :key="n.id"
        class="card"
        :class="{ unread: !n.is_read }"
        @click="open(n)"
      >
        <view class="n-head">
          <text class="chip" :class="n.ntype">{{ typeIcon(n.ntype) }} {{ n.ntype_display || '通知' }}</text>
          <text class="n-time">{{ fmtTime(n.created_at) }}</text>
        </view>
        <view class="n-title">
          <text v-if="!n.is_read" class="dot"></text>{{ n.title }}
        </view>
        <view v-if="n.content" class="n-content">{{ n.content }}</view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listNotifications, markNotificationRead, markAllNotificationsRead } from '@/api/notification.js'

const rows = ref([])
const loading = ref(false)

const hasUnread = computed(() => rows.value.some((n) => !n.is_read))

onShow(load)

async function load() {
  loading.value = true
  try {
    const data = await listNotifications()
    rows.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

function typeIcon(t) {
  return { homework: '📝', exam: '📄', system: '⚙️' }[t] || '🔔'
}

function fmtTime(t) {
  if (!t) return ''
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function open(n) {
  if (n.is_read) return
  n.is_read = true
  try {
    await markNotificationRead(n.id)
  } catch {
    // 忽略
  }
}

async function readAll() {
  await markAllNotificationsRead()
  rows.value = rows.value.map((n) => ({ ...n, is_read: true }))
}
</script>

<style scoped>
.page { padding: 28rpx; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; }
.page-title { font-size: 32rpx; font-weight: 800; color: #0f172a; }
.read-all { font-size: 24rpx; color: #2563eb; }
.tip { padding: 100rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.card { margin-bottom: 16rpx; padding: 24rpx 26rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.card.unread { border-color: #dbeafe; }
.n-head { display: flex; align-items: center; justify-content: space-between; }
.chip { padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 22rpx; }
.chip.homework { background: #f0f9ff; color: #0ea5e9; }
.chip.exam { background: #fef2f2; color: #ef4444; }
.chip.system { background: #f1f5f9; color: #64748b; }
.n-time { font-size: 22rpx; color: #94a3b8; }
.n-title { display: flex; align-items: center; margin-top: 12rpx; font-size: 28rpx; font-weight: 600; color: #0f172a; }
.dot { width: 14rpx; height: 14rpx; margin-right: 12rpx; border-radius: 50%; background: #2563eb; flex-shrink: 0; }
.n-content { margin-top: 10rpx; font-size: 25rpx; line-height: 1.7; color: #64748b; }
</style>
