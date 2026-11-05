<template>
  <view class="page">
    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">暂无实验成绩</view>
      <view v-for="row in rows" :key="row.id" class="card">
        <view class="card-head">
          <view class="lab-title">{{ row.lab_title }}</view>
          <view class="score" :class="scoreClass(row)">
            {{ row.total_score != null ? `${row.total_score} 分` : statusText(row.status) }}
          </view>
        </view>
        <view class="meta">
          <text class="chip">{{ row.course_name }}</text>
          <text v-if="row.submitted_at" class="date">{{ fmtDate(row.submitted_at) }} 提交</text>
          <text v-if="row.reviewed" class="reviewed">教师已复核</text>
        </view>
        <view v-if="row.total_score != null" class="detail">
          <view class="detail-row">
            <text>基础分</text><text>{{ isExternal(row) ? '不适用' : (row.base_score ?? '—') }}</text>
          </view>
          <view class="detail-row">
            <text>完成效率</text><text>{{ isExternal(row) ? '不适用' : (row.efficiency_score ?? '—') }}</text>
          </view>
          <view class="detail-row">
            <text>实验用时</text><text>{{ fmtElapsed(row.elapsed_seconds) }}</text>
          </view>
          <view class="detail-row total">
            <text>总分</text><text>{{ row.total_score }} / {{ row.lab_total_score || 100 }}</text>
          </view>
        </view>
        <view v-if="row.status === 'in_progress'" class="hint">实验进行中，请在电脑端完成并提交</view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listLabSubmissions } from '@/api/lab.js'

const rows = ref([])
const loading = ref(false)

onShow(load)

async function load() {
  loading.value = true
  try {
    const res = await listLabSubmissions()
    rows.value = res.results ?? res ?? []
  } finally {
    loading.value = false
  }
}

function statusText(s) {
  return { in_progress: '进行中', submitted: '已提交' }[s] || s
}

function scoreClass(row) {
  if (row.total_score == null) return 'pending'
  return row.total_score >= 60 ? 'pass' : 'fail'
}

// C6 / C17：question_score 幽灵字段已随 LabQuestion 删除；自定义实验无步骤分项，
// 只展示总分与服务端用时，四项基准分标注「不适用」。
function isExternal(row) {
  return row.grading_source === 'external' || row.score_breakdown?.source === 'external'
}

function fmtElapsed(sec) {
  const n = Number(sec || 0)
  if (!Number.isFinite(n) || n <= 0) return '0 秒'
  const m = Math.floor(n / 60)
  const s = Math.round(n % 60)
  return m ? `${m} 分 ${s} 秒` : `${s} 秒`
}

function fmtDate(s) {
  if (!s) return ''
  const d = new Date(s)
  return `${d.getMonth() + 1}/${d.getDate()}`
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

.card {
  margin-bottom: 20rpx;
  padding: 26rpx 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.04);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}

.lab-title {
  flex: 1;
  font-size: 30rpx;
  font-weight: 700;
  color: #0f172a;
}

.score {
  font-size: 30rpx;
  font-weight: 800;
}

.score.pass {
  color: #16a34a;
}

.score.fail {
  color: #dc2626;
}

.score.pending {
  color: #94a3b8;
  font-size: 26rpx;
}

.meta {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-top: 12rpx;
  font-size: 22rpx;
  color: #94a3b8;
}

.chip {
  padding: 2rpx 14rpx;
  border-radius: 8rpx;
  background: #eff6ff;
  color: #2563eb;
}

.reviewed {
  color: #16a34a;
}

.detail {
  margin-top: 18rpx;
  padding-top: 16rpx;
  border-top: 1rpx solid #f1f5f9;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 6rpx 0;
  font-size: 24rpx;
  color: #64748b;
}

.detail-row.total {
  font-weight: 700;
  color: #0f172a;
  font-size: 26rpx;
}

.hint {
  margin-top: 14rpx;
  font-size: 22rpx;
  color: #f59e0b;
}
</style>
