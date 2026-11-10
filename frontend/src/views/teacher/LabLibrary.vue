<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">实验管理</div>
        <div class="page-subtitle">{{ fixedCourseId ? '本课程的实验，创建后即可课程内排课发布' : '平台预置与自定义实验统一管理；自定义实验创建后即可复制接入说明给 AI 生成页面' }}</div>
      </div>
      <div class="header-actions">
        <el-button type="primary" size="small" @click="createVisible = true">新建实验</el-button>
      </div>
    </div>

    <el-card v-if="!fixedCourseId" shadow="never" class="filter-card">
      <span class="filter-label">课程筛选</span>
      <el-select v-model="courseFilter" clearable placeholder="全部课程" style="width: 240px" @change="load">
        <el-option v-for="c in courses" :key="c.id" :value="c.id" :label="c.name" />
      </el-select>
      <span class="filter-summary">共 {{ labs.length }} 个实验</span>
    </el-card>

    <!-- 课程内模式：Shell 会隐藏 page-header，操作入口放列表上方工具条 -->
    <el-card v-if="fixedCourseId" shadow="never" class="create-bar-card">
      <div class="create-bar">
        <span>新建实验：自定义上传 HTML（推荐），或选择平台预置的计算机网络实验</span>
        <el-button type="primary" size="small" @click="createVisible = true">新建实验</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="lab-library-card">
      <el-table :data="labs" v-loading="loading" :row-class-name="rowClassName">
        <el-table-column prop="title" label="实验名称" min-width="180" show-overflow-tooltip>
          <template #default="{ row }"><span class="lab-name">{{ row.title }}</span></template>
        </el-table-column>
        <el-table-column v-if="!fixedCourseId" prop="course_name" label="课程" min-width="130" show-overflow-tooltip />
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
        <el-table-column label="操作" width="300" class-name="op-col">
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

    <!-- 新建抽屉：自定义上传 / 平台预置（计算机网络实验） -->
    <LabCreateDrawer v-model="createVisible" :courses="courses" :fixed-course-id="fixedCourseId" @created="onCreated" />

    <!-- 详情弹窗：概览（含图表与成绩列表）/ 实验页面 / 成绩接口 / 排课 -->
    <el-dialog
      v-model="detailVisible"
      :title="currentLab?.title || '实验详情'"
      width="86%"
      top="4vh"
      destroy-on-close
      class="lab-detail-dialog"
    >
      <el-tabs v-if="currentLab" v-model="detailTab" class="detail-tabs">
        <el-tab-pane label="概览与成绩" name="overview">
          <div v-loading="detailLoading" class="tab-body">
            <div class="overview-toolbar">
              <el-button size="small" :loading="detailRefreshing" @click="refreshDetailData">
                <el-icon style="margin-right: 4px"><Refresh /></el-icon>刷新数据
              </el-button>
              <span class="toolbar-note">统计、图表与成绩明细按当前排课班级实时汇总</span>
            </div>
            <div class="d-grid">
              <div class="d-item"><span class="d-k">状态</span><el-tag :type="statusType(currentLab.status)" size="small">{{ statusText(currentLab.status) }}</el-tag></div>
              <div class="d-item"><span class="d-k">类型</span><span>{{ currentLab.page_source === 'custom' ? '自定义上传' : '平台预置' }}</span></div>
              <div class="d-item"><span class="d-k">课程</span><span>{{ currentLab.course_name }}</span></div>
              <div class="d-item" v-if="currentLab.page_source !== 'custom'"><span class="d-k">模板</span><span>{{ currentLab.template_title || '—' }}</span></div>
              <div class="d-item"><span class="d-k">满分</span><span>{{ currentLab.total_score }} 分（及格 {{ currentLab.pass_score }}）</span></div>
              <div class="d-item"><span class="d-k">标准时长</span><span>{{ currentLab.standard_minutes_display }} 分钟</span></div>
            </div>
            <div class="stat-cards">
              <div class="stat-box"><div class="stat-num">{{ detailStats.expected }}</div><div class="stat-label">应做人数</div></div>
              <div class="stat-box ok"><div class="stat-num">{{ detailStats.submitted }}</div><div class="stat-label">已提交</div></div>
              <div class="stat-box ing"><div class="stat-num">{{ detailStats.ongoing }}</div><div class="stat-label">进行中</div></div>
              <div class="stat-box avg"><div class="stat-num">{{ detailStats.avgScore ?? '—' }}</div><div class="stat-label">提交均分</div></div>
            </div>

            <!-- 成绩统计图表（纯 CSS/SVG，无图表库依赖；教师反馈：完成情况用饼图） -->
            <div class="chart-row">
              <div class="chart-card">
                <div class="chart-title">完成情况</div>
                <div class="pie-wrap">
                  <div
                    class="pie"
                    :style="{ background: pieGradient }"
                    role="img"
                    :aria-label="`完成情况：已提交 ${detailStats.submitted}，进行中 ${detailStats.ongoing}，未开始 ${pendingCount}`"
                  >
                    <div class="pie-hole">
                      <b>{{ detailStats.expected }}</b>
                      <span>应做人数</span>
                    </div>
                  </div>
                  <div class="legend">
                    <span><i class="dot ok" />已提交 {{ detailStats.submitted }}</span>
                    <span><i class="dot ing" />进行中 {{ detailStats.ongoing }}</span>
                    <span><i class="dot none" />未开始 {{ pendingCount }}</span>
                  </div>
                </div>
              </div>
              <div class="chart-card">
                <div class="chart-title">分数段分布（实验成绩）</div>
                <div class="bar-chart">
                  <div v-for="b in scoreBuckets" :key="b.label" class="bar-col">
                    <div class="bar-count">{{ b.count || '' }}</div>
                    <div class="bar-track"><div class="bar-fill" :style="{ height: barHeight(b.count) }" /></div>
                    <div class="bar-label">{{ b.label }}</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 成绩列表（原「成绩」Tab 内容，移到概览底部） -->
            <div class="scores-title scores-title-row">
              成绩明细
              <span class="scores-note">实验成绩 = 第一次提交（锁定不变）；重做后另记最高成绩与最短用时</span>
              <el-select
                v-if="classroomOptions.length > 1"
                v-model="detailClassroomFilter"
                clearable
                placeholder="全部班级"
                size="small"
                class="classroom-filter"
              >
                <el-option v-for="c in classroomOptions" :key="c.id" :value="c.id" :label="c.name" />
              </el-select>
            </div>
            <el-table :data="detailRows" size="small" class="score-table" :default-sort="{ prop: 'username', order: 'ascending' }">
              <el-table-column label="学生" min-width="170" prop="username" sortable :sort-method="cmpUsername">
                <template #default="{ row }">
                  <span class="stu-name">{{ row.name }}</span>
                  <span class="stu-no">{{ row.username }}</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" min-width="100" sortable :sort-method="cmpState">
                <template #default="{ row }">
                  <el-tag v-if="row.state === 'submitted'" type="success" size="small">已完成</el-tag>
                  <el-tag v-else-if="row.state === 'ongoing'" type="warning" size="small">进行中</el-tag>
                  <el-tag v-else type="info" size="small" effect="plain">未开始</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="实验成绩" min-width="105" align="center" sortable :sort-method="cmpScore">
                <template #default="{ row }">
                  <span v-if="row.total_score !== null && row.total_score !== undefined" class="score-num">{{ row.total_score }}</span>
                  <span v-else class="sub-text">—</span>
                </template>
              </el-table-column>
              <el-table-column label="用时" min-width="125" align="center" sortable :sort-method="cmpElapsed">
                <template #default="{ row }">{{ fmtDuration(row.elapsed_seconds) }}</template>
              </el-table-column>
              <el-table-column label="最高成绩" min-width="105" align="center" sortable :sort-method="cmpBest">
                <template #default="{ row }">
                  <span v-if="row.best_score !== null && row.best_score !== undefined" :class="{ 'best-score': Number(row.best_score) > Number(row.total_score ?? -1) }">{{ row.best_score }}</span>
                  <span v-else class="sub-text">—</span>
                </template>
              </el-table-column>
              <el-table-column label="最短用时" min-width="155" align="center" sortable :sort-method="cmpFastest">
                <template #default="{ row }">{{ fmtDuration(row.min_elapsed) }}</template>
              </el-table-column>
              <el-table-column label="次数" min-width="80" align="center" sortable :sort-method="cmpCount">
                <template #default="{ row }">{{ row.count || '—' }}</template>
              </el-table-column>
              <el-table-column label="最后提交" min-width="155" sortable :sort-method="cmpSubmitted">
                <template #default="{ row }">{{ row.submitted_at ? fmtDT(row.submitted_at) : '—' }}</template>
              </el-table-column>
            </el-table>
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
                v-model="pageFile"
                :lab-id="currentLab.id"
                :page="currentLab.has_custom_page ? { name: currentLab.custom_page_name } : null"
                @uploaded="onPageUploaded"
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
            <!-- Stage 11：当前排课用列表展示，支持行内编辑 -->
            <div class="schedule-block-title">当前排课</div>
            <el-table v-if="currentLab.schedules?.length" :data="currentLab.schedules" size="small" class="schedule-table">
              <el-table-column label="班级" min-width="140">
                <template #default="{ row }">
                  <span v-if="editScheduleId !== row.id">{{ row.classroom_name }}</span>
                  <el-select v-else v-model="editScheduleForm.classroom" size="small" style="width: 100%">
                    <el-option v-for="c in classes" :key="c.id" :value="c.id" :label="c.name" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="开放时间" min-width="180">
                <template #default="{ row }">
                  <span v-if="editScheduleId !== row.id">{{ row.open_at ? fmtDT(row.open_at) : '立即开放' }}</span>
                  <el-date-picker v-else v-model="editScheduleForm.open_at" type="datetime" size="small" style="width: 100%" placeholder="留空 = 立即开放" />
                </template>
              </el-table-column>
              <el-table-column label="截止时间" min-width="180">
                <template #default="{ row }">
                  <span v-if="editScheduleId !== row.id">{{ row.close_at ? fmtDT(row.close_at) : '不限制' }}</span>
                  <el-date-picker v-else v-model="editScheduleForm.close_at" type="datetime" size="small" style="width: 100%" placeholder="留空 = 不限制" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="150">
                <template #default="{ row }">
                  <template v-if="editScheduleId === row.id">
                    <el-button size="small" type="primary" :loading="scheduleSaving" @click="saveEditSchedule(row)">保存</el-button>
                    <el-button size="small" @click="cancelEditSchedule">取消</el-button>
                  </template>
                  <el-button v-else size="small" text type="primary" @click="startEditSchedule(row)">编辑</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="尚未排课：选择班级并新增排课后，学生即可进入实验" :image-size="60" />

            <div class="schedule-block-title" style="margin-top: 18px">新增排课</div>
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
                <el-button type="primary" @click="saveSchedule">新增排课</el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import request from '@/api/request'
