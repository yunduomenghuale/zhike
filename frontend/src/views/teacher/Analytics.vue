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
        <el-button
          class="an-history-btn an-export-btn"
          :icon="Download"
          :disabled="!classId"
          @click="openExportDialog"
        >
          导出 Excel
        </el-button>
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
      <div v-if="aiLoading || aiReport || aiFailed" class="ai-card" :class="{ 'is-loading': aiLoading }">
        <div v-if="aiLoading && !historyTask" class="ai-body">
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

      <!-- 学生列表：表格（密度优先；筛选 + 排序 + 行展开看 AI 简评/全部预警） -->
      <TableSkeleton v-if="loading" :cols="7" />
      <el-empty v-else-if="!students.length" description="班级暂无学生" />
      <template v-else>
        <div class="stu-toolbar">
          <div class="stu-toolbar-left">
            <el-input
              v-model="stuKeyword"
              class="stu-search"
              placeholder="搜索学生姓名"
              :prefix-icon="Search"
              clearable
            />
            <el-select v-model="warnFilter" class="stu-filter">
              <el-option label="全部学生" value="all" />
              <el-option label="有预警" value="warned" />
              <el-option label="状态正常" value="normal" />
            </el-select>
          </div>
          <span class="stu-count">共 {{ studentsView.length }} 人</span>
        </div>

        <el-empty v-if="!studentsView.length" description="没有符合条件的学生" :image-size="60" />
        <el-table
          v-else
          :data="studentsView"
          class="stu-table"
          scrollbar-always-on
          row-key="student_id"
          @row-click="onStuRowClick"
        >
          <!-- 展开行：AI 简评 / 无数据说明 / 全部预警（表格内放不下的信息） -->
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="stu-expand">
                <template v-if="aiComments[row.student_id]">
                  <el-icon class="stu-expand-ico" :size="13"><MagicStick /></el-icon>
                  <span>{{ aiComments[row.student_id] }}</span>
                </template>
                <span v-else-if="isNoDataStudent(row)" class="muted">暂无学习数据，未参与本次分析</span>
                <span v-else-if="aiBusy" class="muted">AI 简评生成中…</span>
                <span v-else class="muted">暂无 AI 简评</span>
                <span v-if="row.warnings.length > 2" class="stu-expand-warns">
                  全部预警：{{ row.warnings.join('、') }}
                </span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="学生" min-width="160">
            <template #default="{ row }">
              <div class="stu-cell-name">
                <span class="stu-avatar-sm" :style="{ background: avatarBg(row.name) }">
                  {{ row.name.charAt(0) }}
                </span>
                <span class="stu-name-wrap">
                  <span class="stu-name-t">{{ row.name }}</span>
                  <small v-if="isNoDataStudent(row)" class="stu-nodata">无数据</small>
                </span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="最近学习" width="110" sortable :sort-method="sortByLastActive">
            <template #default="{ row }">
              <span class="stu-dim" :title="fmtDateTime(row.last_active)">{{ fmtRelative(row.last_active) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="章节练习" width="170" sortable :sort-method="sortByAccuracy">
            <template #default="{ row }">
              <div v-if="row.practice_total" class="stu-prac">
                <div class="stu-prac-line">
                  <span class="stu-prac-num">{{ row.practice_correct }}/{{ row.practice_total }} 题</span>
                  <span class="stu-prac-acc" :style="{ color: accColor(row.accuracy) }">{{ row.accuracy }}%</span>
                </div>
                <el-progress
                  :percentage="row.accuracy"
                  :stroke-width="5"
                  :color="accColor(row.accuracy)"
                  :show-text="false"
                  class="stu-prac-bar"
                />
              </div>
              <span v-else class="stu-none">未做练习</span>
            </template>
          </el-table-column>
          <el-table-column label="作业" width="92" align="center" sortable :sort-method="sortByRate('homework')">
            <template #default="{ row }">
              <strong class="stu-val" :class="{ warn: row.homework_submitted < row.homework_total }">
                {{ row.homework_submitted }}/{{ row.homework_total }}
              </strong>
            </template>
          </el-table-column>
          <el-table-column label="考试" width="132" sortable :sort-method="sortByRate('exam')">
            <template #default="{ row }">
              <strong class="stu-val">
                {{ row.exam_taken }}/{{ row.exam_total }}
                <span v-if="row.avg_exam_score !== null" class="stu-score">· 均分 {{ row.avg_exam_score }}</span>
              </strong>
            </template>
          </el-table-column>
          <el-table-column label="实验" width="126" sortable :sort-method="sortByRate('experiment')">
            <template #default="{ row }">
              <strong class="stu-val" :class="{ warn: row.experiment_done < row.experiment_total }">
                {{ row.experiment_done }}/{{ row.experiment_total }}
                <span v-if="row.avg_experiment_score !== null" class="stu-score">· 均分 {{ row.avg_experiment_score }}</span>
              </strong>
            </template>
          </el-table-column>
          <el-table-column label="预警" min-width="150">
            <template #default="{ row }">
              <div v-if="row.warnings.length" class="stu-warn-cell" :title="row.warnings.join('、')">
                <el-tag
                  v-for="w in row.warnings.slice(0, 2)"
                  :key="w"
                  type="danger"
                  size="small"
                  effect="light"
                  round
                  class="warn-pulse"
                  >{{ w }}</el-tag
                >
                <el-tag v-if="row.warnings.length > 2" type="info" size="small" effect="light" round>
                  +{{ row.warnings.length - 2 }}
                </el-tag>
              </div>
              <el-tag v-else type="success" size="small" effect="light" round>正常</el-tag>
            </template>
          </el-table-column>
          <el-table-column width="52" align="center">
            <template #default>
              <el-icon class="stu-go" :size="15"><ArrowRight /></el-icon>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </template>

    <!-- 导出学习数据：先配置范围与内容再导出（避免"点了就全量下载"的盲盒体验） -->
    <el-dialog
      v-model="exportVisible"
      title="导出学习数据"
      width="560px"
      class="an-export-dialog"
      :close-on-click-modal="false"
    >
      <div class="exp-block">
        <div class="exp-label">时间范围</div>
        <el-radio-group v-model="exportPreset" class="exp-presets">
          <el-radio-button value="all">全部时间</el-radio-button>
          <el-radio-button value="7d">近 7 天</el-radio-button>
          <el-radio-button value="30d">近 30 天</el-radio-button>
          <el-radio-button value="custom">自定义</el-radio-button>
        </el-radio-group>
        <el-date-picker
          v-if="exportPreset === 'custom'"
          v-model="exportRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          class="exp-range"
        />
        <div class="exp-hint">{{ exportRangeHint }}</div>
      </div>

      <div class="exp-block">
        <div class="exp-label">
          导出内容
          <el-checkbox
            class="exp-all"
            :model-value="allSectionsChecked"
            :indeterminate="someSectionsChecked"
            @change="toggleAllSections"
          >
            全选
          </el-checkbox>
        </div>
        <el-checkbox-group v-model="exportSections" class="exp-sections">
          <el-checkbox
            v-for="s in SECTION_OPTIONS"
            :key="s.key"
            :value="s.key"
            :disabled="s.key === 'overview'"
          >
            {{ s.label }}
          </el-checkbox>
        </el-checkbox-group>
        <div class="exp-hint">{{ exportSummaryHint }}</div>
      </div>

      <template #footer>
        <el-button @click="exportVisible = false">取消</el-button>
        <el-button type="primary" :loading="exporting" @click="doExport">开始导出</el-button>
      </template>
    </el-dialog>

    <!-- 历史报告列表（按 AITask 查，点击回看完整报告） -->
    <el-dialog v-model="historyVisible" title="历史报告" width="720px" class="an-history-dialog">
      <div v-loading="historyLoading" class="history-list">
        <div v-if="!historyLoading && historyList.length" class="history-hint">
          共 {{ historyList.length }} 份报告，点击任意一条可回看全文
        </div>
        <el-empty v-if="!historyLoading && !historyList.length" description="暂无历史报告" :image-size="60" />
        <div
          v-for="r in historyList"
          :key="r.task_id"
          class="history-item"
          :class="{ 'is-failed': r.status !== 'success', 'is-clickable': r.status === 'success' }"
          @click="viewHistory(r)"
        >
          <div class="history-item-head">
            <div class="history-item-tags">
              <el-tag :type="statusType(r.status)" size="small" effect="light" round>{{ statusText(r.status) }}</el-tag>
              <el-tag v-if="r.degraded" type="warning" size="small" effect="light" round>部分降级</el-tag>
            </div>
            <span class="history-time" :title="fmtDateTime(r.generated_at || r.created_at)">{{ fmtRelative(r.generated_at || r.created_at) }}</span>
            <el-icon v-if="r.status === 'success'" class="history-item-go" :size="14"><ArrowRight /></el-icon>
          </div>
          <div class="history-item-meta">
            <span v-if="r.analyzed_count != null" class="history-chip">分析 {{ r.analyzed_count }} 人</span>
            <span v-if="r.comment_count" class="history-chip">简评 {{ r.comment_count }} 条</span>
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
import { MagicStick, Loading, WarningFilled, Clock, Search, ArrowRight, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { renderAiMarkdown } from '@/utils/markdown'
import { sortedCourseNames } from '@/utils/course-sort'
import { listClasses } from '@/api/classroom'
import { getClassStats, generateClassAiReport, getClassAiReportHistory, downloadClassExport } from '@/api/analytics'
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
// 恢复中：刷新/切班后正在从服务端找回进行中的任务，先展示占位过程，别留空白
const aiRestoring = ref(false)
const aiLoading = computed(() => aiBusy.value || aiRestoring.value)
const aiProgressMsg = computed(() => {
  if (aiSubmitting.value) return '正在提交分析任务…'
  if (aiRestoring.value) return '正在恢复分析进度…'
  return aiTask.value?.progress?.message || 'AI 正在分析班级数据，请稍候…'
})
const aiProgressPct = computed(() => {
  if (aiSubmitting.value || aiRestoring.value) return null
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

// ---- 学生列表筛选/排序（表格化后本地处理，班级数据量小） ----
const stuKeyword = ref('')
const warnFilter = ref('all')
const studentsView = computed(() => {
  const kw = stuKeyword.value.trim()
  return students.value.filter((s) => {
    if (kw && !String(s.name || '').includes(kw)) return false
    if (warnFilter.value === 'warned' && !s.warnings.length) return false
    if (warnFilter.value === 'normal' && s.warnings.length) return false
    return true
  })
})
// 从未学习排最后：时间列 null 记 0，倒序时自然沉底
function sortByLastActive(a, b) {
  const ta = a.last_active ? new Date(a.last_active).getTime() : 0
  const tb = b.last_active ? new Date(b.last_active).getTime() : 0
  return ta - tb
}
function sortByAccuracy(a, b) {
  return (a.accuracy ?? -1) - (b.accuracy ?? -1)
}
// 完成率排序；无对应数据（total=0）记 -1 沉底
function sortByRate(key) {
  const pick = {
    homework: (s) => (s.homework_total ? s.homework_submitted / s.homework_total : -1),
    exam: (s) => (s.exam_total ? s.exam_taken / s.exam_total : -1),
    experiment: (s) => (s.experiment_total ? s.experiment_done / s.experiment_total : -1),
  }[key]
  return (a, b) => pick(a) - pick(b)
}
// 行点击进详情；展开图标只切换展开不跳转
function onStuRowClick(row, _column, event) {
  if (event?.target?.closest?.('.el-table__expand-icon')) return
  goDetail(row)
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
    resumeActiveTask() // 不 await：与 stats 并行，尽早恢复进度 UI
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
  resumeActiveTask() // 切班也可能有进行中的任务，同样恢复
}

// ---- 导出 Excel：弹窗先配置时间范围与内容（默认全量 + 全选，选择记忆到 localStorage）----
const SECTION_OPTIONS = [
  { key: 'overview', label: '成绩总览' },
  { key: 'homework', label: '作业明细' },
  { key: 'exam', label: '考试明细' },
  { key: 'lab', label: '实验明细' },
  { key: 'practice', label: '练习与错题' },
  { key: 'qa', label: '问答与视频' },
  { key: 'chapter', label: '章节矩阵' },
]
const ALL_SECTION_KEYS = SECTION_OPTIONS.map((s) => s.key)
const EXPORT_PREF_KEY = 'zhike.classExportPrefs'

const exportVisible = ref(false)
const exporting = ref(false)
const exportPreset = ref('all')
const exportRange = ref(null)
const exportSections = ref([...ALL_SECTION_KEYS])

const allSectionsChecked = computed(() => exportSections.value.length === SECTION_OPTIONS.length)
const someSectionsChecked = computed(
  () => exportSections.value.length > 0 && !allSectionsChecked.value
)
function toggleAllSections(checked) {
  exportSections.value = checked ? [...ALL_SECTION_KEYS] : ['overview']
}

function fmtDay(d) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
// 预设 → { start, end }（近 N 天含今天）；custom 无选择返回 null
function presetRange(preset) {
  if (preset === 'all') return {}
  const today = new Date()
  if (preset === '7d' || preset === '30d') {
    const start = new Date(today)
    start.setDate(today.getDate() - (preset === '7d' ? 6 : 29))
    return { start: fmtDay(start), end: fmtDay(today) }
  }
  const r = exportRange.value
  if (!Array.isArray(r) || !r[0]) return null
  return { start: r[0], end: r[1] }
}

// 范围文案：让教师明确「这次导的是哪段时间的数据」
const exportRangeHint = computed(() => {
  const r = presetRange(exportPreset.value)
  if (r === null) return '请选择开始与结束日期（含首尾两天）'
  if (!r.start) return '全部时间：导出该班全部历史学习数据'
  if (exportPreset.value === 'custom') return `${r.start} ~ ${r.end}`
  return `${r.start} ~ ${r.end}（近 ${exportPreset.value === '7d' ? 7 : 30} 天）`
})

const exportSummaryHint = computed(() => {
  const labels = SECTION_OPTIONS.filter((s) => exportSections.value.includes(s.key)).map((s) => s.label)
  const stu = students.value.length
  // 任务规模取自班级统计（每生行的 homework_total / exam_total / experiment_total 是同一份清单长度）
  const first = students.value[0] || {}
  const parts = []
  if (exportSections.value.includes('homework') && first.homework_total) parts.push(`作业 ${first.homework_total} 次`)
  if (exportSections.value.includes('exam') && first.exam_total) parts.push(`考试 ${first.exam_total} 场`)
  if (exportSections.value.includes('lab') && first.experiment_total) parts.push(`实验 ${first.experiment_total} 个`)
  const scale = parts.length ? `（${parts.join(' · ')}）` : ''
  return `将导出 ${stu} 名学生 · ${labels.length} 个表：${labels.join('、')}${scale}`
})

function loadExportPrefs() {
  try {
    const raw = localStorage.getItem(EXPORT_PREF_KEY)
    if (!raw) return
    const prefs = JSON.parse(raw) || {}
    if (['all', '7d', '30d', 'custom'].includes(prefs.preset)) exportPreset.value = prefs.preset
    if (Array.isArray(prefs.sections) && prefs.sections.length) {
      const valid = prefs.sections.filter((k) => ALL_SECTION_KEYS.includes(k))
      exportSections.value = Array.from(new Set(['overview', ...valid]))
    }
  } catch {
    // 本地偏好损坏则用默认值，不影响导出
  }
}
function saveExportPrefs() {
  try {
    localStorage.setItem(
      EXPORT_PREF_KEY,
      JSON.stringify({ preset: exportPreset.value, sections: exportSections.value })
    )
  } catch {
    // 存不了就算了（隐私模式）
  }
}

function openExportDialog() {
  if (!classId.value) return
  loadExportPrefs()
  exportVisible.value = true
}

async function doExport() {
  if (!classId.value || exporting.value) return
  const range = presetRange(exportPreset.value)
  if (range === null) {
    ElMessage.warning('请选择时间范围')
    return
  }
  exportSections.value = Array.from(new Set(['overview', ...exportSections.value]))
  saveExportPrefs()
  exporting.value = true
  try {
    const params = { sheets: exportSections.value.join(',') }
    if (activeCourseId()) params.course = activeCourseId()
    if (range.start) {
      params.start = range.start
      params.end = range.end
    }
    await downloadClassExport(classId.value, params)
    exportVisible.value = false
    ElMessage.success('导出成功')
  } catch (err) {
    let msg = '导出失败'
    const data = err?.response?.data
    if (data instanceof Blob) {
      try {
        msg = JSON.parse(await data.text())?.message || msg
      } catch {
        // 非 JSON 错误体，保持默认提示
      }
    }
    ElMessage.error(msg)
  } finally {
    exporting.value = false
  }
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

// 刷新页面/切换班级后恢复进行中的分析任务（异步任务刷新续看）：
// 任务行在服务端持久化，刷新丢失的只是前端的任务 ID——从历史报告接口
// 找回该班、当前课程最新的 pending/running 任务，重新拉起轮询与进度 UI。
// 请求在途期间展示「正在恢复分析进度…」占位，避免刷新后一两秒的空白。
// 陈旧保护：创建超过 12 分钟仍未终态，视为服务端已中断（后台线程已死、
// 任务行停留在 running），直接展示失败+重试，避免对着死任务空轮 10 分钟。
async function resumeActiveTask() {
  const myClassId = classId.value
  if (!myClassId) return
  aiRestoring.value = true
  try {
    const data = await getClassAiReportHistory(myClassId)
    if (classId.value !== myClassId) return // 期间用户切了班：丢弃
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
  } finally {
    if (classId.value === myClassId) aiRestoring.value = false
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
/* ===== 导出配置弹窗 ===== */
.exp-block {
  margin-bottom: 18px;
}
.exp-block:last-child {
  margin-bottom: 0;
}
.exp-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-700);
}
.exp-presets {
  width: 100%;
}
.exp-range {
  width: 100% !important;
  margin-top: 10px;
}
.exp-hint {
  margin-top: 8px;
  color: var(--gray-400);
  font-size: 12.5px;
  line-height: 1.6;
}
.exp-all {
  font-weight: 400;
  font-size: 12.5px;
}
.exp-sections {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 0;
}
.exp-sections :deep(.el-checkbox) {
  width: 33.33%;
  margin-right: 0;
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
  cursor: default;
}
.history-hint {
  color: var(--gray-400);
  font-size: 12px;
  line-height: 1.5;
}
.history-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.history-item-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.history-time {
  margin-left: auto;
  color: var(--gray-400);
  font-size: 12px;
  white-space: nowrap;
}
.history-item-go {
  flex: none;
  color: var(--gray-300);
  transition: color 0.18s ease, transform 0.18s ease;
}
.history-item.is-clickable:hover .history-item-go {
  color: var(--primary-500);
  transform: translateX(2px);
}
.history-item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.history-chip {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--gray-100);
  color: var(--gray-600);
  font-size: 12px;
  line-height: 1.7;
}
.history-excerpt {
  margin-top: 6px;
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
/* 摘要按 markdown 渲染：标题/加粗 compact 化，配合外层 2 行夹取 */
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

/* ===== 学生列表（表格：密度优先，筛选 / 排序 / 行展开） ===== */
.stu-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.stu-toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.stu-search {
  width: 200px;
}
.stu-filter {
  width: 128px;
}
.stu-count {
  color: var(--gray-400);
  font-size: 12.5px;
  white-space: nowrap;
}
.stu-table {
  width: 100%;
}
/* 窄列 nowrap + 悬停 title（与项目表格口径一致）；展开行内容不受影响 */
.stu-table :deep(.cell) {
  white-space: nowrap;
}
.stu-table :deep(.el-table__row) {
  cursor: pointer;
}
.stu-table :deep(.el-table__expand-icon) {
  cursor: pointer;
}
/* 学生名列 */
.stu-cell-name {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}
.stu-avatar-sm {
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}
.stu-name-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.stu-name-t {
  color: var(--gray-900);
  font-size: 13.5px;
  font-weight: 650;
}
.stu-nodata {
  padding: 0 5px;
  border-radius: 4px;
  background: var(--gray-100);
  color: var(--gray-400);
  font-size: 11px;
  font-style: normal;
}
/* 指标列 */
.stu-dim {
  color: var(--gray-500);
  font-size: 12.5px;
}
.stu-none {
  color: var(--gray-300);
  font-size: 12.5px;
}
.stu-val {
  color: var(--gray-800);
  font-size: 13.5px;
  font-weight: 700;
}
.stu-val.warn {
  color: var(--danger);
}
.stu-score {
  margin-left: 2px;
  color: var(--primary-600);
  font-size: 12px;
  font-weight: 600;
}
.stu-prac {
  display: grid;
  gap: 3px;
  min-width: 132px;
}
.stu-prac-line {
  display: flex;
  align-items: center;
  gap: 8px;
}
.stu-prac-num {
  color: var(--gray-700);
  font-size: 12.5px;
}
.stu-prac-acc {
  font-size: 12.5px;
  font-weight: 700;
}
.stu-prac-bar {
  width: 100%;
}
.stu-prac-bar :deep(.el-progress-bar__outer) {
  background: var(--gray-100);
}
/* 预警列：横排最多 2 个 +N，全部悬停/展开可见 */
.stu-warn-cell {
  display: flex;
  align-items: center;
  gap: 5px;
}
/* 行尾箭头 */
.stu-go {
  color: var(--gray-300);
  transition: color 0.15s ease;
}
.stu-table :deep(.el-table__row):hover .stu-go {
  color: var(--primary-500);
}
/* 展开行：AI 简评 / 无数据说明 / 全部预警 */
.stu-expand {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 4px 14px;
  padding: 2px 16px 8px 52px;
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.65;
}
.stu-expand-ico {
  flex-shrink: 0;
  margin-top: 4px;
  color: #8b5cf6;
}
.stu-expand .muted {
  color: var(--gray-400);
}
.stu-expand-warns {
  color: var(--danger);
}
</style>
