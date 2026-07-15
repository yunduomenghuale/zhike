<template>
  <div class="exam-taking page-container">
    <!-- 顶部：标题 + 倒计时 -->
    <div class="exam-bar">
      <div class="exam-title">
        <el-icon :size="22" color="#2563eb"><Document /></el-icon>
        <span class="exam-name">{{ examName }}</span>
      </div>
      <div v-if="phase === 'taking'" class="timer-ring" :class="{ danger: remaining < 60 }">
        <el-progress
          type="circle"
          :width="62"
          :stroke-width="6"
          :percentage="timePercent"
          :color="remaining < 60 ? '#f56c6c' : '#2563eb'"
        >
          <template #default>
            <div class="ring-inner">
              <el-icon class="ring-clock"><Clock /></el-icon>
              <span class="ring-time">{{ mmss }}</span>
            </div>
          </template>
        </el-progress>
      </div>
    </div>

    <el-alert
      v-if="phase === 'taking' && cheatCount > 0"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
      :title="`检测到 ${cheatCount} 次异常操作`"
      description="切屏/复制等行为已被记录，请专注答题。"
    />

    <div v-loading="loading">
      <!-- 答题 -->
      <template v-if="phase === 'taking'">
        <el-empty v-if="!questions.length" description="试卷暂无题目，请联系老师组卷">
          <template #description>
            <div class="empty-text">试卷暂无题目</div>
            <div class="empty-tip">请联系老师完成组卷</div>
          </template>
        </el-empty>

        <el-row v-else :gutter="24">
          <el-col :xs="24" :lg="18">
            <el-card
              v-for="(q, i) in questions"
              :key="q.question_id"
              :id="`q-${q.question_id}`"
              class="q-card"
              shadow="never"
            >
              <div class="q-stem">
                <span class="q-index">{{ i + 1 }}.</span>
                <el-tag size="small" effect="light" class="q-type">{{ q.qtype_display }}</el-tag>
                <span>{{ q.stem }}</span>
                <span class="q-score">（{{ q.score }} 分）</span>
              </div>

              <!-- 单选 / 判断 -->
              <el-radio-group v-if="q.qtype === 'single' || q.qtype === 'judge'" v-model="answers[q.question_id]">
                <el-radio v-for="opt in optionsOf(q)" :key="opt.key" :value="opt.key" class="q-opt">
                  <span class="opt-key">{{ opt.key }}.</span>
                  <span>{{ opt.text }}</span>
                </el-radio>
              </el-radio-group>

              <!-- 多选 -->
              <el-checkbox-group v-else-if="q.qtype === 'multi'" v-model="answers[q.question_id]">
                <el-checkbox v-for="opt in optionsOf(q)" :key="opt.key" :value="opt.key" class="q-opt">
                  <span class="opt-key">{{ opt.key }}.</span>
                  <span>{{ opt.text }}</span>
                </el-checkbox>
              </el-checkbox-group>

              <!-- 填空 -->
              <div v-else-if="q.qtype === 'blank'" class="blank-input">
                <el-input v-model="answers[q.question_id][0]" placeholder="请输入答案" />
              </div>

              <!-- 简答 -->
              <el-input
                v-else
                v-model="answers[q.question_id]"
                type="textarea"
                :rows="4"
                placeholder="请作答（主观题由老师批改）"
                resize="none"
              />
            </el-card>

            <div class="submit-bar">
              <el-button type="primary" size="large" :loading="submitting" :icon="CircleCheck" @click="() => submit(false)">
                提交答卷
              </el-button>
            </div>
          </el-col>

          <!-- 题号导航 -->
          <el-col :xs="24" :lg="6" class="nav-col">
            <el-card class="nav-card" shadow="never">
              <template #header>
                <div class="nav-header">
                  <el-icon><Grid /></el-icon>
                  <span>答题卡</span>
                </div>
              </template>
              <div class="nav-grid">
                <div
                  v-for="(q, i) in questions"
                  :key="q.question_id"
                  :class="['nav-item', { active: isAnswered(q) }]"
                  @click="scrollToQuestion(q.question_id)"
                >
                  {{ i + 1 }}
                </div>
              </div>
              <div class="nav-legend">
                <span class="legend-item"><span class="dot answered"></span> 已作答</span>
                <span class="legend-item"><span class="dot"></span> 未作答</span>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </template>

      <!-- 结果 -->
      <template v-else-if="phase === 'result'">
        <el-result icon="success" title="交卷成功" :sub-title="`客观题得分：${result.objective_score ?? '-'} / ${result.total_score ?? '-'} 分`">
          <template #extra>
            <el-button v-if="canReview" type="primary" :icon="View" @click="loadReview">查看解析</el-button>
            <el-button :icon="ArrowLeft" @click="$router.push('/student/exams')">返回考试列表</el-button>
          </template>
        </el-result>

        <div v-if="reviewList.length" class="review">
          <el-card v-for="(q, i) in reviewList" :key="q.question_id" class="q-card" shadow="never">
            <div class="q-stem">
              <span class="q-index">{{ i + 1 }}.</span>
              <el-tag size="small" effect="light" class="q-type">{{ q.qtype_display }}</el-tag>
              <span>{{ q.stem }}</span>
            </div>
            <div class="review-line">
              你的答案：<span class="answer">{{ fmtAnswer(q.student_answer) }}</span>
            </div>
            <div v-if="q.is_objective" class="review-line correct">
              正确答案：<span>{{ fmtAnswer(q.correct_answer) }}</span>
            </div>
            <div v-if="q.analysis" class="review-line analysis">解析：{{ q.analysis }}</div>
          </el-card>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Clock, CircleCheck, Grid, View, ArrowLeft } from '@element-plus/icons-vue'
