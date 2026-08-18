<template>
  <view class="page">
    <view v-if="loading" class="tip">正在加载题目…</view>
    <view v-else-if="!questions.length" class="tip">本章还没有已发布的练习题</view>
    <template v-else>
      <view v-if="submitted" class="result-card">
        <view class="result-num">{{ result.correct }} / {{ result.total }}</view>
        <view class="result-label">答对题数</view>
      </view>

      <view v-for="(q, i) in questions" :key="q.id" class="q-card">
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
            :class="{ active: answers[q.id] === opt.key }"
            @click="!submitted && (answers[q.id] = opt.key)"
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
            :class="{ active: answers[q.id]?.includes(opt.key) }"
            @click="!submitted && toggleMulti(q.id, opt.key)"
          >
            <text class="opt-key">{{ opt.key }}.</text> {{ opt.text }}
          </view>
        </view>

        <!-- 填空 -->
        <input
          v-else-if="q.qtype === 'blank'"
          v-model="answers[q.id][0]"
          class="blank-input"
          placeholder="请输入答案"
          placeholder-class="ph"
          :disabled="submitted"
        />

        <!-- 简答 -->
        <textarea
          v-else
          v-model="answers[q.id]"
          class="textarea"
          placeholder="请作答"
          placeholder-class="ph"
          :disabled="submitted"
        />

        <!-- 提交后反馈 -->
        <view
          v-if="submitted && feedback[q.id]"
          class="fb"
          :class="feedback[q.id].is_correct === null ? '' : feedback[q.id].is_correct ? 'ok' : 'no'"
        >
          <template v-if="feedback[q.id].is_correct === null">
            <view>本题为简答题，请参考答案自行核对：</view>
            <view class="fb-ana">参考答案：{{ fmt(feedback[q.id].correct_answer) }}</view>
          </template>
          <template v-else>
            <view>
              {{ feedback[q.id].is_correct ? '回答正确' : `回答错误，正确答案：${fmt(feedback[q.id].correct_answer)}` }}
            </view>
          </template>
          <view v-if="feedback[q.id].analysis" class="fb-ana">解析：{{ feedback[q.id].analysis }}</view>
        </view>
      </view>

      <template v-if="isStudent">
        <button
          v-if="!submitted"
          class="submit-btn"
          :disabled="submitting"
          :loading="submitting"
          @click="submitPractice"
        >
          提交练习（{{ answeredCount }}/{{ questions.length }}）
        </button>
        <button v-else class="reset-btn" @click="resetPractice">重新作答</button>
      </template>
      <view v-else class="tip">当前账号仅供预览，学生账号可提交练习</view>
    </template>
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { listQuestions, practiceSubmit } from '@/api/question.js'

const courseId = ref(null)
const catalogId = ref(null)
const questions = ref([])
const answers = ref({})
const feedback = ref({})
const submitted = ref(false)
const submitting = ref(false)
const loading = ref(false)
const result = ref({ total: 0, correct: 0 })

// 练习提交仅学生可用（IsStudent），教师等角色只读预览
const isStudent = uni.getStorageSync('user')?.role === 'student'

onLoad((q) => {
  courseId.value = Number(q.course) || null
  catalogId.value = Number(q.catalog) || null
  if (q.title) uni.setNavigationBarTitle({ title: `练习 · ${decodeURIComponent(q.title)}` })
  loadPractice()
})

async function loadPractice() {
  if (!courseId.value || !catalogId.value) return
  loading.value = true
  try {
    const data = await listQuestions({
      course: courseId.value,
      catalog: catalogId.value,
      status: 'published',
    })
    questions.value = data.results ?? data
    resetAnswers()
  } finally {
    loading.value = false
  }
}

function resetAnswers() {
  const init = {}
  questions.value.forEach((q) => {
    init[q.id] = q.qtype === 'multi' ? [] : q.qtype === 'blank' ? [''] : ''
  })
  answers.value = init
  feedback.value = {}
  submitted.value = false
}

function resetPractice() {
  resetAnswers()
}

function toggleMulti(id, key) {
  const cur = answers.value[id] || []
  answers.value = {
    ...answers.value,
    [id]: cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key],
  }
}

function buildAns(q) {
  const v = answers.value[q.id]
  if (q.qtype === 'multi') return { keys: v }
  if (q.qtype === 'blank') return { blanks: v }
  if (q.qtype === 'short') return { text: v }
  return { key: v }
}

