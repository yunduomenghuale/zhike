<template>
  <view class="page">
    <view class="toolbar">
      <button class="ghost-btn" :disabled="loading" @click="load">刷新</button>
      <button class="primary-btn small" @click="releaseAll">批量发布成绩</button>
    </view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!subs.length" class="tip">暂无学生参加</view>
      <view v-for="s in subs" :key="s.id" class="card">
        <view class="s-head" @click="toggle(s.id)">
          <view class="s-main">
            <text class="s-name">{{ s.student_name || `学生#${s.student}` }}</text>
            <text v-if="s.abnormal" class="chip danger">异常</text>
            <text v-if="s.score_released" class="chip success">已发布</text>
          </view>
          <text class="chip" :class="tone(s.status)">{{ s.status_display || s.status }}</text>
        </view>
        <view class="s-scores">
          <text>客观分 {{ s.objective_score ?? '-' }}</text>
          <text>总分 {{ s.total_score ?? '-' }}</text>
          <text>交卷 {{ fmtTime(s.submitted_at) }}</text>
        </view>

        <view v-if="expandedId === s.id" class="s-detail">
          <!-- 主观题批改 -->
          <template v-if="['submitted', 'timeout'].includes(s.status) && s.has_subjective">
            <view v-if="grading[s.id]?.loading" class="empty">加载答卷中…</view>
            <template v-else-if="grading[s.id]">
              <view v-for="q in grading[s.id].questions" :key="q.question_id" class="gq">
                <view class="gq-stem">第 {{ q.order + 1 }} 题（{{ q.score }} 分）：{{ q.stem }}</view>
                <view class="gq-ans">学生答案：{{ q.student_answer?.text || '（未作答）' }}</view>
                <view class="gq-ref">参考答案：{{ q.reference_answer?.text || '-' }}</view>
                <view v-if="q.analysis" class="gq-ana">解析：{{ q.analysis }}</view>
                <input
                  v-model="grading[s.id].scores[q.question_id]"
                  class="input score-input"
                  type="digit"
                  :placeholder="`得分 0~${q.score}`"
                  placeholder-class="ph"
                  :disabled="s.score_released"
                />
              </view>
              <button v-if="!s.score_released" class="primary-btn grade-btn" @click="saveGrade(s)">保存批改</button>
            </template>
          </template>
          <view v-else-if="!s.has_subjective" class="empty">纯客观题试卷，已自动评分</view>

          <button
            v-if="['submitted', 'timeout'].includes(s.status) && !s.score_released"
            class="op-btn success release-btn"
            @click="releaseOne(s)"
          >发布该生成绩</button>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import {
  monitorExam, releaseExamScores, examGradingDetail, gradeExamSubmission, releaseExamScore,
} from '@/api/exam.js'

const examId = ref(null)
const subs = ref([])
const loading = ref(false)
const expandedId = ref(null)
const grading = ref({})

onLoad((q) => {
  examId.value = Number(q.id) || null
  if (q.name) uni.setNavigationBarTitle({ title: decodeURIComponent(q.name) })
  load()
})

