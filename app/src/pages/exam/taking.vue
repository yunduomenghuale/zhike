<template>
  <view class="page">
    <view v-if="loading" class="tip">正在进入考试…</view>
    <template v-else-if="submission">
      <!-- 倒计时 -->
      <view class="timer-bar" :class="{ danger: remainSec <= 300 }">
        <text>⏱ 剩余 {{ remainText }}</text>
        <text class="timer-count">已答 {{ answeredCount }}/{{ questions.length }}</text>
      </view>

      <view v-for="(q, i) in questions" :key="q.question_id" class="q-card">
        <view class="q-stem">
          <text class="q-idx">{{ i + 1 }}.</text>
          <text class="chip">{{ q.qtype_display }}</text>
          <text>{{ q.stem }}</text>
          <text class="q-score">（{{ q.score }} 分）</text>
        </view>

        <!-- 单选 / 判断 -->
        <view v-if="['single', 'judge'].includes(q.qtype)" class="opts">
          <view
            v-for="opt in q.options"
            :key="opt.key"
            class="opt"
            :class="{ active: answers[q.question_id]?.key === opt.key }"
            @click="answers[q.question_id] = { key: opt.key }"
          >
            <text class="opt-key">{{ opt.key }}.</text> {{ opt.text }}
          </view>
        </view>

        <!-- 多选 -->
        <view v-else-if="q.qtype === 'multi'" class="opts">
          <view
            v-for="opt in q.options"
            :key="opt.key"
            class="opt"
            :class="{ active: answers[q.question_id]?.keys?.includes(opt.key) }"
            @click="toggleMulti(q.question_id, opt.key)"
          >
            <text class="opt-key">{{ opt.key }}.</text> {{ opt.text }}
          </view>
        </view>

        <!-- 填空（多空题按空数量渲染输入框） -->
        <template v-else-if="q.qtype === 'blank'">
          <input
            v-for="(_, blankIndex) in (answers[q.question_id]?.blanks || [''])"
            :key="blankIndex"
            class="blank-input"
            :placeholder="`第 ${blankIndex + 1} 空`"
            placeholder-class="ph"
            :value="answers[q.question_id]?.blanks?.[blankIndex] || ''"
            @input="onBlankInput(q.question_id, blankIndex, $event)"
          />
        </template>

        <!-- 简答 -->
        <textarea
          v-else
          class="textarea"
          placeholder="请作答"
          placeholder-class="ph"
          :value="answers[q.question_id]?.text || ''"
          @input="answers[q.question_id] = { text: $event.detail.value }"
        />
      </view>

      <view class="btn-row">
        <button class="save-btn" :disabled="saving" :loading="saving" @click="saveAnswers">保存答案</button>
        <button class="submit-btn" :disabled="submitting" :loading="submitting" @click="doSubmit">
          交卷（{{ answeredCount }}/{{ questions.length }}）
        </button>
      </view>
      <view class="save-hint" :class="{ dirty }">
        <text v-if="dirty">有未保存的更改，退出或刷新页面将丢失，请及时点击「保存答案」</text>
        <text v-else-if="savedAtText">已于 {{ savedAtText }} 保存（保存不提交，考试结束时将自动交卷）</text>
        <text v-else>答题过程中可随时「保存答案」暂存（不提交），到结束时间将自动交卷</text>
      </view>
    </template>
  </view>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { onHide, onLoad, onShow, onUnload } from '@dcloudio/uni-app'
import { startExam, saveExamAnswers, submitExam, reportCheat } from '@/api/exam.js'

const examId = ref(null)
const submission = ref(null)
const questions = ref([])
const answers = reactive({})
const loading = ref(true)
const submitting = ref(false)
const submitted = ref(false)
const remainSec = ref(0)
const durationMin = ref(60)
let timer = null

// ---- 保存答案（不提交）----
const saving = ref(false)
const savedAt = ref(null)
const dirty = ref(false)
const savedAtText = computed(() => {
  if (!savedAt.value) return ''
  const d = new Date(savedAt.value)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
})
// 答案有任何改动即标记未保存（保存/交卷后清除）
watch(answers, () => { dirty.value = true }, { deep: true })
let remindTimer = null
// 定时提醒保存：每 90 秒检查一次，有未保存答案时提示
function startSaveReminder() {
  remindTimer = setInterval(() => {
    if (dirty.value && !submitted.value) {
      uni.showToast({ title: '有未保存的答案，请点击「保存答案」', icon: 'none' })
    }
  }, 90 * 1000)
}

