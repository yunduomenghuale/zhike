<template>
  <view class="page">
    <view v-if="loading" class="tip">加载中…</view>
    <template v-else-if="data">
      <!-- 成绩卡 -->
      <view class="score-card">
        <view class="score-num">{{ data.submission?.total_score ?? '-' }}</view>
        <view class="score-label">总分（客观题 {{ data.submission?.objective_score ?? '-' }} 分）</view>
        <view class="score-time">交卷：{{ fmtTime(data.submission?.submitted_at) }}</view>
      </view>

      <view v-for="(q, i) in data.questions" :key="q.question_id" class="q-card">
        <view class="q-stem">
          <text class="q-idx">{{ i + 1 }}.</text>
          <text class="chip">{{ q.qtype_display }}</text>
          <text>{{ q.stem }}</text>
          <text class="q-score">（{{ q.score }} 分）</text>
        </view>

        <view v-if="q.options?.length" class="opts">
          <view
            v-for="opt in q.options"
            :key="opt.key"
            class="opt"
            :class="optClass(q, opt.key)"
          >
            <text class="opt-key">{{ opt.key }}.</text> {{ opt.text }}
          </view>
        </view>

        <view class="ans wrong">我的答案：{{ fmt(q.student_answer) }}</view>
        <view class="ans right">正确答案：{{ fmt(q.correct_answer) }}</view>
        <view v-if="!q.is_objective" class="ans">
          本题得分：{{ data.submission?.subjective_scores?.[q.question_id] ?? '待批' }} 分
        </view>
        <view v-if="q.analysis" class="analysis">解析：{{ q.analysis }}</view>
      </view>
    </template>
    <view v-else class="tip">
      <view>成绩尚未发布或考试未结束</view>
      <button class="back-btn" @click="goBack">返回</button>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { reviewExam } from '@/api/exam.js'

const data = ref(null)
const loading = ref(true)

onLoad(async (q) => {
  try {
    data.value = await reviewExam(Number(q.sub))
  } catch {
    // 后端已 toast 原因
    data.value = null
  } finally {
    loading.value = false
  }
})

function goBack() {
  uni.navigateBack()
}

function fmt(a) {
  if (!a) return '（未作答）'
  if (a.key != null) return String(a.key)
  if (a.keys) return a.keys.join('、')
  if (a.blanks) return a.blanks.join(' / ')
  if (a.text != null) return String(a.text)
  return JSON.stringify(a)
}

function isCorrectOption(q, key) {
  const c = q.correct_answer || {}
  return c.key === key || (c.keys || []).includes(key)
}

function isMyOption(q, key) {
  const m = q.student_answer || {}
  return m.key === key || (m.keys || []).includes(key)
}

function optClass(q, key) {
  if (isCorrectOption(q, key)) return 'opt-right'
  if (isMyOption(q, key)) return 'opt-wrong'
  return ''
}

function fmtTime(t) {
  if (!t) return '-'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style scoped>
.page { padding: 28rpx; }
.tip { padding: 100rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.back-btn { margin-top: 24rpx; width: 220rpx; height: 72rpx; line-height: 72rpx; border-radius: 20rpx; background: #2563eb; color: #fff; font-size: 26rpx; }
.back-btn::after { border: none; }
.score-card { margin-bottom: 22rpx; padding: 40rpx; border-radius: 20rpx; background: #ecfdf5; border: 1rpx solid #d1fae5; text-align: center; }
.score-num { font-size: 56rpx; font-weight: 800; color: #10b981; }
.score-label { margin-top: 8rpx; font-size: 24rpx; color: #475569; }
.score-time { margin-top: 8rpx; font-size: 22rpx; color: #94a3b8; }
.q-card { margin-bottom: 18rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.q-stem { font-size: 27rpx; line-height: 1.8; color: #0f172a; }
.q-idx { margin-right: 8rpx; font-weight: 700; }
.chip { margin-right: 10rpx; padding: 2rpx 14rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 20rpx; }
.q-score { font-size: 22rpx; color: #94a3b8; }
.opts { margin-top: 16rpx; }
.opt { margin-bottom: 12rpx; padding: 16rpx 22rpx; border-radius: 16rpx; background: #f8fafc; font-size: 25rpx; color: #334155; }
.opt.opt-right { background: #ecfdf5; color: #10b981; }
.opt.opt-wrong { background: #fef2f2; color: #ef4444; }
.opt-key { font-weight: 700; }
.ans { margin-top: 10rpx; font-size: 25rpx; line-height: 1.7; color: #475569; }
.ans.wrong { color: #ef4444; }
.ans.right { color: #10b981; }
.analysis { margin-top: 10rpx; font-size: 24rpx; line-height: 1.7; color: #64748b; }
</style>