function fmt(a) {
  if (!a) return '-'
  if (a.key) return a.key
  if (a.keys) return a.keys.join(', ')
  if (a.blanks) return a.blanks.join(' / ')
  if (a.text) return a.text
  return '-'
}

const answeredCount = computed(() => questions.value.filter((q) => {
  const v = answers.value[q.id]
  if (q.qtype === 'multi') return Array.isArray(v) && v.length > 0
  if (q.qtype === 'blank') return Array.isArray(v) && v.some((x) => String(x).trim())
  return String(v ?? '').trim() !== ''
}).length)

async function submitPractice() {
  const payload = {}
  questions.value.forEach((q) => { payload[q.id] = buildAns(q) })
  submitting.value = true
  try {
    const res = await practiceSubmit({ answers: payload })
    const map = {}
    ;(res.results || []).forEach((r) => { map[r.question_id] = r })
    feedback.value = map
    result.value = { total: res.total, correct: res.correct }
    submitted.value = true
    uni.showToast({ title: `答对 ${res.correct}/${res.total}`, icon: 'none' })
    uni.pageScrollTo({ scrollTop: 0, duration: 200 })
  } finally {
    submitting.value = false
  }
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

.result-card {
  margin-bottom: 22rpx;
  padding: 36rpx;
  border-radius: 20rpx;
  background: #eff6ff;
  border: 1rpx solid #dbeafe;
  text-align: center;
}

.result-num {
  font-size: 48rpx;
  font-weight: 800;
  color: #2563eb;
}

.result-label {
  margin-top: 8rpx;
  font-size: 24rpx;
  color: #64748b;
}

.q-card {
  margin-bottom: 18rpx;
  padding: 26rpx 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.04);
}

.q-stem {
  font-size: 27rpx;
  line-height: 1.8;
  color: #0f172a;
}

.q-idx {
  margin-right: 8rpx;
  font-weight: 700;
}

.chip {
  margin-right: 10rpx;
  padding: 2rpx 14rpx;
  border-radius: 999rpx;
  background: #f1f5f9;
  color: #64748b;
  font-size: 20rpx;
}

.q-score {
  font-size: 22rpx;
  color: #94a3b8;
}

.opts {
  margin-top: 18rpx;
}

.opt {
  margin-bottom: 14rpx;
  padding: 18rpx 24rpx;
  border-radius: 20rpx;
  background: #f1f5f9;
  border: 1rpx solid transparent;
  font-size: 26rpx;
  color: #334155;
}

.opt.active {
  background: #eff6ff;
  border-color: #2563eb;
  color: #2563eb;
}

.opt-key {
  font-weight: 700;
}

.blank-input {
  height: 76rpx;
  margin-top: 18rpx;
  padding: 0 24rpx;
  border-radius: 20rpx;
  background: #f1f5f9;
  border: 1rpx solid transparent;
  font-size: 26rpx;
  box-sizing: border-box;
}

.textarea {
  width: 100%;
  min-height: 160rpx;
  margin-top: 18rpx;
  padding: 20rpx 24rpx;
  border-radius: 20rpx;
  background: #f1f5f9;
  border: 1rpx solid transparent;
  font-size: 26rpx;
  box-sizing: border-box;
}

.ph {
  color: #94a3b8;
}

.fb {
  margin-top: 16rpx;
  padding: 18rpx 22rpx;
  border-radius: 14rpx;
  background: #f8fafc;
  font-size: 24rpx;
  line-height: 1.7;
  color: #475569;
}

.fb.ok {
  background: #ecfdf5;
  color: #10b981;
}

.fb.no {
  background: #fef2f2;
  color: #ef4444;
}

.fb-ana {
  margin-top: 8rpx;
}

.submit-btn {
  margin-top: 12rpx;
  height: 92rpx;
  line-height: 92rpx;
  border-radius: 24rpx;
  background: #2563eb;
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 600;
}

.submit-btn::after {
  border: none;
}

.reset-btn {
  margin-top: 12rpx;
  height: 92rpx;
  line-height: 92rpx;
  border-radius: 24rpx;
  background: #ffffff;
  border: 1rpx solid #2563eb;
  color: #2563eb;
  font-size: 30rpx;
  font-weight: 600;
}

.reset-btn::after {
  border: none;
}
</style>
