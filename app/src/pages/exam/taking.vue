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

        <!-- 填空 -->
        <input
          v-else-if="q.qtype === 'blank'"
          class="blank-input"
          placeholder="请输入答案"
          placeholder-class="ph"
          :value="answers[q.question_id]?.blanks?.[0] || ''"
          @input="answers[q.question_id] = { blanks: [$event.detail.value] }"
        />

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

      <button class="submit-btn" :disabled="submitting" :loading="submitting" @click="doSubmit">
        交卷（{{ answeredCount }}/{{ questions.length }}）
      </button>
    </template>
  </view>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { onHide, onLoad, onUnload } from '@dcloudio/uni-app'
import { startExam, submitExam, reportCheat } from '@/api/exam.js'

const examId = ref(null)
const submission = ref(null)
const questions = ref([])
const answers = reactive({})
const loading = ref(true)
const submitting = ref(false)
const submitted = ref(false)
const remainSec = ref(0)
let timer = null

onLoad(async (q) => {
  examId.value = Number(q.exam) || null
  try {
    const res = await startExam(examId.value)
    submission.value = res.submission
    questions.value = res.questions || []
    uni.setNavigationBarTitle({ title: '考试中' })
    // 倒计时：开始时间 + 时长
    const endTs = new Date(res.submission.started_at).getTime() + (res.duration || 60) * 60000
    remainSec.value = Math.max(0, Math.floor((endTs - Date.now()) / 1000))
    timer = setInterval(() => {
      remainSec.value -= 1
      if (remainSec.value <= 0) {
        clearInterval(timer)
        timer = null
        autoSubmit()
      }
    }, 1000)
  } catch {
    // 后端已 toast 原因（未开始/已结束/已提交等）
    setTimeout(() => uni.navigateBack(), 1500)
  } finally {
    loading.value = false
  }
})

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
  }
})

onUnload(() => {
  if (timer) clearInterval(timer)
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
</style>