import LabCreateDrawer from '@/components/lab/LabCreateDrawer.vue'
import LabPageUploader from '@/components/lab/LabPageUploader.vue'
import LabGradingPanel from '@/components/lab/LabGradingPanel.vue'
import {
  listLabs, getLab, deleteLab, publishLab, closeLab, listLabSchedules, updateLabSchedule,
  createLabSchedule, listLabSubmissions,
} from '@/api/labs'

// fixedCourseId：课程工作台内嵌模式（教师反馈第 1 条）——实验归属该课程，锁定课程筛选
const props = defineProps({
  fixedCourseId: { type: [Number, String], default: null },
})

const courses = ref([])
const classes = ref([])
const labs = ref([])
const loading = ref(false)
const courseFilter = ref(props.fixedCourseId ? Number(props.fixedCourseId) : null)
const createVisible = ref(false)
const detailVisible = ref(false)
const detailTab = ref('overview')
const detailLoading = ref(false)
const currentLab = ref(null)
const detailRoster = ref([])
const detailSubs = ref([])
const labStatsCache = ref({})
const scheduleForm = ref({ lab: null, classroom: null, open_at: '', close_at: '' })
// 详情内「实验页面」的待上传文件（教师反馈：选择文件后要有文件状态条并可上传替换）
const pageFile = ref(null)
function onPageUploaded() {
  pageFile.value = null
  refreshCurrent()
}

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
    // 顶级实验管理页没有分页控件：一次取到后端上限（max_page_size=100），
    // 并按 id 倒序展示，保证「刚创建的实验」永远在可见范围内；
    // 否则按模型默认 course_id/order/id 升序时新实验会落到第一页之外。
    const courseParams = courseFilter.value ? { course: courseFilter.value } : undefined
    const labParams = { ...(courseParams || {}), page_size: 100 }
    // 课程下拉同样一次取全（否则课程超过默认 20 条时，新建抽屉里选不到最新课程）。
    const requests = [listLabs(labParams)]
    if (!props.fixedCourseId) requests.push(request.get('/courses/', { params: { page_size: 100 } }))
    const [l, c] = await Promise.all(requests)
    if (c) courses.value = c.results ?? c
    labs.value = (l.results ?? l).slice().sort((a, b) => b.id - a.id)
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

