<template>
  <view class="page">
    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">暂无考试</view>
      <view v-for="e in rows" :key="e.id" class="card" @click="open(e)">
        <view class="e-head">
          <view class="e-name">{{ e.name }}</view>
          <text class="chip" :class="statusOf(e).tone">{{ statusOf(e).label }}</text>
        </view>
        <view class="e-chips">
          <text class="chip">{{ e.class_name }}</text>
          <text class="chip">{{ e.duration }} 分钟</text>
          <text class="chip">{{ e.total_score }} 分</text>
        </view>
        <view class="e-time" :class="{ over: isOver(e) }">
          {{ fmtTime(e.start_at) }} ~ {{ fmtTime(e.end_at) }}
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listExams } from '@/api/exam.js'
import { get } from '@/utils/request.js'

const rows = ref([])
const subMap = ref({})
const loading = ref(false)

onShow(load)

async function load() {
  loading.value = true
  try {
    const [ex, subs] = await Promise.all([listExams(), get('/exam-submissions/', {})])
    rows.value = ex.results ?? ex
    const map = {}
    ;(subs.results ?? subs).forEach((s) => { map[s.exam] = s })
    subMap.value = map
  } finally {
    loading.value = false
  }
}

function isOver(e) {
  return e.end_at && new Date(e.end_at).getTime() < Date.now()
}

function notStarted(e) {
  return e.start_at && new Date(e.start_at).getTime() > Date.now()
}

function statusOf(e) {
  const sub = subMap.value[e.id]
  if (!sub) {
    if (notStarted(e)) return { label: '未开始', tone: 'muted' }
    if (isOver(e)) return { label: '未参加', tone: 'muted' }
    return { label: '未参加', tone: 'warn' }
  }
  if (sub.status === 'in_progress') return { label: '继续作答', tone: 'warn' }
  if (sub.status === 'absent') return { label: '缺考', tone: 'muted' }
  if (sub.score_released) return { label: `已出分 ${sub.total_score ?? '-'} 分`, tone: 'success' }
  return { label: '已交卷，待出分', tone: '' }
}

function fmtTime(t) {
  if (!t) return '不限'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function open(e) {
  const sub = subMap.value[e.id]
  if (sub && ['submitted', 'timeout'].includes(sub.status)) {
    if (sub.score_released) {
      uni.navigateTo({ url: `/pages/exam/review?sub=${sub.id}` })
    } else {
      uni.showToast({ title: '成绩尚未发布，请等待教师统一出分', icon: 'none' })
    }
    return
  }
  if (notStarted(e)) return uni.showToast({ title: '考试尚未开始', icon: 'none' })
  if (isOver(e) && !sub) return uni.showToast({ title: '考试已结束', icon: 'none' })
  uni.showModal({
    title: '进入考试',
    content: '进入后开始计时，中途切出会被记录。确定开始吗？',
    success: (res) => {
      if (res.confirm) uni.navigateTo({ url: `/pages/exam/taking?exam=${e.id}` })
    },
  })
}
</script>

<style scoped>
.page { padding: 28rpx; }
.tip { padding: 100rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.card { margin-bottom: 20rpx; padding: 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.05); }
.card:active { transform: scale(0.98); }
.e-head { display: flex; align-items: center; justify-content: space-between; gap: 14rpx; }
.e-name { flex: 1; overflow: hidden; font-size: 30rpx; font-weight: 700; color: #0f172a; text-overflow: ellipsis; white-space: nowrap; }
.e-chips { display: flex; flex-wrap: wrap; gap: 10rpx; margin-top: 14rpx; }
.chip { padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 22rpx; }
.chip.warn { background: #fff7ed; color: #f59e0b; }
.chip.success { background: #ecfdf5; color: #10b981; }
.chip.muted { background: #f1f5f9; color: #94a3b8; }
.e-time { margin-top: 12rpx; font-size: 23rpx; color: #94a3b8; }
.e-time.over { color: #ef4444; }
</style>
