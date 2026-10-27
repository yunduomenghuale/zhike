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
              <QuestionImage :question="q" />

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

              <!-- 填空（多空题按空数量渲染输入框） -->
              <div v-else-if="q.qtype === 'blank'" class="blank-input">
                <el-input
                  v-for="(_, blankIndex) in answers[q.question_id]"
                  :key="blankIndex"
                  v-model="answers[q.question_id][blankIndex]"
                  :placeholder="`第 ${blankIndex + 1} 空`"
                  class="blank-item"
                />
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
              <el-button size="large" :icon="Finished" :loading="saving" @click="saveAnswers">
                保存答案
              </el-button>
              <el-button type="primary" size="large" :loading="submitting" :icon="CircleCheck" @click="() => submit(false)">
                提交答卷
              </el-button>
            </div>
            <div class="save-hint">
              <span v-if="dirty" class="save-hint-dirty">
                有未保存的更改，刷新或误关页面将丢失，请及时点击「保存答案」
              </span>
              <span v-else-if="savedAtText" class="save-hint-ok">
                已于 {{ savedAtText }} 保存（保存不提交，考试结束时将自动交卷）
              </span>
              <span v-else>答题过程中可随时「保存答案」暂存（不提交），到结束时间将自动交卷</span>
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

      <!-- 结果：只展示交卷成功摘要，题目回看点击「查看答题情况」跳转独立页 -->
      <template v-else-if="phase === 'result'">
        <el-result icon="success" title="交卷成功" :sub-title="resultSubtitle">
          <template #extra>
            <el-button type="primary" :icon="View" @click="goReview">查看答题情况</el-button>
            <el-button :icon="ArrowLeft" @click="router.push(examListPath())">返回考试列表</el-button>
          </template>
        </el-result>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Clock, CircleCheck, Grid, View, ArrowLeft, Finished } from '@element-plus/icons-vue'
import { startExam, saveExamAnswers, submitExam, reportCheat } from '@/api/exam'
import QuestionImage from '@/components/QuestionImage.vue'

const route = useRoute()
const router = useRouter()
// 课程空间进入时携带 course 查询参数：交卷后的返回/回看都回到课程空间内
const courseId = computed(() => Number(route.query.course) || null)
function examListPath() {
  return courseId.value ? `/student/courses/${courseId.value}/exams` : '/student/exams'
}
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

// 交卷结果摘要：客观题提交即出分；主观题批阅后（或统一出分后）展示总分
const resultSubtitle = computed(() => {
  const total = result.value.total_score
  const obj = result.value.objective_score
  if (total != null) return `总分：${total} 分（客观题 ${obj ?? 0} 分）`
  if (obj != null) return `客观题得分：${obj} 分；主观题待教师批阅后出分`
  return '答卷已提交'
})

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
// 答案有任何改动即标记未保存（保存/提交后清除）
watch(answers, () => { dirty.value = true }, { deep: true })
let remindTimer = null
// 定时提醒保存：每 90 秒检查一次，有未保存答案时提示
function startSaveReminder() {
  remindTimer = setInterval(() => {
    if (dirty.value && phase.value === 'taking') {
      ElMessage.warning({
        message: '有未保存的答案，请点击「保存答案」暂存，避免刷新或误关页面丢失',
        duration: 5000,
      })
    }
  }, 90 * 1000)
}
function onPageLeave(e) {
  // 浏览器原生确认框：刷新/关闭前提醒有未保存答案
  if (dirty.value && phase.value === 'taking') {
    e.preventDefault()
    e.returnValue = ''
    return ''
  }
  return undefined
}

// 把已保存的作答回填到答题模型（刷新/重进后继续答）
function restoreAnswers(saved) {
  if (!saved) return
  questions.value.forEach((q) => {
    const a = saved[String(q.question_id)]
    if (!a) return
    if (q.qtype === 'multi') answers[q.question_id] = Array.isArray(a.keys) ? [...a.keys] : []
    else if (q.qtype === 'blank') {
      const n = Math.max(1, q.blank_count || 1)
      const blanks = Array.isArray(a.blanks) ? [...a.blanks] : []
      answers[q.question_id] = Array.from({ length: n }, (_, i) => blanks[i] ?? '')
    } else if (q.qtype === 'short') answers[q.question_id] = a.text ?? ''
    else answers[q.question_id] = a.key ?? ''
  })
}

