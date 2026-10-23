<template>
  <div class="page-container analytics-page">
    <!-- 工具栏：左侧班级筛选，右侧功能按钮 -->
    <div class="an-toolbar">
      <div class="an-toolbar-left">
        <el-select v-model="classId" class="module-select" placeholder="选择班级" popper-class="module-select-popper" style="width: 280px" @change="onClassChange">
          <el-option v-for="c in classes" :key="c.id" :label="`${c.name} / ${classCourseNames(c)}`" :value="c.id" />
        </el-select>
      </div>
      <div class="an-toolbar-actions">
        <el-button class="an-history-btn" :icon="Clock" :disabled="!classId" @click="openHistory">
          历史报告
        </el-button>
        <el-button class="an-primary-btn" type="primary" :icon="MagicStick" :loading="aiBusy" :disabled="!classId" @click="generateReport">
          {{ aiReport ? '重新生成报告' : '生成分析报告' }}
        </el-button>
      </div>
    </div>

    <el-empty v-if="!classId" description="请先选择班级" />

    <template v-else>
      <!-- AI 学情分析报告（异步任务：生成中渐进展示，失败可重试；可回看历史报告） -->
      <div v-if="aiBusy || aiReport || aiFailed" class="ai-card" :class="{ 'is-loading': aiBusy }">
        <div v-if="aiBusy && !historyTask" class="ai-body">
          <div class="ai-loading-tip">
            <el-icon class="is-loading" :size="15"><Loading /></el-icon>
            {{ aiProgressMsg }}
          </div>
          <el-progress
            v-if="aiProgressPct !== null"
            :percentage="aiProgressPct"
            :stroke-width="6"
            :show-text="false"
            class="ai-progress"
          />
          <el-skeleton v-if="!aiReport" :rows="4" animated />
          <div v-else class="ai-md" v-html="renderMd(aiReport)"></div>
        </div>
        <div v-else-if="aiFailed && !historyTask" class="ai-body">
          <div class="ai-failed-tip">
            <el-icon :size="15"><WarningFilled /></el-icon>
            分析失败：{{ aiError || '未知错误' }}
          </div>
          <el-button size="small" type="primary" @click="generateReport">重新生成</el-button>
        </div>
        <template v-else>
          <div class="ai-head">
            <span class="ai-head-icon">
              <el-icon :size="15"><MagicStick /></el-icon>
            </span>
            <span class="ai-head-title">AI 学情分析</span>
            <el-tag v-if="aiDegraded" type="warning" size="small" effect="light" round>部分内容降级</el-tag>
            <span class="ai-head-time">生成于 {{ fmtDateTime(aiGeneratedAt) }}</span>
            <el-button v-if="historyTask" size="small" text class="ai-back-btn" @click="exitHistory">
              返回当前报告
            </el-button>
          </div>
          <div v-if="historyTask" class="ai-history-banner">
            <el-icon :size="13"><Clock /></el-icon>
            正在查看历史报告 · 生成于 {{ fmtDateTime(aiGeneratedAt) }}
          </div>
          <div class="ai-body ai-md" v-html="renderMd(aiReport)"></div>
        </template>
      </div>

      <!-- 学生卡片列表 -->
      <TableSkeleton v-if="loading" :cols="6" />
      <el-empty v-else-if="!students.length" description="班级暂无学生" />
      <div v-else class="stu-list animate-list">
        <div v-for="row in students" :key="row.student_id" class="stu-card" @click="goDetail(row)">
          <div class="stu-main">
            <div class="stu-left">
              <span class="stu-avatar" :style="{ background: avatarBg(row.name) }">
                {{ row.name.charAt(0) }}
              </span>
              <div class="stu-id">
                <div class="stu-name">{{ row.name }}</div>
                <div class="stu-last">最近学习：{{ fmtRelative(row.last_active) }}</div>
              </div>
            </div>

            <div class="stu-metrics">
              <div class="metric metric-practice">
                <span class="metric-label">
                  <span class="metric-ico blue"><el-icon :size="13"><Notebook /></el-icon></span>
                  章节练习
                </span>
                <template v-if="row.practice_total">
                  <div class="metric-practice-line">
                    <span class="metric-text">{{ row.practice_correct }}/{{ row.practice_total }} 题</span>
                    <span class="metric-acc" :style="{ color: accColor(row.accuracy) }">{{ row.accuracy }}%</span>
                  </div>
                  <el-progress
                    :percentage="row.accuracy"
                    :stroke-width="6"
                    :color="accColor(row.accuracy)"
                    :show-text="false"
                    class="metric-bar"
                  />
                </template>
                <span v-else class="metric-none">未做练习</span>
              </div>
              <div class="metric">
                <span class="metric-label">
                  <span class="metric-ico purple"><el-icon :size="13"><Files /></el-icon></span>
                  作业
                </span>
                <strong class="metric-value" :class="{ warn: row.homework_submitted < row.homework_total }">
                  {{ row.homework_submitted }}/{{ row.homework_total }}
                </strong>
              </div>
              <div class="metric">
                <span class="metric-label">
                  <span class="metric-ico orange"><el-icon :size="13"><Medal /></el-icon></span>
                  考试
                </span>
                <strong class="metric-value">
                  {{ row.exam_taken }}/{{ row.exam_total }}
                  <span v-if="row.avg_exam_score !== null" class="metric-score">· 均分 {{ row.avg_exam_score }}</span>
                </strong>
              </div>
              <div v-if="row.experiment_total" class="metric">
                <span class="metric-label">
                  <span class="metric-ico teal"><el-icon :size="13"><Cpu /></el-icon></span>
                  实验
                </span>
                <strong class="metric-value" :class="{ warn: row.experiment_done < row.experiment_total }">
                  {{ row.experiment_done }}/{{ row.experiment_total }}
                  <span v-if="row.avg_experiment_score !== null" class="metric-score">· 均分 {{ row.avg_experiment_score }}</span>
                </strong>
              </div>
            </div>

            <div class="stu-warnings">
              <el-tag
                v-for="w in row.warnings"
                :key="w"
                type="danger"
                size="small"
                effect="light"
                round
                class="warn-pulse"
                >{{ w }}</el-tag
              >
              <el-tag v-if="!row.warnings.length" type="success" size="small" effect="light" round>正常</el-tag>
            </div>
          </div>

          <div v-if="aiComments[row.student_id]" class="stu-ai">
            <el-icon :size="13" class="stu-ai-icon"><MagicStick /></el-icon>
            <span>{{ aiComments[row.student_id] }}</span>
          </div>
          <div v-else-if="isNoDataStudent(row)" class="stu-ai muted">暂无学习数据，未参与本次分析</div>
          <div v-else-if="aiBusy" class="stu-ai muted">AI 简评生成中…</div>
        </div>
      </div>
    </template>

    <!-- 历史报告列表（按 AITask 查，点击回看完整报告） -->
    <el-dialog v-model="historyVisible" title="历史报告" width="640px" class="an-history-dialog">
      <div v-loading="historyLoading" class="history-list">
        <el-empty v-if="!historyLoading && !historyList.length" description="暂无历史报告" :image-size="60" />
        <div
          v-for="r in historyList"
          :key="r.task_id"
          class="history-item"
          :class="{ 'is-failed': r.status !== 'success' }"
          @click="viewHistory(r)"
        >
          <div class="history-item-head">
            <el-tag :type="statusType(r.status)" size="small" effect="light" round>{{ statusText(r.status) }}</el-tag>
            <el-tag v-if="r.degraded" type="warning" size="small" effect="light" round>部分降级</el-tag>
            <span class="history-time">{{ fmtDateTime(r.generated_at || r.created_at) }}</span>
          </div>
          <div class="history-item-meta">
            <span v-if="r.analyzed_count != null">分析 {{ r.analyzed_count }} 人</span>
            <span v-if="r.comment_count">简评 {{ r.comment_count }} 条</span>
          </div>
          <div v-if="r.report_excerpt" class="history-excerpt" v-html="renderMd(r.report_excerpt)"></div>
          <div v-else-if="r.error" class="history-error">{{ r.error }}</div>
          <div v-else class="history-excerpt muted">暂无报告内容</div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MagicStick, Loading, Notebook, Files, Medal, Cpu, WarningFilled, Clock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { renderAiMarkdown } from '@/utils/markdown'