/** 从花名册与提交记录聚合统计（纯函数）：班级筛选前后共用同一口径。
 *  Stage 11 计分口径：实验成绩 = 第一次提交（锁定）；重做后另记最高成绩/最短用时。 */
function computeStats(roster, subs) {
  const byStudent = new Map()
  ;(subs || []).forEach((s) => {
    if (!byStudent.has(s.student)) byStudent.set(s.student, [])
    byStudent.get(s.student).push(s)
  })
  const doneLists = [...byStudent.values()].filter((l) => l.some((s) => s.status === 'submitted'))
  const ongoing = [...byStudent.values()].length - doneLists.length
  const submitted = doneLists.length
  const firstScores = doneLists
    .map((l) => {
      const done = l.filter((s) => s.status === 'submitted')
        .sort((a, b) => String(a.submitted_at || '').localeCompare(String(b.submitted_at || '')))
      return done.length ? Number(done[0].total_score || 0) : null
    })
    .filter((n) => n !== null && Number.isFinite(n))
  const avgScore = firstScores.length ? Math.round((firstScores.reduce((a, b) => a + b, 0) / firstScores.length) * 10) / 10 : null
  return { expected: (roster || []).length, submitted, ongoing, avgScore }
}

/** 与课程空间同口径的统计（C17：external 排除步骤指标）。 */
async function fetchLabStats(lab) {
  const classroomIds = (lab.schedules || []).map((s) => s.classroom)
  if (!classroomIds.length) {
    return { expected: 0, submitted: 0, ongoing: 0, avgScore: null, roster: [], subs: [] }
  }
  const [rosterRes, subRes] = await Promise.all([
    // classroom 多值用逗号分隔（服务端支持单值/逗号/重复参数）
    request.get('/class-students/', { params: { classroom: classroomIds.join(','), learn_status: 'active', page_size: 500 } }),
    listLabSubmissions({ lab: lab.id, page_size: 500 }),
  ])
  let roster = rosterRes.results ?? rosterRes
  if (!Array.isArray(roster)) roster = []
  // 本地兜底：只保留该实验排课班级的学籍（排课班级之外的学生绝不进成绩列表）
  const allowedClassrooms = new Set(classroomIds)
  roster = roster.filter((r) => allowedClassrooms.has(r.classroom))
  const subs = subRes.results ?? subRes
  // submitted/ongoing 已是「学生数」（数字）——曾遗留 submitted.length 导致详情统计消失。
  return { ...computeStats(roster, subs), roster, subs }
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
  detailClassroomFilter.value = null
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

// 详情数据手动刷新（教师反馈）：重拉实验详情 + 学籍/提交聚合，不打断当前 Tab
const detailRefreshing = ref(false)
async function refreshDetailData() {
  if (!currentLab.value || detailRefreshing.value) return
  detailRefreshing.value = true
  try {
    const labId = currentLab.value.id
    try {
      currentLab.value = await getLab(labId)
    } catch { /* 详情回查失败保留原对象 */ }
    const st = await fetchLabStats(currentLab.value)
    labStatsCache.value = { ...labStatsCache.value, [labId]: st }
    detailRoster.value = st.roster
    detailSubs.value = st.subs
    await loadClasses(currentLab.value)
  } finally {
    detailRefreshing.value = false
  }
}

async function refreshCurrent() {
  await load()
  if (!currentLab.value) return
  // 详情必须按 id 回查，不能用「列表里找得到吗」来决定是否刷新：
  // 分页/筛选变化时当前实验可能不在列表结果里，继续用旧对象会显示
  // 「尚未上传」「无排课」等陈旧数据。
  try {
    currentLab.value = await getLab(currentLab.value.id)
  } catch { /* 拉取失败保留原详情，不阻塞操作 */ }
}

async function onCreated(lab) {
  // 新建后把筛选定位到该课程，用户立刻看到刚创建的实验。
  if (lab.course) courseFilter.value = lab.course
  await load()
  let fresh = lab
  try {
    fresh = await getLab(lab.id)
  } catch { /* 回查失败时退回创建响应，后续操作仍按 id 进行 */ }
  // 自定义实验创建成功即展示「成绩接口」Tab（设计 §6.2）
  await openDetail(fresh, fresh.page_source === 'custom' ? 'grading' : 'overview')
}

// Stage 11 计分口径聚合：实验成绩 = 第一次提交（锁定不变）；重做另记最高成绩与最短用时。
function summarizeSubs(list) {
  const done = list
    .filter((s) => s.status === 'submitted')
    .sort((a, b) => String(a.submitted_at || '').localeCompare(String(b.submitted_at || '')))
  if (!done.length) {
    const ongoing = list.find((s) => s.status !== 'submitted') || list[0] || null
    return { state: ongoing ? 'ongoing' : 'not_started', count: 0, first: null, best: null, fastest: null, last: ongoing }
  }
  let best = done[0]
  let fastest = done[0]
  for (const s of done) {
    if (Number(s.total_score) > Number(best.total_score) ||
        (Number(s.total_score) === Number(best.total_score) &&
          Number(s.elapsed_seconds ?? 1e9) < Number(best.elapsed_seconds ?? 1e9))) best = s
    if (Number(s.elapsed_seconds ?? 1e9) < Number(fastest.elapsed_seconds ?? 1e9)) fastest = s
  }
  return { state: 'submitted', count: done.length, first: done[0], best, fastest, last: done[done.length - 1] }
}

// 成绩明细排序：点表头即选排序项（再点切升降序）；空值始终排在最后
function cmpWithNull(field) {
  return (a, b) => {
    const pick = (v) => (v === null || v === undefined || v === '' ? null : Number(v))
    const x = pick(a[field])
    const y = pick(b[field])
    if (x === null && y === null) return 0
    if (x === null) return 1
    if (y === null) return -1
    return x - y
  }
}
const STATE_RANK = { not_started: 0, ongoing: 1, submitted: 2 }
const cmpState = (a, b) => (STATE_RANK[a.state] ?? 9) - (STATE_RANK[b.state] ?? 9)
const cmpScore = cmpWithNull('total_score')
const cmpElapsed = cmpWithNull('elapsed_seconds')
const cmpBest = cmpWithNull('best_score')
const cmpFastest = cmpWithNull('min_elapsed')
const cmpCount = cmpWithNull('count')
/** 学号升序：字母数字混合按字符序（数字学号在前，字母学号在后）。 */
const cmpUsername = (a, b) => {
  const x = String(a.username || '')
  const y = String(b.username || '')
  if (x === y) return 0
  return x < y ? -1 : 1
}
/** 用时列：入参秒，出参「X秒 / X分YY秒 / X时YY分」（超过 1 小时才显示小时），无数据显示 —。 */
function fmtDuration(sec) {
  if (sec === null || sec === undefined || sec === '') return '—'
  const s = Math.max(0, Math.round(Number(sec)))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  if (h) return `${h}时${String(m).padStart(2, '0')}分`
  if (m) return `${m}分${String(ss).padStart(2, '0')}秒`
  return `${ss}秒`
}
function cmpSubmitted(a, b) {
  const x = String(a.submitted_at || '')
  const y = String(b.submitted_at || '')
  if (!x && !y) return 0
  if (!x) return 1
  if (!y) return -1
  return x.localeCompare(y)
}

// 多班级筛选：成绩明细/统计只看所选班级的花名册与提交（默认全部班级）；
// 同一学生在多班时按排课口径在每个班级下分别可见。
const detailClassroomFilter = ref(null)
const classroomOptions = computed(() =>
  (currentLab.value?.schedules || []).map((s) => ({ id: s.classroom, name: s.classroom_name })))
const filteredRoster = computed(() => {
  const f = detailClassroomFilter.value
  const roster = detailRoster.value || []
  return f ? roster.filter((r) => r.classroom === f) : roster
})
const filteredSubs = computed(() => {
  const f = detailClassroomFilter.value
  const subs = detailSubs.value || []
  if (!f) return subs
  const ids = new Set(filteredRoster.value.map((r) => r.student))
  return subs.filter((s) => ids.has(s.student))
})

const detailRows = computed(() => {
  const byStudent = new Map()
  filteredSubs.value.forEach((s) => {
    if (!byStudent.has(s.student)) byStudent.set(s.student, [])
    byStudent.get(s.student).push(s)
  })
  const mkRow = (name, username, student, list) => {
    const sm = summarizeSubs(list)
    const first = sm.first || sm.last || {}
    return {
      name, username, student, sm,
      state: sm.state,
      total_score: sm.first ? sm.first.total_score : null,
      grading_source: first.grading_source,
      passed_steps: first.passed_steps,
      total_steps: first.total_steps,
      elapsed_seconds: sm.first ? sm.first.elapsed_seconds : (first.elapsed_seconds ?? null),
      submitted_at: sm.last ? sm.last.submitted_at : null,
      best_score: sm.best ? sm.best.total_score : null,
      min_elapsed: sm.fastest ? sm.fastest.elapsed_seconds : null,
      count: sm.count,
    }
  }
  const rows = []
  const seen = new Set()
  filteredRoster.value.forEach((r) => {
    const list = byStudent.get(r.student) || []
    seen.add(r.student)
    if (!list.length) return rows.push({ id: null, name: r.student_name, username: r.username, state: 'not_started' })
    rows.push(mkRow(r.student_name, r.username, r.student, list))
  })
  filteredSubs.value.forEach((s) => {
    if (!seen.has(s.student)) {
      seen.add(s.student)
      rows.push(mkRow(s.student_name, s.student_username, s.student, byStudent.get(s.student) || [s]))
    }
  })
  return rows
})
// 详情统计随班级筛选现算（口径与列表页 fetchLabStats 完全一致）
const detailStats = computed(() => computeStats(filteredRoster.value, filteredSubs.value))

// 完成情况饼图（conic-gradient 甜甜圈，教师反馈：饼图展示）
const pendingCount = computed(() =>
  Math.max(0, Number(detailStats.value.expected || 0) - Number(detailStats.value.submitted || 0) - Number(detailStats.value.ongoing || 0)))
const pieGradient = computed(() => {
  const total = Number(detailStats.value.expected || 0)
  if (!total) return 'conic-gradient(#e2e8f0 0deg 360deg)'
  const okDeg = Math.round((Number(detailStats.value.submitted || 0) / total) * 360)
  const ingDeg = Math.round((Number(detailStats.value.ongoing || 0) / total) * 360)
  return `conic-gradient(#10b981 0deg ${okDeg}deg, #f59e0b ${okDeg}deg ${okDeg + ingDeg}deg, #e2e8f0 ${okDeg + ingDeg}deg 360deg)`
})

// 分数段分布（纯 CSS 柱状）：口径 = 实验成绩（每生第一次提交锁定），
// 重做记录不重复计入——与成绩明细「实验成绩」列同源
const scoreBuckets = computed(() => {
  const buckets = [
    { label: '0-59', min: 0, max: 59.99 },
    { label: '60-69', min: 60, max: 69.99 },
    { label: '70-79', min: 70, max: 79.99 },
    { label: '80-89', min: 80, max: 89.99 },
    { label: '90-100', min: 90, max: 1000 },
  ]
  const scores = detailRows.value
    .filter((r) => r.state === 'submitted' && r.total_score !== null && r.total_score !== undefined)
    .map((r) => Number(r.total_score))
  const counts = buckets.map((b) => scores.filter((n) => n >= b.min && n <= b.max).length)
  const max = Math.max(...counts, 1)
  return buckets.map((b, i) => ({ ...b, count: counts[i], ratio: counts[i] / max }))
})
function barHeight(count) {
  const b = scoreBuckets.value.find((x) => x.count === count) || {}
  return `${Math.max(4, Math.round((b.ratio || 0) * 96))}px`
}

async function saveSchedule() {
  if (!scheduleForm.value.classroom) return ElMessage.warning('请选择班级')
  try {
    await createLabSchedule({
      ...scheduleForm.value,
      open_at: scheduleForm.value.open_at || null,
      close_at: scheduleForm.value.close_at || null,
    })
    ElMessage.success('排课已新增')
    await refreshCurrent()
  } catch (e) {
    ElMessage.error(e?.message || '排课失败')
  }
}

// Stage 11：排课行内编辑
const editScheduleId = ref(null)
const editScheduleForm = ref({ classroom: null, open_at: '', close_at: '' })
const scheduleSaving = ref(false)
function startEditSchedule(row) {
  editScheduleId.value = row.id
  editScheduleForm.value = { classroom: row.classroom, open_at: row.open_at || '', close_at: row.close_at || '' }
}
function cancelEditSchedule() {
  editScheduleId.value = null
}
async function saveEditSchedule(row) {
  if (!editScheduleForm.value.classroom) return ElMessage.warning('请选择班级')
  scheduleSaving.value = true
  try {
    await updateLabSchedule(row.id, {
      classroom: editScheduleForm.value.classroom,
      open_at: editScheduleForm.value.open_at || null,
      close_at: editScheduleForm.value.close_at || null,
    })
    ElMessage.success('排课已更新')
    editScheduleId.value = null
    await refreshCurrent()
  } catch (e) {
    ElMessage.error(e?.message || '排课更新失败')
  } finally {
    scheduleSaving.value = false
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
.create-bar-card { margin-bottom: 12px; }
.schedule-block-title { font-size: 13px; font-weight: 600; color: #334155; margin-bottom: 10px; }
.schedule-table { width: 100%; }
.create-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 13px; color: #475569; }
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
/* 操作列：4 个按钮保持单行（教师反馈第 3 条） */
.op-col :deep(.cell) { white-space: nowrap; }
.op-col :deep(.el-button + .el-button) { margin-left: 8px; }
.detail-tabs { padding: 0 6px; }
.overview-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.toolbar-note { font-size: 12px; color: #94a3b8; }
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
/* 图表（纯 CSS/SVG，教师反馈：完成情况用饼图） */
.chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 16px 0; }
.chart-card { border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px 20px; background: #fff; }
.chart-title { font-size: 13px; font-weight: 600; color: #334155; margin-bottom: 14px; }
.pie-wrap { display: flex; align-items: center; justify-content: center; gap: 40px; padding: 6px 0 2px; }
.pie {
  width: 168px; height: 168px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  box-shadow: inset 0 0 0 1px rgba(0,0,0,.04);
  flex-shrink: 0;
}
.pie-hole {
  width: 106px; height: 106px; border-radius: 50%; background: #fff;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
}
.pie-hole b { font-size: 28px; font-weight: 700; color: #1e293b; line-height: 1.2; }
.pie-hole span { font-size: 12px; color: #94a3b8; }
.legend { display: flex; flex-direction: column; gap: 12px; font-size: 13.5px; color: #475569; }
.legend .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
.dot.ok { background: #10b981; }
.dot.ing { background: #f59e0b; }
.dot.none { background: #e2e8f0; }
.bar-chart { display: flex; align-items: flex-end; gap: 18px; height: 130px; padding: 0 6px; }
.bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; }
.bar-count { font-size: 12px; color: #475569; font-weight: 600; }
.bar-track { flex: 1; width: 34px; display: flex; align-items: flex-end; background: #f8fafc; border-radius: 6px 6px 0 0; overflow: hidden; }
.bar-fill { width: 100%; background: linear-gradient(180deg, #60a5fa, #2563eb); border-radius: 6px 6px 0 0; transition: height .3s; }
.bar-label { margin-top: 6px; font-size: 11px; color: #94a3b8; }
.scores-title { font-size: 14px; font-weight: 600; color: #1e293b; margin: 6px 0 10px; padding-left: 8px; border-left: 3px solid #10b981; }
.scores-title-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.classroom-filter { margin-left: auto; width: 200px; }
/* 成绩明细：表头（含排序箭头）不换行，箭头始终跟在列名右侧 */
.score-table :deep(th .cell) { white-space: nowrap; }
.schedule-list { margin-top: 14px; }
.schedule-line { display: flex; align-items: center; gap: 8px; line-height: 1.9; }
.schedule-class { padding: 1px 8px; border-radius: 4px; background: #ecf5ff; color: #409eff; font-size: 12px; }
.schedule-time { color: #64748b; font-size: 12px; }
@media (max-width: 1100px) { .chart-row { grid-template-columns: 1fr; } }
</style>
.score-num.best-score { color: #d97706; font-weight: 700; }
.scores-note { margin-left: 10px; font-size: 12px; font-weight: 400; color: #94a3b8; }