async function saveAnswers() {
  if (saving.value || !subId.value) return
  saving.value = true
  try {
    const data = await saveExamAnswers(subId.value, { answers: buildPayload() })
    savedAt.value = data.saved_at
    dirty.value = false
    ElMessage.success(`已保存（${savedAtText.value || '刚刚'}），刷新页面也不会丢失`)
  } catch {
    // 失败原因（如已到交卷时间）由请求拦截器统一提示
  } finally {
    saving.value = false
  }
}

function optionsOf(q) {
  return q.options || []
}

function isAnswered(q) {
  const v = answers[q.question_id]
  if (Array.isArray(v)) {
    // 填空题初始化为 ['',''] 占位数组：有任意一个非空才算已作答
    if (q.qtype === 'blank') return v.some((s) => String(s ?? '').trim() !== '')
    return v.length > 0
  }
  return v !== '' && v != null
}

function scrollToQuestion(id) {
  const el = document.getElementById(`q-${id}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function initAnswerModel() {
  questions.value.forEach((q) => {
    if (q.qtype === 'multi') answers[q.question_id] = []
    else if (q.qtype === 'blank') answers[q.question_id] = new Array(Math.max(1, q.blank_count || 1)).fill('')
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

function startTimer() {
  // 倒计时锚定服务端开始时间：init 已把 remaining 初始化为「截止时间 - 现在」，
  // 刷新/误关/重开页面都从同一截止点续算，不会重置考试时间
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
    // 回填已保存的答案（保存不提交，刷新/重进后继续作答）
    restoreAnswers(data.submission.answers)
    savedAt.value = data.submission.saved_at || null
    dirty.value = false // 回填属于已保存内容，不算未保存更改
    bindAntiCheat()
    startSaveReminder()
    const durationSeconds = (data.duration || 60) * 60
    totalSeconds.value = durationSeconds
    // 优先用服务端续算的剩余秒数（关闭页面重开不重置考试时间）
    remaining.value = Math.max(0, Math.floor(Number(data.remaining_seconds ?? durationSeconds)))
    if (remaining.value <= 0) {
      ElMessage.warning('考试时间已到，正在自动交卷')
      submit(true)
    } else {
      startTimer()
    }
  } catch {
    // 失败原因（未开始/已结束等）由请求拦截器统一弹出，这里直接返回列表页，
    // 避免停留在「试卷暂无题目」的空白答题页
    router.replace(examListPath())
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
    phase.value = 'result'
    clearInterval(timer)
    unbindAntiCheat()
    dirty.value = false
  } finally {
    submitting.value = false
  }
}

// 交卷成功页只展示摘要；题目回看跳转独立页面（按需加载，交卷页不直接展开）
function goReview() {
  // 课程空间来源：回到课程内嵌回看路由（保留课程导航栏）
  if (courseId.value) {
    router.push(`/student/courses/${courseId.value}/exams/${examId}/review`)
  } else {
    router.push({ name: 'exam-review', params: { id: examId } })
  }
}

onMounted(() => {
  init()
  window.addEventListener('beforeunload', onPageLeave)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  clearInterval(remindTimer)
  unbindAntiCheat()
  window.removeEventListener('beforeunload', onPageLeave)
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
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.pending {
  color: #d97706;
  font-weight: 600;
}

.submit-bar {
  text-align: center;
  margin: 32px 0 8px;
  display: flex;
  justify-content: center;
  gap: 12px;
}

.save-hint {
  text-align: center;
  margin-bottom: 24px;
  font-size: 12.5px;
  line-height: 1.6;
  color: #64748b;
}

.save-hint-dirty {
  color: #d97706;
  font-weight: 600;
}

.save-hint-ok {
  color: #16a34a;
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