async function load() {
  if (!examId.value) return
  loading.value = true
  try {
    const data = await monitorExam(examId.value)
    subs.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

async function toggle(id) {
  if (expandedId.value === id) {
    expandedId.value = null
    return
  }
  expandedId.value = id
  const s = subs.value.find((x) => x.id === id)
  if (!s || grading.value[id] || !['submitted', 'timeout'].includes(s.status) || !s.has_subjective) return
  grading.value = { ...grading.value, [id]: { loading: true, questions: [], scores: {} } }
  try {
    const res = await examGradingDetail(id)
    const scores = {}
    ;(res.subjective_questions || []).forEach((q) => {
      const existing = (res.subjective_scores || {})[q.question_id]
      scores[q.question_id] = existing ?? ''
    })
    grading.value = {
      ...grading.value,
      [id]: { loading: false, questions: res.subjective_questions || [], scores },
    }
  } catch {
    grading.value = { ...grading.value, [id]: { loading: false, questions: [], scores: {} } }
  }
}

function tone(s) {
  return { in_progress: 'warn', submitted: '', timeout: '', absent: 'muted' }[s] || ''
}

function fmtTime(t) {
  if (!t) return '-'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function saveGrade(s) {
  const g = grading.value[s.id]
  if (!g) return
  const scores = {}
  for (const [qid, v] of Object.entries(g.scores)) {
    if (v !== '' && v != null) scores[qid] = Number(v)
  }
  if (!Object.keys(scores).length) return uni.showToast({ title: '请先填写得分', icon: 'none' })
  await gradeExamSubmission(s.id, { scores })
  uni.showToast({ title: '批改已保存', icon: 'success' })
  grading.value = { ...grading.value }
  delete grading.value[s.id]
  expandedId.value = null
  load()
}

function releaseOne(s) {
  uni.showModal({
    title: '发布成绩',
    content: `发布后 ${s.student_name || '该学生'} 可见分数，确定吗？`,
    success: async (res) => {
      if (!res.confirm) return
      await releaseExamScore(s.id)
      uni.showToast({ title: '已发布', icon: 'success' })
      load()
    },
  })
}

function releaseAll() {
  uni.showModal({
    title: '批量发布成绩',
    content: '将发布本场考试所有已完成批改的答卷，确定吗？',
    success: async (res) => {
      if (!res.confirm) return
      const r = await releaseExamScores(examId.value)
      uni.showToast({ title: r?.released != null ? `已发布 ${r.released} 份` : '已发布', icon: 'none' })
      load()
    },
  })
}
</script>

<style scoped>
.page { padding: 28rpx; }
.toolbar { display: flex; justify-content: space-between; gap: 14rpx; margin-bottom: 20rpx; }
.tip { padding: 80rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.card { margin-bottom: 18rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.s-head { display: flex; align-items: center; justify-content: space-between; }
.s-main { display: flex; align-items: center; gap: 12rpx; }
.s-name { font-size: 29rpx; font-weight: 700; color: #0f172a; }
.s-scores { display: flex; gap: 22rpx; margin-top: 12rpx; font-size: 23rpx; color: #64748b; }
.chip { padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 22rpx; }
.chip.warn { background: #fff7ed; color: #f59e0b; }
.chip.success { background: #ecfdf5; color: #10b981; }
.chip.danger { background: #fef2f2; color: #ef4444; }
.chip.muted { background: #f1f5f9; color: #94a3b8; }
.s-detail { margin-top: 18rpx; padding-top: 18rpx; border-top: 1rpx solid #f1f5f9; }
.empty { padding: 20rpx 0; font-size: 24rpx; color: #94a3b8; }
.gq { margin-bottom: 20rpx; }
.gq-stem { font-size: 26rpx; font-weight: 600; line-height: 1.7; color: #0f172a; }
.gq-ans { margin-top: 8rpx; font-size: 25rpx; line-height: 1.7; color: #334155; white-space: pre-wrap; }
.gq-ref { margin-top: 8rpx; font-size: 24rpx; color: #10b981; }
.gq-ana { margin-top: 6rpx; font-size: 23rpx; color: #94a3b8; }
.input { height: 72rpx; padding: 0 24rpx; border-radius: 16rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.score-input { width: 220rpx; margin-top: 12rpx; }
.ph { color: #94a3b8; }
.primary-btn { height: 80rpx; line-height: 80rpx; border-radius: 20rpx; background: #2563eb; color: #fff; font-size: 28rpx; font-weight: 600; }
.primary-btn::after { border: none; }
.primary-btn.small { width: auto; height: 64rpx; line-height: 64rpx; padding: 0 24rpx; font-size: 24rpx; }
.primary-btn.grade-btn { margin-top: 8rpx; }
.ghost-btn { height: 64rpx; line-height: 64rpx; padding: 0 28rpx; border-radius: 16rpx; background: #f1f5f9; color: #475569; font-size: 24rpx; }
.ghost-btn::after { border: none; }
.op-btn.success { background: #ecfdf5; color: #10b981; }
.release-btn { width: 100%; height: 72rpx; line-height: 72rpx; margin-top: 16rpx; border-radius: 16rpx; font-size: 26rpx; font-weight: 600; }
.release-btn::after { border: none; }
</style>