// 把已保存的作答回填到答题模型（退出重进后继续答）
function restoreAnswers(saved) {
  if (!saved) return
  questions.value.forEach((q) => {
    const a = saved[String(q.question_id)]
    if (!a) return
    if (q.qtype === 'blank') {
      const n = Math.max(1, q.blank_count || 1)
      const blanks = Array.isArray(a.blanks) ? [...a.blanks] : []
      answers[q.question_id] = { blanks: Array.from({ length: n }, (_, i) => blanks[i] ?? '') }
    } else if (q.qtype === 'multi') {
      answers[q.question_id] = { keys: Array.isArray(a.keys) ? [...a.keys] : [] }
    } else {
      answers[q.question_id] = { ...a }
    }
  })
}

async function saveAnswers() {
  if (saving.value || !submission.value) return
  saving.value = true
  try {
    const res = await saveExamAnswers(submission.value.id, { answers })
    savedAt.value = res.saved_at
    dirty.value = false
    uni.showToast({ title: `已保存（${savedAtText.value || '刚刚'}）`, icon: 'success' })
  } catch {
    // 失败原因（如已到交卷时间）由请求拦截器统一提示
  } finally {
    saving.value = false
  }
}

onLoad(async (q) => {
  examId.value = Number(q.exam) || null
  try {
    const res = await startExam(examId.value)
    submission.value = res.submission
    questions.value = res.questions || []
    // 填空题按空数量初始化作答数组（多空题渲染多个输入框）
    questions.value.forEach((q) => {
      if (q.qtype === 'blank') {
        answers[q.question_id] = { blanks: new Array(Math.max(1, q.blank_count || 1)).fill('') }
      }
    })
    // 回填已保存的答案（保存不提交，退出重进后继续作答）
    restoreAnswers(res.submission.answers)
    savedAt.value = res.submission.saved_at || null
    dirty.value = false // 回填属于已保存内容，不算未保存更改
    uni.setNavigationBarTitle({ title: '考试中' })
    // 倒计时：服务端按「开始时间 + 时长」续算剩余秒数，
    // 关闭/重开/切后台再回来都从同一截止点续算，不会重置考试时间
    durationMin.value = Number(res.duration) || 60
    const durationSec = durationMin.value * 60
    remainSec.value = Math.max(0, Math.floor(Number(res.remaining_seconds ?? durationSec)))
    if (remainSec.value <= 0) {
      uni.showToast({ title: '考试时间已到，正在自动交卷', icon: 'none' })
      setTimeout(() => autoSubmit(), 800)
      return
    }
    startTicker()
    startSaveReminder()
  } catch {
    // 后端已 toast 原因（未开始/已结束/已提交等）
    setTimeout(() => uni.navigateBack(), 1500)
  } finally {
    loading.value = false
  }
})

// 从后台恢复：按服务端开始时间重新校准剩余时间（避免后台计时被系统节流）
onShow(() => {
  if (!submission.value || submitted.value || submitting.value) return
  const startedAt = submission.value.started_at
  if (!startedAt) return
  const endTs = new Date(startedAt).getTime() + durationMin.value * 60000
  remainSec.value = Math.max(0, Math.floor((endTs - Date.now()) / 1000))
  if (remainSec.value <= 0 && !timer) autoSubmit()
})

function startTicker() {
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    remainSec.value -= 1
    if (remainSec.value <= 0) {
      clearInterval(timer)
      timer = null
      autoSubmit()
    }
  }, 1000)
}