import { sortedCourseNames } from '@/utils/course-sort'
import { listClasses } from '@/api/classroom'
import { getClassStats, generateClassAiReport, getClassAiReportHistory } from '@/api/analytics'
import { getAiTask } from '@/api/ai-task'
import { useAiTaskPolling } from '@/composables/useAiTaskPolling'

const renderMd = renderAiMarkdown

const classes = ref([])
const classId = ref(null)
const loading = ref(false)
const students = ref([])
// AI 学情分析：异步任务（submit → 轮询 /ai-tasks/<id>/ → 终态渲染）
const { task: aiTask, start: startPolling, stop: stopPolling } = useAiTaskPolling()
const aiSubmitting = ref(false)
// 历史报告（P3）：查看历史时以历史任务为展示口径，否则用当前任务
const historyVisible = ref(false)
const historyLoading = ref(false)
const historyList = ref([])
const historyTask = ref(null)
const displayTask = computed(() => historyTask.value || aiTask.value)
const aiResult = computed(() => displayTask.value?.result || null)
const aiReport = computed(() => aiResult.value?.report || '')
const aiComments = computed(() => aiResult.value?.comments || {})
const aiGeneratedAt = computed(() => aiResult.value?.generated_at || null)
const aiDegraded = computed(() => Boolean(aiResult.value?.degraded))
const aiFailed = computed(() => aiTask.value?.status === 'failed')
const aiError = computed(() => aiTask.value?.error || '')
const aiBusy = computed(
  () => aiSubmitting.value || (aiTask.value ? ['pending', 'running'].includes(aiTask.value.status) : false)
)
const aiProgressMsg = computed(() => aiTask.value?.progress?.message || 'AI 正在分析班级数据，请稍候…')
const aiProgressPct = computed(() => {
  const p = aiTask.value?.progress
  if (!p || !p.total) return null
  return Math.round(((p.done || 0) / p.total) * 100)
})
const noDataIds = computed(
  () => new Set((aiResult.value?.no_data_students || []).map((s) => Number(s.student_id)))
)
function isNoDataStudent(row) {
  return noDataIds.value.has(Number(row.student_id))
}
const route = useRoute()
const router = useRouter()
const fixedCourseId = computed(() => Number(route.params.id) || null)

