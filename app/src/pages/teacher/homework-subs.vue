<template>
  <view class="page">
    <view class="toolbar">
      <view class="page-title">{{ title }}</view>
      <button class="primary-btn small" @click="releaseAll">批量发布成绩</button>
    </view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!subs.length" class="tip">暂无学生提交</view>
      <view v-for="s in subs" :key="s.id" class="card">
        <view class="s-head" @click="toggle(s.id)">
          <view class="s-main">
            <text class="s-name">{{ s.student_name || `学生#${s.student}` }}</text>
            <text v-if="s.is_late" class="chip danger">逾期</text>
          </view>
          <text class="chip" :class="tone(s.correct_status)">{{ statusLabel(s) }}</text>
        </view>
        <view class="s-time">提交：{{ fmtTime(s.submitted_at) }}</view>

        <view v-if="expandedId === s.id" class="s-detail">
          <!-- 作答内容 -->
          <template v-if="hw?.mode === 'questions'">
            <view v-for="(a, i) in s.answer_items || []" :key="a.id" class="qa-item">
              <view class="qa-stem">{{ i + 1 }}. {{ a.snapshot?.stem }}</view>
              <view class="qa-ans">学生答案：{{ fmtAns(a.student_answer) }}</view>
              <view v-if="a.is_correct !== null && a.is_correct !== undefined" class="qa-judge" :class="a.is_correct ? 'ok' : 'no'">
                {{ a.is_correct ? '✓ 正确' : '✗ 错误' }}<text v-if="a.score != null">（{{ a.score }} 分）</text>
              </view>
              <!-- 简答题打分 -->
              <view v-if="a.needs_manual_grading" class="grade-row">
                <input
                  v-model="gradeForms[s.id].answer_scores[a.id].score"
                  class="input score-input"
                  type="digit"
                  placeholder="得分"
                  placeholder-class="ph"
                  :disabled="s.correct_status === 'returned'"
                />
                <input
                  v-model="gradeForms[s.id].answer_scores[a.id].comment"
                  class="input comment-input"
                  placeholder="评语（可空）"
                  placeholder-class="ph"
                  :disabled="s.correct_status === 'returned'"
                />
              </view>
            </view>
          </template>
          <template v-else>
            <view v-if="s.content" class="s-content">{{ s.content }}</view>
            <view v-if="s.attachment" class="attach" @click="copyLink(s.attachment)">
              📎 {{ fileName(s.attachment) }}（点击复制链接）
            </view>
            <view class="grade-row">
              <input
                v-model="gradeForms[s.id].score"
                class="input score-input"
                type="digit"
                :placeholder="`得分（0~${hw?.total_score ?? 100}）`"
                placeholder-class="ph"
                :disabled="s.correct_status === 'returned'"
              />
            </view>
          </template>

          <textarea
            v-model="gradeForms[s.id].comment"
            class="textarea"
            placeholder="总评语（可空）"
            placeholder-class="ph"
            :disabled="s.correct_status === 'returned'"
          />

          <view v-if="s.correct_status !== 'returned'" class="ops">
            <button class="op-btn primary" :disabled="gradingId === s.id" @click="doGrade(s)">
              {{ gradingId === s.id ? '提交中…' : '保存批改' }}
            </button>
            <button v-if="s.correct_status === 'graded'" class="op-btn success" @click="doRelease(s)">发布成绩</button>
          </view>
          <view v-else class="released">成绩已发布：{{ s.score }} 分{{ s.comment ? ` · ${s.comment}` : '' }}</view>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { get } from '@/utils/request.js'
import { listSubmissions, gradeSubmission, releaseSubmission, releaseAllSubmissions } from '@/api/homework.js'
import { mediaURL } from '@/config.js'

const hwId = ref(null)
const title = ref('作业提交')
const hw = ref(null)
const subs = ref([])
const loading = ref(false)
const expandedId = ref(null)
const gradeForms = ref({})
const gradingId = ref(null)

onLoad((q) => {
  hwId.value = Number(q.id) || null
  if (q.title) {
    title.value = decodeURIComponent(q.title)
    uni.setNavigationBarTitle({ title: title.value })
  }
  load()
})

async function load() {
  if (!hwId.value) return
  loading.value = true
  try {
    const [detail, data] = await Promise.all([
      get(`/homeworks/${hwId.value}/`),
      listSubmissions({ homework: hwId.value }),
    ])
    hw.value = detail
    subs.value = data.results ?? data
    const forms = {}
    subs.value.forEach((s) => {
      const answerScores = {}
      ;(s.answer_items || []).forEach((a) => {
        if (a.needs_manual_grading) {
          answerScores[a.id] = { score: a.score ?? '', comment: a.comment || '' }
        }
      })
      forms[s.id] = { score: s.score ?? '', comment: s.comment || '', answer_scores: answerScores }
    })
    gradeForms.value = forms
  } finally {
    loading.value = false
  }
}

function toggle(id) {
  expandedId.value = expandedId.value === id ? null : id
}

function statusLabel(s) {
  if (s.correct_status === 'submitted') return '待批改'
  if (s.correct_status === 'graded') return '已批改'
  return `已发布 ${s.score ?? '-'} 分`
}