import { startExam, submitExam, reviewExam, reportCheat } from '@/api/exam'

const route = useRoute()
const examId = Number(route.params.id)

const loading = ref(true)
const phase = ref('taking')
const examName = ref('在线考试')
const questions = ref([])
const answers = reactive({})
const subId = ref(null)
const antiCheat = ref({})
const submitting = ref(false)
const result = ref({})
const canReview = ref(false)
const reviewList = ref([])

const remaining = ref(0)
const totalSeconds = ref(0)
let timer = null
const mmss = computed(() => {
  const m = String(Math.floor(remaining.value / 60)).padStart(2, '0')
  const s = String(remaining.value % 60).padStart(2, '0')
  return `${m}:${s}`
})
const timePercent = computed(() =>
  totalSeconds.value ? Math.round((remaining.value / totalSeconds.value) * 100) : 0,
)

const cheatCount = ref(0)

function optionsOf(q) {
  return q.options || []
}

function isAnswered(q) {
  const v = answers[q.question_id]
  if (Array.isArray(v)) return v.length > 0 && !(v.length === 1 && v[0] === '')
  return v !== '' && v != null
}

function scrollToQuestion(id) {
  const el = document.getElementById(`q-${id}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function initAnswerModel() {
  questions.value.forEach((q) => {
    if (q.qtype === 'multi') answers[q.question_id] = []
    else if (q.qtype === 'blank') answers[q.question_id] = ['']
    else answers[q.question_id] = ''
  })
}

function buildPayload() {
  const payload = {}
  questions.value.forEach((q) => {
    const v = answers[q.question_id]
    if (q.qtype === 'multi') payload[q.question_id] = { keys: v }
    else if (q.qtype === 'blank') payload[q.question_id] = { blanks: v }
    else if (q.qtype === 'short') payload[q.question_id] = { text: v }
    else payload[q.question_id] = { key: v }
  })
  return payload
}

function report(action, note = '') {
  cheatCount.value += 1
  reportCheat({ exam: examId, action, note }).catch(() => {})
}
function onVisibility() {
  if (document.hidden && antiCheat.value.detect_blur) report('blur', '切换/离开页面')
}
function onCopy(e) {
  if (antiCheat.value.forbid_copy) { e.preventDefault(); report('copy', '尝试复制') }
}
function onPaste(e) {
  if (antiCheat.value.forbid_paste) { e.preventDefault(); report('paste', '尝试粘贴') }
}
function onContextMenu(e) {
  if (antiCheat.value.forbid_contextmenu) { e.preventDefault(); report('rightclick', '右键菜单') }
}
function bindAntiCheat() {
  document.addEventListener('visibilitychange', onVisibility)
  document.addEventListener('copy', onCopy)
  document.addEventListener('paste', onPaste)
  document.addEventListener('contextmenu', onContextMenu)
}
function unbindAntiCheat() {
  document.removeEventListener('visibilitychange', onVisibility)
  document.removeEventListener('copy', onCopy)
  document.removeEventListener('paste', onPaste)
  document.removeEventListener('contextmenu', onContextMenu)
}

function startTimer(minutes) {
  totalSeconds.value = minutes * 60
  remaining.value = minutes * 60
  timer = setInterval(() => {
    remaining.value -= 1
    if (remaining.value <= 0) {
      clearInterval(timer)
      ElMessage.warning('考试时间到，正在自动交卷')
      submit(true)
    }
  }, 1000)
}

async function init() {
  try {
    const data = await startExam(examId)
    subId.value = data.submission.id
    questions.value = data.questions
    antiCheat.value = data.anti_cheat || {}
    initAnswerModel()
    bindAntiCheat()
    startTimer(data.duration || 60)
  } catch {
    ElMessage.error('无法进入考试')
  } finally {
    loading.value = false
  }
}

async function submit(isTimeout) {
  if (!isTimeout) {
    try {
      await ElMessageBox.confirm('确认交卷？交卷后不可修改。', '提示', { type: 'warning' })
    } catch {
      return
    }
  }
  submitting.value = true
  try {
    const data = await submitExam(subId.value, { answers: buildPayload(), timeout: isTimeout })
    result.value = data
    canReview.value = true
    phase.value = 'result'
    clearInterval(timer)
    unbindAntiCheat()
  } finally {
    submitting.value = false
  }
}

async function loadReview() {
  try {
    const data = await reviewExam(subId.value)
    reviewList.value = data.questions
  } catch {
    ElMessage.info('本次考试未开放解析')
  }
}

function fmtAnswer(a) {
  if (!a) return '（未作答）'
  if (a.key) return a.key
  if (a.keys) return a.keys.join(', ')
  if (a.blanks) return a.blanks.join(' / ')
  if (a.text) return a.text
  return '（未作答）'
}

onMounted(init)
onBeforeUnmount(() => {
  clearInterval(timer)
  unbindAntiCheat()
})
</script>

<style scoped>
.exam-taking {
  padding-bottom: 40px;
}

.exam-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
}

.exam-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.exam-name {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
}

.timer {
  font-size: 18px;
  font-weight: 700;
  color: #2563eb;
  display: flex;
  align-items: center;
  gap: 6px;
  background: #eff6ff;
  padding: 8px 16px;
  border-radius: 20px;
}

.timer.danger {
  color: #ef4444;
  background: #fef2f2;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* #6 倒计时环形进度 */
.timer-ring {
  display: flex;
  align-items: center;
}

.timer-ring.danger {
  animation: pulse 1s infinite;
}

.ring-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  line-height: 1.1;
}

.ring-clock {
  font-size: 13px;
  color: #94a3b8;
  margin-bottom: 1px;
}

.ring-time {
  font-size: 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.timer-ring.danger .ring-time,
.timer-ring.danger .ring-clock {
  color: #ef4444;
}

.q-card {
  margin-bottom: 16px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}

.q-stem {
  margin-bottom: 16px;
  line-height: 1.7;
  font-size: 15px;
  color: #1e293b;
}

.q-index {
  font-weight: 700;
  margin-right: 6px;
}

.q-type {
  margin-right: 8px;
  font-weight: 500;
}

.q-score {
  color: #64748b;
  font-size: 13px;
  margin-left: 6px;
}

.q-opt {
  display: flex;
  align-items: flex-start;
  margin: 10px 0;
  padding: 8px 12px;
  border-radius: 8px;
  transition: background 0.2s ease;
}

.q-opt:hover {
  background: #f8fafc;
}

.opt-key {
  font-weight: 600;
  margin-right: 4px;
  color: #2563eb;
}

.blank-input {
  max-width: 400px;
}

.submit-bar {
  text-align: center;
  margin: 32px 0;
}

.nav-col {
  position: sticky;
  top: 20px;
  align-self: flex-start;
}

.nav-card {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}

.nav-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #1e293b;
}

.nav-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
}

.nav-item {
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.nav-item:hover {
  background: #dbeafe;
  color: #2563eb;
}

.nav-item.active {
  background: #2563eb;
  color: #fff;
}

.nav-legend {
  display: flex;
  gap: 16px;
  margin-top: 16px;
  font-size: 12px;
  color: #64748b;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
}

.dot.answered {
  background: #2563eb;
  border-color: #2563eb;
}

.review-line {
  margin-top: 8px;
  font-size: 14px;
  color: #475569;
}

.review-line .answer {
  font-weight: 600;
  color: #1e293b;
}

.review-line.correct {
  color: #10b981;
  font-weight: 500;
}

.review-line.analysis {
  color: #64748b;
  background: #f8fafc;
  padding: 10px 12px;
  border-radius: 8px;
  margin-top: 10px;
}

.empty-text {
  font-size: 14px;
  color: #64748b;
  margin-bottom: 4px;
}

.empty-tip {
  font-size: 12px;
  color: #94a3b8;
}

@media (max-width: 992px) {
  .nav-col {
    position: static;
    margin-bottom: 20px;
  }
}
</style>
