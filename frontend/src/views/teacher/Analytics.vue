<template>
  <div class="page-container analytics-page">
    <!-- 工具栏：左侧班级筛选，右侧功能按钮 -->
    <div class="an-toolbar">
      <div class="an-toolbar-left">
        <el-select v-model="classId" class="module-select" placeholder="选择班级" popper-class="module-select-popper" style="width: 280px" @change="onClassChange">
          <el-option v-for="c in classes" :key="c.id" :label="`${classCourseNames(c)} / ${c.name}`" :value="c.id" />
        </el-select>
      </div>
      <div class="an-toolbar-actions">
        <el-button class="an-primary-btn" type="primary" :icon="MagicStick" :loading="aiLoading" :disabled="!classId" @click="generateReport">
          {{ aiReport ? '重新生成报告' : '生成分析报告' }}
        </el-button>
      </div>
    </div>

    <el-empty v-if="!classId" description="请先选择班级" />

    <template v-else>
      <!-- AI 学情分析报告（生成后展示） -->
      <div v-if="aiLoading || aiReport" class="ai-card" :class="{ 'is-loading': aiLoading }">
        <div v-if="aiLoading" class="ai-body">
          <div class="ai-loading-tip">
            <el-icon class="is-loading" :size="15"><Loading /></el-icon>
            AI 正在分析班级数据，请稍候…
          </div>
          <el-skeleton :rows="4" animated />
        </div>
        <template v-else>
          <div class="ai-head">
            <span class="ai-head-icon">
              <el-icon :size="15"><MagicStick /></el-icon>
            </span>
            <span class="ai-head-title">AI 学情分析</span>
            <span class="ai-head-time">生成于 {{ fmtDateTime(aiGeneratedAt) }}</span>
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
            </div>

            <div class="stu-warnings">
              <el-tag v-for="w in row.warnings" :key="w" type="danger" size="small" effect="light" round class="warn-pulse">{{ w }}</el-tag>
              <el-tag v-if="!row.warnings.length" type="success" size="small" effect="light" round>正常</el-tag>
            </div>
          </div>

          <div v-if="aiComments[row.student_id]" class="stu-ai">
            <el-icon :size="13" class="stu-ai-icon"><MagicStick /></el-icon>
            <span>{{ aiComments[row.student_id] }}</span>
          </div>
          <div v-else-if="aiLoading" class="stu-ai muted">AI 简评生成中…</div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MagicStick, Loading, Notebook, Files, Medal } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { listClasses } from '@/api/classroom'
import { getClassStats, generateClassAiReport } from '@/api/analytics'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

const classes = ref([])
const classId = ref(null)
const loading = ref(false)
const students = ref([])
const aiLoading = ref(false)
const aiReport = ref('')
const aiComments = ref({})
const aiGeneratedAt = ref(null)
const route = useRoute()
const router = useRouter()
const fixedCourseId = computed(() => Number(route.params.id) || null)

function goDetail(row) {
  router.push({
    name: 'class-student-detail',
    params: { classId: classId.value, studentId: row.student_id },
    query: activeCourseId() ? { course: activeCourseId() } : {},
  })
}

function classCourseNames(item) {
  return item.course_names?.join('、') || item.course_name || '未关联课程'
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

function renderMd(text) {
  return md.render(text || '')
}

function resetAi() {
  aiReport.value = ''
  aiComments.value = {}
  aiGeneratedAt.value = null
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
  if (!classId.value || aiLoading.value) return
  aiLoading.value = true
  try {
    const data = await generateClassAiReport(classId.value, { course: activeCourseId() })
    aiReport.value = data.report || ''
    aiComments.value = data.comments || {}
    aiGeneratedAt.value = data.generated_at
    if (!aiReport.value) ElMessage.warning('AI 暂未生成有效内容，请重试')
  } finally {
    aiLoading.value = false
  }
}

onMounted(loadClasses)
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
  display: flex;
  align-items: center;
  gap: 26px;
  flex: 1;
  min-width: 0;
}
.metric {
  display: grid;
  gap: 5px;
  flex: 1;
  min-width: 74px;
}
.metric-practice {
  flex: 1.8;
  min-width: 150px;
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
.stu-warnings {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
  max-width: 220px;
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
    flex-wrap: wrap;
    gap: 14px 22px;
  }
  .stu-warnings {
    justify-content: flex-start;
    max-width: none;
  }
}
</style>