function tone(status) {
  return { submitted: 'warn', graded: '', returned: 'success' }[status] || ''
}

function fmtAns(a) {
  if (!a) return '（未作答）'
  if (a.key != null) return String(a.key)
  if (a.keys) return a.keys.join('、')
  if (a.blanks) return a.blanks.join(' / ')
  if (a.text != null) return String(a.text)
  return JSON.stringify(a)
}

function fmtTime(t) {
  if (!t) return '-'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fileName(url) {
  const raw = String(url).split('/').pop()?.split('?')[0] || '附件'
  try { return decodeURIComponent(raw) } catch { return raw }
}

function copyLink(url) {
  uni.setClipboardData({ data: mediaURL(url), success: () => uni.showToast({ title: '链接已复制', icon: 'none' }) })
}

async function doGrade(s) {
  const f = gradeForms.value[s.id]
  gradingId.value = s.id
  try {
    if (hw.value?.mode === 'questions') {
      await gradeSubmission(s.id, { answer_scores: f.answer_scores, comment: f.comment })
    } else {
      if (f.score === '' || f.score === null) {
        uni.showToast({ title: '请输入分数', icon: 'none' })
        return
      }
      await gradeSubmission(s.id, { score: f.score, comment: f.comment })
    }
    uni.showToast({ title: '批改完成', icon: 'success' })
    await load()
  } finally {
    gradingId.value = null
  }
}

function doRelease(s) {
  uni.showModal({
    title: '发布成绩',
    content: `发布后 ${s.student_name || '该学生'} 可见分数与评语，确定吗？`,
    success: async (res) => {
      if (!res.confirm) return
      await releaseSubmission(s.id)
      uni.showToast({ title: '已发布', icon: 'success' })
      load()
    },
  })
}

function releaseAll() {
  uni.showModal({
    title: '批量发布成绩',
    content: '将发布本作业所有已批改的提交，确定吗？',
    success: async (res) => {
      if (!res.confirm) return
      const r = await releaseAllSubmissions(hwId.value)
      uni.showToast({ title: `已发布 ${r.released} 份`, icon: 'none' })
      load()
    },
  })
}
</script>

<style scoped>
.page { padding: 28rpx; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; margin-bottom: 20rpx; }
.page-title { flex: 1; overflow: hidden; font-size: 30rpx; font-weight: 800; color: #0f172a; text-overflow: ellipsis; white-space: nowrap; }
.tip { padding: 80rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.card { margin-bottom: 18rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.s-head { display: flex; align-items: center; justify-content: space-between; }
.s-main { display: flex; align-items: center; gap: 12rpx; }
.s-name { font-size: 29rpx; font-weight: 700; color: #0f172a; }
.s-time { margin-top: 10rpx; font-size: 22rpx; color: #94a3b8; }
.chip { padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 22rpx; }
.chip.warn { background: #fff7ed; color: #f59e0b; }
.chip.success { background: #ecfdf5; color: #10b981; }
.chip.danger { background: #fef2f2; color: #ef4444; }
.s-detail { margin-top: 18rpx; padding-top: 18rpx; border-top: 1rpx solid #f1f5f9; }
.qa-item { margin-bottom: 18rpx; }
.qa-stem { font-size: 26rpx; line-height: 1.7; color: #0f172a; }
.qa-ans { margin-top: 8rpx; font-size: 25rpx; color: #475569; }
.qa-judge { margin-top: 6rpx; font-size: 24rpx; }
.qa-judge.ok { color: #10b981; }
.qa-judge.no { color: #ef4444; }
.s-content { font-size: 26rpx; line-height: 1.8; color: #334155; white-space: pre-wrap; }
.attach { margin-top: 12rpx; font-size: 24rpx; color: #2563eb; }
.grade-row { display: flex; gap: 14rpx; margin-top: 14rpx; }
.input { height: 72rpx; padding: 0 24rpx; border-radius: 16rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.score-input { width: 180rpx; flex-shrink: 0; }
.comment-input { flex: 1; }
.textarea { width: 100%; min-height: 110rpx; margin-top: 14rpx; padding: 16rpx 24rpx; border-radius: 16rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.ph { color: #94a3b8; }
.ops { display: flex; gap: 14rpx; margin-top: 16rpx; }
.op-btn { flex: 1; height: 72rpx; line-height: 72rpx; border-radius: 16rpx; font-size: 26rpx; font-weight: 600; }
.op-btn::after { border: none; }
.op-btn.primary { background: #2563eb; color: #fff; }
.op-btn.success { background: #ecfdf5; color: #10b981; }
.released { margin-top: 14rpx; padding: 16rpx 20rpx; border-radius: 14rpx; background: #ecfdf5; font-size: 24rpx; color: #10b981; }
.primary-btn { height: 80rpx; line-height: 80rpx; border-radius: 20rpx; background: #2563eb; color: #fff; font-size: 28rpx; font-weight: 600; }
.primary-btn::after { border: none; }
.primary-btn.small { width: auto; height: 64rpx; line-height: 64rpx; padding: 0 24rpx; font-size: 24rpx; flex-shrink: 0; }
</style>