function goDetail(row) {
  // 课程空间内的学习统计：走课程子路由进学生详情（保留课程导航栏）；
  // 全局「学习统计」页（/teacher/analytics）仍走 MainLayout 路由
  if (fixedCourseId.value) {
    router.push({
      name: 'course-analytics-student',
      params: { id: fixedCourseId.value, studentId: row.student_id },
      query: { class: classId.value, course: activeCourseId() },
    })
    return
  }
  router.push({
    name: 'class-student-detail',
    params: { classId: classId.value, studentId: row.student_id },
    query: activeCourseId() ? { course: activeCourseId() } : {},
  })
}

function classCourseNames(item) {
  // 多课程名按首字母排序（英文/数字在前、中文按拼音），与班级卡片口径一致
  return sortedCourseNames(item).join('、') || '未关联课程'
}

function activeCourseId() {
  const classroom = classes.value.find((item) => item.id === classId.value)
  return fixedCourseId.value || classroom?.course || null
}

const AVATAR_COLORS = ['#2563eb', '#10b981', '#f59e0b', '#8b5cf6', '#06b6d4', '#f97316']
function avatarBg(name) {
  let hash = 0
  for (const ch of name || '') hash = (hash * 31 + ch.codePointAt(0)) >>> 0
  const color = AVATAR_COLORS[hash % AVATAR_COLORS.length]
  return `linear-gradient(135deg, ${color} 0%, ${color}cc 100%)`
}

function accColor(a) {
  if (a == null) return '#94a3b8'
  if (a >= 80) return '#10b981'
  if (a >= 60) return '#f59e0b'
  return '#ef4444'
}

function fmtRelative(t) {
  if (!t) return '—'
  const d = new Date(t)
  const now = new Date()
  const startOf = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate())
  const days = Math.round((startOf(now) - startOf(d)) / 86400000)
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  if (days <= 0) return `今天 ${hm}`
  if (days === 1) return `昨天 ${hm}`
  if (days < 30) return `${days} 天前`
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}

function fmtDateTime(t) {
  return t ? new Date(t).toLocaleString() : ''
}

function resetAi() {
  stopPolling()
  aiTask.value = null
  historyTask.value = null
}

