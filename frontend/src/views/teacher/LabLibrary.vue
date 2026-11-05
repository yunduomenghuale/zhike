<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">实验管理</div>
        <div class="page-subtitle">平台预置与自定义实验统一管理；自定义实验创建后即可复制接入说明给 AI 生成页面</div>
      </div>
      <div class="header-actions">
        <el-button type="warning" plain size="small" @click="guideDialog.open()">实验必读</el-button>
        <el-button type="primary" size="small" @click="createVisible = true">新建实验</el-button>
      </div>
    </div>

    <el-card shadow="never" class="filter-card">
      <span class="filter-label">课程筛选</span>
      <el-select v-model="courseFilter" clearable placeholder="全部课程" style="width: 240px" @change="load">
        <el-option v-for="c in courses" :key="c.id" :value="c.id" :label="c.name" />
      </el-select>
      <span class="filter-summary">共 {{ labs.length }} 个实验</span>
    </el-card>

    <el-card shadow="never" class="lab-library-card">
      <el-table :data="labs" v-loading="loading" :row-class-name="rowClassName">
        <el-table-column prop="title" label="实验名称" min-width="180" show-overflow-tooltip>
          <template #default="{ row }"><span class="lab-name">{{ row.title }}</span></template>
        </el-table-column>
        <el-table-column prop="course_name" label="课程" min-width="130" show-overflow-tooltip />
        <el-table-column label="类型" width="96">
          <template #default="{ row }">
            <el-tag :type="row.page_source === 'custom' ? 'warning' : 'info'" size="small" effect="plain">
              {{ row.page_source === 'custom' ? '自定义' : '平台预置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="调试" width="96">
          <template #default="{ row }">
            <el-tag v-if="row.page_source === 'custom'" :type="debugBadge(row).type" size="small" effect="plain">
              {{ debugBadge(row).text }}
            </el-tag>
            <span v-else class="sub-text">不适用</span>
          </template>
        </el-table-column>
        <el-table-column label="已完成" width="84" align="center">
          <template #default="{ row }"><span class="stu-done">{{ labDone(row) }}/{{ labTotalStudents(row) }}</span></template>
        </el-table-column>
        <el-table-column label="均分" width="72" align="center">
          <template #default="{ row }">
            <span v-if="labAvg(row) !== null">{{ labAvg(row) }}</span>
            <span v-else class="sub-text">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="openDetail(row)">详情</el-button>
            <el-button size="small" @click="openDetail(row, 'schedule')">排课</el-button>
            <el-button v-if="row.status === 'draft'" size="small" type="success" @click="publish(row)">发布</el-button>
            <el-button v-if="row.status === 'published'" size="small" type="warning" @click="close(row)">下线</el-button>
            <el-button v-if="row.status === 'closed'" size="small" type="success" @click="publish(row)">重新上线</el-button>
            <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建抽屉：平台预置 / 自定义上传 -->
    <LabCreateDrawer v-model="createVisible" :courses="courses" @created="onCreated" />

    <!-- 详情抽屉：概览 / 实验页面 / 成绩接口 / 排课 / 成绩 -->
    <el-drawer v-model="detailVisible" :title="currentLab?.title || '实验详情'" size="76%">
      <el-tabs v-if="currentLab" v-model="detailTab" class="detail-tabs">
        <el-tab-pane label="概览" name="overview">
          <div v-loading="detailLoading" class="tab-body">
            <div class="d-grid">
              <div class="d-item"><span class="d-k">状态</span><el-tag :type="statusType(currentLab.status)" size="small">{{ statusText(currentLab.status) }}</el-tag></div>
              <div class="d-item"><span class="d-k">类型</span><span>{{ currentLab.page_source === 'custom' ? '自定义上传' : '平台预置' }}</span></div>
              <div class="d-item"><span class="d-k">课程</span><span>{{ currentLab.course_name }}</span></div>
              <div class="d-item"><span class="d-k">模板</span><span>{{ currentLab.template_title || '—（自定义实验无模板）' }}</span></div>
              <div class="d-item"><span class="d-k">满分</span><span>{{ currentLab.total_score }} 分（及格 {{ currentLab.pass_score }}）</span></div>
              <div class="d-item"><span class="d-k">标准时长</span><span>{{ currentLab.standard_minutes_display }} 分钟</span></div>
            </div>
            <div class="stat-cards">
              <div class="stat-box"><div class="stat-num">{{ detailStats.expected }}</div><div class="stat-label">应做人数</div></div>
              <div class="stat-box ok"><div class="stat-num">{{ detailStats.submitted }}</div><div class="stat-label">已提交</div></div>
              <div class="stat-box ing"><div class="stat-num">{{ detailStats.ongoing }}</div><div class="stat-label">进行中</div></div>
              <div class="stat-box avg"><div class="stat-num">{{ detailStats.avgScore ?? '—' }}</div><div class="stat-label">提交均分</div></div>
              <div class="stat-box avg"><div class="stat-num">{{ detailStats.avgSteps ?? '—' }}</div><div class="stat-label">平均步骤通过</div></div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="实验页面" name="page">
          <div class="tab-body">
            <template v-if="currentLab.page_source === 'custom'">
              <el-alert type="info" :closable="false" show-icon title="单 HTML 自定义页面" class="page-alert">
                <template #default>页面运行在平台父页面的沙箱 iframe 内；上传后可先「预览页面」检查。当前文件：<strong>{{ currentLab.custom_page_name || '尚未上传' }}</strong><span v-if="currentLab.custom_page_size">（{{ fmtSize(currentLab.custom_page_size) }}）</span></template>
              </el-alert>
              <LabPageUploader
                :key="currentLab.id"
                :lab-id="currentLab.id"
                :page="currentLab.has_custom_page ? { name: currentLab.custom_page_name } : null"
                @uploaded="refreshCurrent"
                @changed="refreshCurrent"
              />
            </template>
            <el-empty v-else description="平台预置实验由平台统一部署页面，无需上传" />
          </div>
        </el-tab-pane>

        <el-tab-pane v-if="currentLab.page_source === 'custom'" label="成绩接口" name="grading">
          <div class="tab-body">
            <LabGradingPanel :lab-id="currentLab.id" :lab="currentLab" @updated="refreshCurrent" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="排课" name="schedule">
          <div class="tab-body">
            <el-form :model="scheduleForm" label-width="90px" style="max-width: 560px">
              <el-form-item label="班级" required>
                <el-select v-model="scheduleForm.classroom" style="width: 100%">
                  <el-option v-for="c in classes" :key="c.id" :value="c.id" :label="c.name" />
                </el-select>
              </el-form-item>
              <el-form-item label="开放时间">
                <el-date-picker v-model="scheduleForm.open_at" type="datetime" style="width: 100%" placeholder="留空 = 立即开放" />
              </el-form-item>
              <el-form-item label="截止时间">
                <el-date-picker v-model="scheduleForm.close_at" type="datetime" style="width: 100%" placeholder="留空 = 不限制" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="saveSchedule">保存排课</el-button>
              </el-form-item>
            </el-form>
            <div v-if="currentLab.schedules?.length" class="schedule-list">
              <div v-for="s in currentLab.schedules" :key="s.id" class="schedule-line">
                <span class="schedule-class">{{ s.classroom_name }}</span>
                <span class="schedule-time">{{ s.open_at ? fmtDT(s.open_at) : '立即开放' }} ~ {{ s.close_at ? fmtDT(s.close_at) : '不限制' }}</span>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="成绩" name="scores">
          <div class="tab-body">
            <el-table :data="detailRows" size="small">
              <el-table-column label="学生" min-width="130">
                <template #default="{ row }">
                  <span class="stu-name">{{ row.name }}</span>
                  <span class="stu-no">{{ row.username }}</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="80">
                <template #default="{ row }">
                  <el-tag v-if="row.state === 'submitted'" type="success" size="small">已提交</el-tag>
                  <el-tag v-else-if="row.state === 'ongoing'" type="warning" size="small">进行中</el-tag>
                  <el-tag v-else type="info" size="small" effect="plain">未开始</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="总分" width="70" align="center">
                <template #default="{ row }">
                  <span v-if="row.state === 'submitted'" class="score-num">{{ row.total_score }}</span>
                  <span v-else class="sub-text">—</span>
                </template>
              </el-table-column>
              <el-table-column label="步骤" width="72" align="center">
                <template #default="{ row }">
                  <span v-if="row.state === 'not_started'">—</span>
                  <span v-else-if="row.grading_source === 'external'" class="sub-text">不适用</span>
                  <span v-else>{{ `${row.passed_steps ?? 0}/${row.total_steps ?? '—'}` }}</span>
                </template>
              </el-table-column>
              <el-table-column label="用时" width="70" align="center">
                <template #default="{ row }">{{ row.state === 'not_started' ? '—' : `${Math.round((row.elapsed_seconds ?? 0) / 60)}分` }}</template>
              </el-table-column>
              <el-table-column label="提交时间" width="130">
                <template #default="{ row }">{{ row.submitted_at ? fmtDT(row.submitted_at) : '—' }}</template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-drawer>

    <LabGuideDialog ref="guideDialog" is-teacher-view />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/api/request'
import LabGuideDialog from '@/components/LabGuideDialog.vue'
import LabCreateDrawer from '@/components/lab/LabCreateDrawer.vue'
import LabPageUploader from '@/components/lab/LabPageUploader.vue'
import LabGradingPanel from '@/components/lab/LabGradingPanel.vue'
import {
  listLabs, deleteLab, publishLab, closeLab, listLabSchedules,
  createLabSchedule, listLabSubmissions,
} from '@/api/labs'

const courses = ref([])
const classes = ref([])
const labs = ref([])
const loading = ref(false)
const courseFilter = ref(null)
const createVisible = ref(false)
const detailVisible = ref(false)
const detailTab = ref('overview')
const detailLoading = ref(false)
const currentLab = ref(null)
const detailRoster = ref([])
const detailSubs = ref([])
const labStatsCache = ref({})
const guideDialog = ref(null)
const scheduleForm = ref({ lab: null, classroom: null, open_at: '', close_at: '' })

const statusText = (s) => ({ draft: '草稿', published: '已发布', closed: '已下线' }[s] || s)
const statusType = (s) => ({ draft: 'info', published: 'success', closed: 'warning' }[s] || 'info')

function fmtDT(t) {
  if (!t) return '—'
  const d = new Date(t)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function fmtSize(size) {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
// E2E 精确定位本次实验行（同名实验曾导致点错草稿，见 stage3-grade.md 调试记录）
const rowClassName = ({ row }) => `lab-row-${row.id}`

function debugBadge(row) {
  const d = row.last_debug
  if (!d || d.passed == null) return { text: '未验证', type: 'info' }
  return d.passed ? { text: '最近通过', type: 'success' } : { text: '最近失败', type: 'danger' }
}
function labDone(row) {
  const st = labStatsCache.value[row.id]
  return st ? st.submitted : '—'
}
function labTotalStudents(row) {
  const st = labStatsCache.value[row.id]
  return st ? st.expected : '—'
}
function labAvg(row) {
  const st = labStatsCache.value[row.id]
  return st ? st.avgScore : null
}

async function load() {
  loading.value = true
  try {
    const params = courseFilter.value ? { course: courseFilter.value } : undefined
    const [l, c] = await Promise.all([listLabs(params), request.get('/courses/', { params })])
    courses.value = c.results ?? c
    labs.value = l.results ?? l
    labs.value
      .filter((lab) => (lab.schedules || []).length)
      .forEach((lab) => {
        fetchLabStats(lab).then((st) => {
          labStatsCache.value = { ...labStatsCache.value, [lab.id]: st }
        }).catch(() => {})
      })
  } finally {
    loading.value = false
  }
}

/** 与课程空间 LabManage.vue 同口径的统计（C17：external 排除步骤指标）。 */
async function fetchLabStats(lab) {
  const classroomIds = (lab.schedules || []).map((s) => s.classroom)
  if (!classroomIds.length) {
    return { expected: 0, submitted: 0, ongoing: 0, avgScore: null, avgSteps: null, roster: [], subs: [] }
  }
  const [rosterRes, subRes] = await Promise.all([
    request.get('/class-students/', { params: { classroom: classroomIds, learn_status: 'active', page_size: 500 } }),
    listLabSubmissions({ lab: lab.id, page_size: 500 }),
  ])
  let roster = rosterRes.results ?? rosterRes
  if (!Array.isArray(roster)) roster = []
  const subs = subRes.results ?? subRes
  const submitted = subs.filter((s) => s.status === 'submitted')
  const ongoing = subs.filter((s) => s.status !== 'submitted')
  const scores = submitted.map((s) => Number(s.total_score || 0)).filter((n) => Number.isFinite(n))
  const avgScore = scores.length ? Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 10) / 10 : null
  const stepPairs = submitted.filter((s) => s.grading_source !== 'external' && s.total_steps > 0)
  const avgSteps = stepPairs.length
    ? Math.round((stepPairs.reduce((a, s) => a + s.passed_steps / s.total_steps, 0) / stepPairs.length) * 100)
    : null
  return { expected: roster.length, submitted: submitted.length, ongoing: ongoing.length, avgScore, avgSteps, roster, subs }
}

async function loadClasses(lab) {
  const res = await request.get('/classes/')
  classes.value = (res.results ?? res).filter(
    (c) => Array.isArray(c.courses) && c.courses.includes(lab.course),
  )
  let openAt = ''
  let closeAt = ''
  try {
    const sres = await listLabSchedules({ lab: lab.id })
    const mine = (sres.results ?? sres)[0]
    if (mine) {
      openAt = mine.open_at || ''
      closeAt = mine.close_at || ''
    }
  } catch { /* 拉取失败不阻塞排课 */ }
  scheduleForm.value = { lab: lab.id, classroom: null, open_at: openAt, close_at: closeAt }
}

async function openDetail(row, tab = 'overview') {
  currentLab.value = row
  detailTab.value = tab
  detailVisible.value = true
  detailLoading.value = true
  try {
    const [st] = await Promise.all([fetchLabStats(row), loadClasses(row)])
    labStatsCache.value = { ...labStatsCache.value, [row.id]: st }
    detailRoster.value = st.roster
    detailSubs.value = st.subs
  } finally {
    detailLoading.value = false
  }
}

async function refreshCurrent() {
  await load()
  if (!currentLab.value) return
  const fresh = labs.value.find((l) => l.id === currentLab.value.id)
  if (fresh) currentLab.value = fresh
}

async function onCreated(lab) {
  await load()
  const row = labs.value.find((l) => l.id === lab.id) || lab
  // 自定义实验创建成功即展示「成绩接口」Tab（设计 §6.2）
  await openDetail(row, lab.page_source === 'custom' ? 'grading' : 'overview')
}

const detailRows = computed(() => {
  const mapSub = (s, name, username) => ({
    id: s.id,
    name: name || s.student_name,
    username: username || s.student_username,
    state: s.status === 'submitted' ? 'submitted' : 'ongoing',
    total_score: s.total_score,
    grading_source: s.grading_source,
    passed_steps: s.passed_steps,
    total_steps: s.total_steps,
    elapsed_seconds: s.elapsed_seconds,
    submitted_at: s.submitted_at,
    student: s.student,
  })
  if (!detailRoster.value.length) return detailSubs.value.map((s) => mapSub(s))
  const byStudent = new Map(detailSubs.value.map((s) => [s.student, s]))
  return detailRoster.value.map((r) => {
    const s = byStudent.get(r.student)
    if (!s) return { id: null, name: r.student_name, username: r.username, state: 'not_started' }
    return mapSub(s, r.student_name, r.username)
  })
})
const detailStats = computed(() => labStatsCache.value[currentLab.value?.id] || {
  expected: 0, submitted: 0, ongoing: 0, avgScore: null, avgSteps: null,
})

async function saveSchedule() {
  if (!scheduleForm.value.classroom) return ElMessage.warning('请选择班级')
  try {
    await createLabSchedule({
      ...scheduleForm.value,
      open_at: scheduleForm.value.open_at || null,
      close_at: scheduleForm.value.close_at || null,
    })
    ElMessage.success('排课已保存')
    await refreshCurrent()
  } catch (e) {
    ElMessage.error(e?.message || '排课失败')
  }
}
async function publish(row) {
  await publishLab(row.id)
  ElMessage.success('已发布并通知班级学生')
  await load()
}
async function close(row) {
  await closeLab(row.id)
  ElMessage.success('已下线')
  await load()
}
async function remove(row) {
  await ElMessageBox.confirm(`确认删除实验「${row.title}」？`, '提示', { type: 'warning' })
  await deleteLab(row.id)
  await load()
}

onMounted(load)
</script>

<style scoped>
.header-actions { display: flex; align-items: center; gap: 10px; }
.filter-card { margin-bottom: 12px; }
.filter-label { font-size: 13px; color: #64748b; margin-right: 10px; }
.filter-summary { margin-left: 16px; font-size: 12px; color: #94a3b8; }
.lab-library-card :deep(.el-table .el-scrollbar__bar.is-horizontal) { display: block !important; }
.lab-name { font-weight: 600; color: #1e293b; }
.sub-text { color: #94a3b8; font-size: 12px; }
.stu-done { color: #475569; font-size: 13px; }
.stu-name { display: block; font-size: 13px; font-weight: 600; color: #1e293b; }
.stu-no { display: block; font-size: 12px; color: #94a3b8; }
.score-num { font-weight: 700; color: #2563eb; }
.detail-tabs { padding: 0 6px; }
.tab-body { padding: 8px 4px 20px; }
.page-alert { margin-bottom: 14px; }
.d-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px 24px;
  background: #f8fafc;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 18px;
}
.d-item { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #334155; }
.d-k { color: #94a3b8; flex-shrink: 0; }
.stat-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 12px; }
.stat-box { border-radius: 10px; padding: 14px 10px; text-align: center; background: #f8fafc; }
.stat-box .stat-num { font-size: 24px; font-weight: 700; color: #1e293b; }
.stat-box .stat-label { margin-top: 4px; font-size: 12px; color: #94a3b8; }
.stat-box.ok { background: #ecfdf5; }
.stat-box.ok .stat-num { color: #059669; }
.stat-box.ing { background: #fff7ed; }
.stat-box.ing .stat-num { color: #d97706; }
.stat-box.avg { background: #eff6ff; }
.stat-box.avg .stat-num { color: #2563eb; }
.schedule-list { margin-top: 14px; }
.schedule-line { display: flex; align-items: center; gap: 8px; line-height: 1.9; }
.schedule-class { padding: 1px 8px; border-radius: 4px; background: #ecf5ff; color: #409eff; font-size: 12px; }
.schedule-time { color: #64748b; font-size: 12px; }
</style>
