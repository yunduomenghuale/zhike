<template>
  <view class="page">
    <view v-if="loading" class="tip">加载中…</view>
    <template v-else-if="detail">
      <!-- 头部 -->
      <view class="card head">
        <view class="h-name">{{ detail.student?.name }}</view>
        <view class="h-sub">@{{ detail.student?.username }} · {{ detail.class_name }} · {{ detail.course_name }}</view>
        <view class="h-sub">入班：{{ fmtDate(detail.student?.joined_at) }}</view>
      </view>

      <!-- 概览 -->
      <view class="summary">
        <view class="sum-item">
          <view class="sum-num">{{ pct(detail.summary?.accuracy) }}</view>
          <view class="sum-label">练习正确率</view>
        </view>
        <view class="sum-item">
          <view class="sum-num">{{ detail.summary?.homework_submitted ?? 0 }}/{{ detail.summary?.homework_total ?? 0 }}</view>
          <view class="sum-label">作业提交</view>
        </view>
        <view class="sum-item">
          <view class="sum-num">{{ detail.summary?.exam_taken ?? 0 }}/{{ detail.summary?.exam_total ?? 0 }}</view>
          <view class="sum-label">考试</view>
        </view>
        <view class="sum-item">
          <view class="sum-num">{{ detail.summary?.avg_exam_score ?? '-' }}</view>
          <view class="sum-label">考试均分</view>
        </view>
      </view>

      <!-- 章节练习覆盖 -->
      <view class="card">
        <view class="card-title">章节练习覆盖（{{ detail.progress?.percent ?? 0 }}%）</view>
        <view v-if="!detail.progress?.chapters?.length" class="empty">暂无章节数据</view>
        <view v-for="c in detail.progress?.chapters || []" :key="c.catalog_id" class="ch-row">
          <view class="ch-head">
            <text class="ch-title">{{ c.title || `章节 ${c.catalog_id}` }}</text>
            <text class="ch-meta">{{ c.questions_practiced }}/{{ c.questions_total }} 题</text>
          </view>
          <view class="track"><view class="fill" :style="{ width: (c.coverage ?? 0) + '%' }"></view></view>
          <view class="ch-meta sub">覆盖率 {{ pct(c.coverage) }} · 正确率 {{ pct(c.accuracy) }}</view>
        </view>
      </view>

      <!-- 作业明细 -->
      <view class="card">
        <view class="card-title">作业</view>
        <view v-if="!detail.homeworks?.length" class="empty">暂无作业</view>
        <view v-for="h in detail.homeworks" :key="h.id" class="line-row">
          <view class="line-main">
            <text class="line-title">{{ h.title }}</text>
            <text class="line-sub">截止 {{ fmtTime(h.deadline) }}</text>
          </view>
          <text v-if="h.submitted" class="chip success">{{ h.score != null ? `${h.score} 分` : (h.correct_status || '已提交') }}</text>
          <text v-else class="chip danger">未提交</text>
          <text v-if="h.is_late" class="chip warn">逾期</text>
        </view>
      </view>

      <!-- 考试明细 -->
      <view class="card">
        <view class="card-title">考试</view>
        <view v-if="!detail.exams?.length" class="empty">暂无考试</view>
        <view v-for="e in detail.exams" :key="e.id" class="line-row">
          <view class="line-main">
            <text class="line-title">{{ e.name }}</text>
            <text class="line-sub">{{ fmtTime(e.submitted_at) }}</text>
          </view>
          <text v-if="e.taken" class="chip success">{{ e.score != null ? `${e.score} 分` : '已参加' }}</text>
          <text v-else class="chip">未参加</text>
        </view>
      </view>

      <!-- 最近答题 -->
      <view class="card">
        <view class="card-title">最近答题</view>
        <view v-if="!detail.recent_records?.length" class="empty">暂无记录</view>
        <view v-for="(r, i) in (detail.recent_records || []).slice(0, 10)" :key="i" class="line-row">
          <view class="line-main">
            <text class="line-title">{{ r.stem }}</text>
            <text class="line-sub">{{ r.qtype }} · {{ fmtTime(r.submitted_at) }}</text>
          </view>
          <text class="chip" :class="r.is_correct ? 'success' : 'danger'">{{ r.is_correct ? '正确' : '错误' }}</text>
        </view>
      </view>
    </template>
    <view v-else class="tip">加载失败</view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { getClassStudentDetail } from '@/api/analytics.js'

const detail = ref(null)
const loading = ref(false)

onLoad(async (q) => {
  if (q.name) uni.setNavigationBarTitle({ title: decodeURIComponent(q.name) })
  loading.value = true
  try {
    detail.value = await getClassStudentDetail(Number(q.class), Number(q.student), { course: Number(q.course) })
  } finally {
    loading.value = false
  }
})

function pct(v) {
  return v == null ? '-' : `${v}%`
}

function fmtDate(t) {
  if (!t) return '-'
  const d = new Date(t)
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}

function fmtTime(t) {
  if (!t) return '-'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style scoped>
.page { padding: 28rpx; }
.tip { padding: 80rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.card { margin-bottom: 20rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.head .h-name { font-size: 34rpx; font-weight: 800; color: #0f172a; }
.h-sub { margin-top: 8rpx; font-size: 23rpx; color: #94a3b8; }
.card-title { font-size: 28rpx; font-weight: 700; color: #0f172a; margin-bottom: 14rpx; }
.summary { display: flex; gap: 14rpx; margin-bottom: 20rpx; }
.sum-item { flex: 1; padding: 24rpx 8rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; text-align: center; }
.sum-num { font-size: 32rpx; font-weight: 800; color: #2563eb; }
.sum-label { margin-top: 6rpx; font-size: 21rpx; color: #94a3b8; }
.empty { padding: 24rpx 0; font-size: 24rpx; color: #94a3b8; }
.ch-row { margin-bottom: 18rpx; }
.ch-head { display: flex; align-items: center; justify-content: space-between; }
.ch-title { flex: 1; overflow: hidden; font-size: 26rpx; font-weight: 600; color: #334155; text-overflow: ellipsis; white-space: nowrap; }
.ch-meta { font-size: 22rpx; color: #94a3b8; }
.ch-meta.sub { margin-top: 6rpx; }
.track { height: 10rpx; margin-top: 8rpx; overflow: hidden; border-radius: 999rpx; background: #f1f5f9; }
.fill { height: 100%; border-radius: 999rpx; background: #2563eb; }
.line-row { display: flex; align-items: center; gap: 12rpx; padding: 14rpx 0; border-bottom: 1rpx solid #f8fafc; }
.line-row:last-child { border-bottom: none; }
.line-main { flex: 1; min-width: 0; }
.line-title { display: block; overflow: hidden; font-size: 26rpx; color: #334155; text-overflow: ellipsis; white-space: nowrap; }
.line-sub { font-size: 22rpx; color: #94a3b8; }
.chip { flex-shrink: 0; padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 22rpx; }
.chip.success { background: #ecfdf5; color: #10b981; }
.chip.warn { background: #fff7ed; color: #f59e0b; }
.chip.danger { background: #fef2f2; color: #ef4444; }
</style>