// ---- 历史报告（P3）----
const REPORT_STATUS = {
  success: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  running: { text: '进行中', type: 'warning' },
  pending: { text: '排队中', type: 'info' },
}
function statusText(s) {
  return REPORT_STATUS[s]?.text || s
}
function statusType(s) {
  return REPORT_STATUS[s]?.type || 'info'
}

async function openHistory() {
  if (!classId.value) return
  historyVisible.value = true
  historyLoading.value = true
  try {
    const data = await getClassAiReportHistory(classId.value)
    historyList.value = data.reports ?? []
  } catch {
    historyList.value = []
  } finally {
    historyLoading.value = false
  }
}

async function viewHistory(item) {
  if (item.status !== 'success') {
    ElMessage.warning('该报告未生成成功，无法查看')
    return
  }
  try {
    const task = await getAiTask(item.task_id)
    if (!task?.result?.report) {
      ElMessage.warning('该报告暂无内容')
      return
    }
    historyTask.value = task
    historyVisible.value = false
  } catch {
    // 拉取失败已由响应拦截器统一提示
  }
}

function exitHistory() {
  historyTask.value = null
}

async function loadClasses() {
  const data = await listClasses(fixedCourseId.value ? { course: fixedCourseId.value } : undefined)
  const list = data.results ?? data
  classes.value = fixedCourseId.value
    ? list.filter((item) => (item.courses || [item.course]).map(Number).includes(fixedCourseId.value))
    : list
  if (classes.value.length) {
    classId.value = classes.value[0].id
    load()
  } else {
    classId.value = null
    students.value = []
  }
}

async function load() {
  if (!classId.value) return
  loading.value = true
  try {
    const data = await getClassStats(classId.value, { course: activeCourseId() })
    students.value = data.students
  } finally {
    loading.value = false
  }
}

function onClassChange() {
  resetAi()
  load()
}

async function generateReport() {
  if (!classId.value || aiBusy.value) return
  historyTask.value = null // 生成新报告即退出历史查看，回到当前任务口径
  aiSubmitting.value = true
  try {
    // D5 异步化：提交即返回 task_id，轮询任务终态（S1 报告 / S2 简评增量落库，渐进渲染）
    const data = await generateClassAiReport(classId.value, { course: activeCourseId() })
    startPolling(data.task_id, {
      onSuccess: () => {
        if (!aiReport.value) ElMessage.warning('AI 暂未生成有效内容，请重试')
      },
    })
  } catch {
    // 频率限制（429）/ 无学生（400）等已由响应拦截器统一提示，仅复位提交态
  } finally {
    aiSubmitting.value = false
  }
}

// 刷新页面后恢复进行中的分析任务（异步任务刷新续看）：
// 任务行在服务端持久化，刷新丢失的只是前端的任务 ID——挂载时从历史报告
// 接口找回本班、当前课程最新的 pending/running 任务，重新拉起轮询与进度 UI。
// 陈旧保护：创建超过 12 分钟仍未终态，视为服务端已中断（后台线程已死、
// 任务行停留在 running），直接展示失败+重试，避免对着死任务空轮 10 分钟。
async function resumeActiveTask() {
  if (!classId.value) return
  try {
    const data = await getClassAiReportHistory(classId.value)
    const active = (data.reports || []).find(
      (t) =>
        ['pending', 'running'].includes(t.status) &&
        (!t.course_id || t.course_id === activeCourseId())
    )
    if (!active) return
    startPolling(
      active.task_id,
      {
        onSuccess: () => {
          if (!aiReport.value) ElMessage.warning('AI 暂未生成有效内容，请重试')
        },
      },
      { staleAfterMs: 12 * 60 * 1000, createdAt: active.created_at }
    )
  } catch {
    // 恢复失败不影响页面使用：教师可手动重新生成
  }
}

onMounted(async () => {
  await loadClasses()
  resumeActiveTask()
})
</script>

<style scoped>
/* 工具栏（与知识库页一致：左右分布，无分隔线） */
.an-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-bottom: 4px;
  margin-bottom: 16px;
}
.an-toolbar-left,
.an-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.an-primary-btn {
  height: 40px;
  padding: 0 20px;
  border: 0;
  border-radius: 12px;
  font-weight: 700;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.2);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.an-primary-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.2);
}
.an-history-btn {
  height: 40px;
  padding: 0 16px;
  border-radius: 12px;
  font-weight: 600;
  color: var(--primary-600);
  border-color: rgba(37, 99, 235, 0.25);
  background: #fff;
}
.an-history-btn:hover {
  color: var(--primary-500);
  border-color: var(--primary-500);
  background: var(--primary-50);
}