const remainText = computed(() => {
  const s = Math.max(0, remainSec.value)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = String(s % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`
})

const answeredCount = computed(() => questions.value.filter((q) => {
  const a = answers[q.question_id] || {}
  if (q.qtype === 'multi') return Boolean(a.keys?.length)
  if (q.qtype === 'blank') return Boolean(a.blanks?.some((x) => String(x).trim()))
  if (q.qtype === 'short') return Boolean(String(a.text || '').trim())
  return Boolean(String(a.key || '').trim())
}).length)

function toggleMulti(qid, key) {
  const a = answers[qid] || { keys: [] }
  const keys = (a.keys || []).includes(key)
    ? a.keys.filter((k) => k !== key)
    : [...(a.keys || []), key]
  answers[qid] = { keys }
}

// 多空填空：按空数量维护数组，逐空写入
function onBlankInput(qid, index, e) {
  const cur = answers[qid]?.blanks ? [...answers[qid].blanks] : []
  cur[index] = e.detail.value
  answers[qid] = { blanks: cur }
}

async function doSubmit() {
  if (submitting.value || submitted.value) return
  uni.showModal({
    title: '交卷',
    content: answeredCount.value < questions.value.length
      ? `还有 ${questions.value.length - answeredCount.value} 道题未作答，确定交卷吗？`
      : '确定交卷吗？',
    success: async (res) => {
      if (!res.confirm) return
      await finalize()
    },
  })
}

async function autoSubmit() {
  uni.showToast({ title: '时间到，自动交卷', icon: 'none' })
  await finalize()
}

async function finalize() {
  if (submitting.value || submitted.value) return
  submitting.value = true
  try {
    await submitExam(submission.value.id, { answers })
    submitted.value = true
    dirty.value = false
    uni.showToast({ title: '交卷成功', icon: 'success' })
    setTimeout(() => uni.navigateBack(), 800)
  } finally {
    submitting.value = false
  }
}

onHide(() => {
  // 防作弊：考试中切出页面上报日志
  if (submission.value && !submitted.value) {
    reportCheat({ exam: examId.value, action: 'blur', note: '切出考试页面' }).catch(() => {})
    // 退出前提醒保存：有未保存答案时 toast 提示，重进后可继续作答
    if (dirty.value) {
      uni.showToast({ title: '有未保存的答案，重进后请及时保存', icon: 'none' })
    }
  }
})

onUnload(() => {
  if (timer) clearInterval(timer)
  if (remindTimer) clearInterval(remindTimer)
})
</script>

<style scoped>
.page { padding: 28rpx; }
.tip { padding: 100rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.timer-bar { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; padding: 20rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; font-size: 28rpx; font-weight: 700; color: #2563eb; box-shadow: 0 2rpx 8rpx rgba(15,23,42,0.06); }
.timer-bar.danger { color: #ef4444; }
.timer-count { font-size: 24rpx; font-weight: 600; color: #94a3b8; }
.q-card { margin-bottom: 18rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.q-stem { font-size: 27rpx; line-height: 1.8; color: #0f172a; }
.q-idx { margin-right: 8rpx; font-weight: 700; }
.chip { margin-right: 10rpx; padding: 2rpx 14rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 20rpx; }
.q-score { font-size: 22rpx; color: #94a3b8; }
.opts { margin-top: 18rpx; }
.opt { margin-bottom: 14rpx; padding: 18rpx 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; color: #334155; }
.opt.active { background: #eff6ff; border-color: #2563eb; color: #2563eb; }
.opt-key { font-weight: 700; }
.blank-input { height: 76rpx; margin-top: 18rpx; padding: 0 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.textarea { width: 100%; min-height: 180rpx; margin-top: 18rpx; padding: 20rpx 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.ph { color: #94a3b8; }
.submit-btn { margin-top: 12rpx; height: 92rpx; line-height: 92rpx; border-radius: 24rpx; background: #2563eb; color: #fff; font-size: 30rpx; font-weight: 600; }
.submit-btn::after { border: none; }
.btn-row { display: flex; gap: 18rpx; margin-top: 16rpx; }
.btn-row .submit-btn { flex: 1; margin-top: 0; }
.save-btn { flex: 1; height: 92rpx; line-height: 92rpx; border-radius: 24rpx; background: #fff; border: 2rpx solid #2563eb; color: #2563eb; font-size: 30rpx; font-weight: 600; }
.save-btn::after { border: none; }
.save-hint { margin: 16rpx 0 24rpx; text-align: center; font-size: 22rpx; line-height: 1.6; color: #94a3b8; }
.save-hint.dirty { color: #d97706; font-weight: 600; }
</style>
