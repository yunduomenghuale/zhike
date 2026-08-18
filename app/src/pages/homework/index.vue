<template>
  <view class="page">
    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">暂无作业</view>
      <view v-for="row in rows" :key="row.id" class="hw-card" @click="open(row)">
        <view class="hw-icon">{{ row.mode === 'questions' ? '📋' : '📝' }}</view>
        <view class="hw-main">
          <view class="hw-title">{{ row.title }}</view>
          <view class="hw-meta">
            <text class="chip">{{ row.mode === 'questions' ? '题库作业' : '附件/文本' }}</text>
            <text class="chip">{{ row.total_score }} 分</text>
          </view>
          <view class="hw-deadline" :class="{ overdue: isOverdue(row) }">
            截止：{{ formatTime(row.deadline) }}
          </view>
        </view>
        <view class="hw-side">
          <text class="status" :class="statusInfo(row).tone">{{ statusInfo(row).label }}</text>
          <text class="arrow">›</text>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listHomeworks, listSubmissions } from '@/api/homework.js'

const rows = ref([])
const subMap = ref({})
const loading = ref(false)

// 提交状态仅学生可见；教师视角的 submissions 是全班学生的，不能按 homework 归一
const isStudent = uni.getStorageSync('user')?.role === 'student'

onShow(load)

async function load() {
  loading.value = true
  try {
    const [hw, subs] = await Promise.all([
      listHomeworks(),
      isStudent ? listSubmissions() : Promise.resolve([]),
    ])
    rows.value = hw.results ?? hw
    const map = {}
    ;(subs.results ?? subs).forEach((s) => { map[s.homework] = s })
    subMap.value = map
  } finally {
    loading.value = false
  }
}

function hasStarted(row) {
  return !row.start_time || new Date(row.start_time).getTime() <= Date.now()
}

function isOverdue(row) {
  return row.deadline && new Date(row.deadline).getTime() < Date.now()
}

function formatTime(value) {
  if (!value) return '不限'
  const d = new Date(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function statusInfo(row) {
  if (!row) return { label: '', tone: 'muted' }
  // 教师视角无个人提交概念，展示作业进行状态
  if (!isStudent) {
    if (!hasStarted(row)) return { label: '未开始', tone: 'muted' }
    if (isOverdue(row)) return { label: '已截止', tone: 'muted' }
    return { label: '进行中', tone: 'success' }
  }
  const sub = subMap.value[row.id]
  if (!hasStarted(row)) return { label: '未开始', tone: 'muted' }
  if (!sub) return { label: '未提交', tone: 'muted' }
  if (sub.correct_status === 'submitted') return { label: '待批改', tone: 'warn' }
  if (sub.correct_status === 'graded') return { label: '待发布成绩', tone: 'warn' }
  return { label: `已发布 ${sub.score} 分`, tone: 'success' }
}

function open(row) {
  uni.navigateTo({ url: `/pages/homework/detail?id=${row.id}` })
}
</script>

<style scoped>
.page {
  padding: 28rpx;
}

.tip {
  padding: 100rpx 0;
  text-align: center;
  font-size: 26rpx;
  color: #94a3b8;
}

.hw-card {
  display: flex;
  align-items: center;
  gap: 22rpx;
  margin-bottom: 20rpx;
  padding: 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.05);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.hw-card:active {
  transform: scale(0.98);
}

.hw-icon {
  width: 84rpx;
  height: 84rpx;
  display: flex;
  flex: 0 0 84rpx;
  align-items: center;
  justify-content: center;
  border-radius: 20rpx;
  background: #eff6ff;
  font-size: 40rpx;
}

.hw-main {
  flex: 1;
  min-width: 0;
}

.hw-title {
  overflow: hidden;
  font-size: 30rpx;
  font-weight: 700;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hw-meta {
  display: flex;
  gap: 12rpx;
  margin-top: 10rpx;
}

.chip {
  padding: 4rpx 16rpx;
  border-radius: 999rpx;
  background: #f1f5f9;
  color: #64748b;
  font-size: 22rpx;
}

.hw-deadline {
  margin-top: 10rpx;
  font-size: 23rpx;
  color: #94a3b8;
}

.hw-deadline.overdue {
  color: #ef4444;
}

.hw-side {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  align-items: flex-end;
  gap: 10rpx;
}

.status {
  padding: 4rpx 16rpx;
  border-radius: 999rpx;
  background: #f1f5f9;
  color: #94a3b8;
  font-size: 22rpx;
}

.status.warn {
  background: #fff7ed;
  color: #d97706;
}

.status.success {
  background: #ecfdf5;
  color: #10b981;
}

.arrow {
  font-size: 36rpx;
  color: #cbd5e1;
}
</style>