/* ===== 历史报告 ===== */
.history-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 480px;
  overflow-y: auto;
}
.history-item {
  padding: 12px 14px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}
.history-item:hover {
  border-color: rgba(96, 165, 250, 0.5);
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.08);
}
.history-item.is-failed {
  opacity: 0.75;
}
.history-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.history-time {
  margin-left: auto;
  color: var(--gray-400);
  font-size: 12px;
}
.history-item-meta {
  display: flex;
  gap: 14px;
  margin-top: 6px;
  color: var(--gray-500);
  font-size: 12.5px;
}
.history-excerpt {
  margin-top: 6px;
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
/* 摘要按 markdown 渲染：标题/加粗 compact 化，配合外层 3 行夹取 */
.history-excerpt :deep(h2),
.history-excerpt :deep(h3) {
  margin: 0;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--gray-900);
}
.history-excerpt :deep(p) {
  margin: 0;
}
.history-excerpt :deep(strong) {
  color: var(--gray-900);
}
.history-excerpt :deep(ul),
.history-excerpt :deep(ol) {
  margin: 0;
  padding-left: 18px;
}
.history-excerpt.muted {
  color: var(--gray-300);
}
.history-error {
  margin-top: 6px;
  color: var(--danger);
  font-size: 12.5px;
}
.ai-history-banner {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 20px 8px;
  padding: 6px 12px;
  border-radius: 8px;
  color: var(--primary-600);
  font-size: 12.5px;
  background: var(--primary-50);
}
.ai-back-btn {
  margin-left: 8px;
  color: var(--primary-600);
}

/* ===== AI 学情分析报告 ===== */
.ai-card {
  position: relative;
  margin-bottom: 16px;
  padding: 1.5px;
  border-radius: var(--radius-lg);
  background: linear-gradient(120deg, #60a5fa 0%, #a78bfa 45%, #f0abfc 75%, #60a5fa 100%);
  background-size: 300% 100%;
  box-shadow: 0 14px 34px rgba(99, 102, 241, 0.14);
  animation: ai-border-flow 6s linear infinite;
}
.ai-card.is-loading {
  animation: ai-border-flow 2.4s linear infinite, ai-breathe 1.8s ease-in-out infinite;
}
@keyframes ai-border-flow {
  from { background-position: 0% 0; }
  to { background-position: 300% 0; }
}
@keyframes ai-breathe {
  0%, 100% { box-shadow: 0 14px 34px rgba(99, 102, 241, 0.14); }
  50% { box-shadow: 0 16px 42px rgba(99, 102, 241, 0.34); }
}
.ai-card::before {
  content: '';
  position: absolute;
  inset: 1.5px;
  border-radius: calc(var(--radius-lg) - 1.5px);
  background: rgba(255, 255, 255, 0.94);
}
.ai-card > * {
  position: relative;
}
.ai-head {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 14px 20px 0;
}
.ai-head-icon {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: #fff;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
}
.ai-head-title {
  font-size: 15px;
  font-weight: 750;
  background: linear-gradient(90deg, #2563eb, #7c3aed);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.ai-head-time {
  margin-left: auto;
  color: var(--gray-400);
  font-size: 12px;
}
.ai-body {
  padding: 10px 20px 16px;
}
.ai-loading-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--primary-600);
}
.ai-progress {
  margin-bottom: 14px;
}
.ai-failed-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--danger);
}
.ai-md {
  font-size: 14px;
  line-height: 1.85;
  color: var(--gray-700);
}
.ai-md :deep(h2) {
  margin: 12px 0 8px;
  font-size: 15px;
  font-weight: 700;
  color: var(--gray-900);
  display: flex;
  align-items: center;
  gap: 8px;
}
.ai-md :deep(h2)::before {
  content: '';
  width: 4px;
  height: 15px;
  border-radius: 2px;
  background: linear-gradient(180deg, #3b82f6, #8b5cf6);
}
.ai-md :deep(h2:first-child) { margin-top: 2px; }
.ai-md :deep(p) { margin: 0 0 8px; }
.ai-md :deep(ul), .ai-md :deep(ol) { margin: 0 0 8px; padding-left: 20px; }
.ai-md :deep(strong) { color: var(--gray-900); }

/* ===== 学生卡片列表（与知识库资料行一致） ===== */
.stu-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.stu-card {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(37, 99, 235, 0.09);
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(248, 251, 255, 0.9));
  box-shadow: 0 8px 22px rgba(37, 99, 235, 0.06);
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.stu-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: linear-gradient(180deg, #3b82f6, #8b5cf6);
  opacity: 0;
  transition: opacity 0.18s ease;
}
.stu-card:hover {
  transform: translateY(-2px);
  border-color: rgba(96, 165, 250, 0.45);
  box-shadow: 0 14px 32px rgba(37, 99, 235, 0.12);
}
.stu-card:hover::before {
  opacity: 1;
}
.stu-main {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 14px 18px;
}
.stu-left {
  display: flex;
  align-items: center;
  gap: 13px;
  min-width: 0;
  flex: 0 0 220px;
}
.stu-avatar {
  width: 42px;
  height: 42px;
  display: flex;
  flex: 0 0 42px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.14);
  transition: transform 0.18s ease;
}
.stu-card:hover .stu-avatar {
  transform: scale(1.05);
}
.stu-name {
  color: var(--gray-900);
  font-size: 15px;
  font-weight: 650;
}
.stu-last {
  margin-top: 3px;
  color: var(--gray-400);
  font-size: 12px;
}
.stu-metrics {
  flex: 1;
  min-width: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(140px, 1fr));
  gap: 10px 26px;
  align-content: center;
}
.metric {
  display: grid;
  gap: 5px;
  min-width: 0;
}
.metric-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--gray-400);
  font-size: 12px;
}
.metric-ico {
  width: 22px;
  height: 22px;
  display: inline-grid;
  place-items: center;
  border-radius: 7px;
}
.metric-ico.blue {
  color: var(--primary-600);
  background: var(--primary-50);
}
.metric-ico.purple {
  color: #8b5cf6;
  background: #f5f3ff;
}
.metric-ico.orange {
  color: var(--warning);
  background: #fff7ed;
}
.metric-ico.teal {
  color: #0d9488;
  background: #f0fdfa;
}
.metric-value {
  color: var(--gray-800);
  font-size: 14.5px;
  font-weight: 700;
}
.metric-value.warn {
  color: var(--danger);
}
.metric-score {
  margin-left: 4px;
  color: var(--primary-600);
  font-size: 12.5px;
  font-weight: 600;
}
.metric-practice-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.metric-text {
  color: var(--gray-700);
  font-size: 13px;
}
.metric-acc {
  font-size: 13px;
  font-weight: 700;
}
.metric-bar {
  width: 100%;
}
.metric-bar :deep(.el-progress-bar__outer) {
  background: var(--gray-100);
}
.metric-none {
  color: var(--gray-300);
  font-size: 13px;
}
/* 预警区：定宽竖排滚动，标签再多也不挤压指标列 */
.stu-warnings {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  flex-shrink: 0;
  width: 150px;
  max-height: 100px;
  overflow-y: auto;
  padding: 2px 2px 2px 0;
  scrollbar-width: thin;
  scrollbar-color: var(--gray-300) transparent;
}
.stu-warnings::-webkit-scrollbar {
  width: 4px;
}
.stu-warnings::-webkit-scrollbar-thumb {
  border-radius: 2px;
  background: var(--gray-300);
}
.stu-warnings::-webkit-scrollbar-track {
  background: transparent;
}
/* 长文案预警允许在竖排列内换行，防 nowrap 溢出被卡片裁切 */
.stu-warnings :deep(.el-tag) {
  max-width: 100%;
  height: auto;
  white-space: normal;
  text-align: left;
}

/* AI 简评条 */
.stu-ai {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0 18px;
  padding: 10px 14px 12px;
  border-top: 1px dashed var(--gray-200);
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.65;
}
.stu-ai-icon {
  flex-shrink: 0;
  margin-top: 3px;
  color: #8b5cf6;
}
.stu-ai.muted {
  color: var(--gray-400);
}

@media (max-width: 900px) {
  .stu-main {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .stu-left {
    flex-basis: auto;
  }
  .stu-metrics {
    gap: 12px 16px;
  }
  .stu-warnings {
    align-items: flex-start;
    width: 100%;
    max-height: 112px;
  }
}
</style>
