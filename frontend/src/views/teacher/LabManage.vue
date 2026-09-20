<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">虚拟实验</div>
        <div class="page-subtitle">引用平台实验模板创建实验，排课后学生按窗口进入</div>
      </div>
      <el-button type="warning" plain size="small" @click="guideDialog.open()">实验必读</el-button>
    </div>

    <!-- 新建实验：选模板 → 绑课程 → 覆盖配置（按钮内联在最后一行右侧，不单独占行） -->
    <el-card shadow="never" class="mb12">
      <template #header><span>新建实验</span></template>
      <el-form :model="form" label-width="100px" style="max-width: 720px">
        <el-form-item label="实验模板" required>
          <el-select v-model="form.template" placeholder="选择平台预置实验" style="width: 100%">
            <el-option v-for="t in templates" :key="t.id" :value="t.id" :label="t.title" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属课程">
          <el-input :model-value="currentCourseName" disabled>
            <template #append>当前课程</template>
          </el-input>
        </el-form-item>
        <el-form-item label="实验名称">
          <el-input v-model="form.title" placeholder="留空默认使用模板名称" />
        </el-form-item>
        <el-form-item label="标准时长">
          <el-input-number v-model="form.standard_minutes" :min="5" :max="180" placeholder="分钟" />
        </el-form-item>
        <el-form-item>
          <template #label>
            <span class="weight-label">题目权重</span>
            <el-tooltip placement="top" effect="light">
              <template #content>
                <div class="weight-tip">
                  <p><b>0</b> = 纯实验步骤评分（基础分+准确性+效率+完成度）</p>
                  <p><b>0.3</b> = 实验步骤分 × 0.7 + 附加题得分 × 0.3</p>
                  <p>取值 0~1，附加题越多建议权重越大</p>
                </div>
              </template>
              <el-icon class="tip-ico"><QuestionFilled /></el-icon>
            </el-tooltip>
          </template>
          <div class="weight-row">
            <el-input-number v-model="form.question_weight" :min="0" :max="1" :step="0.1" />
            <el-button class="create-btn" type="primary" :loading="creating" @click="create">创建实验</el-button>
          </div>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 我的实验列表 -->
    <el-card shadow="never">
      <template #header><span>我的实验</span></template>
      <el-table :data="labs" v-loading="loading">
        <el-table-column prop="title" label="实验" min-width="200" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="学生完成" width="100" align="center">
          <template #default="{ row }">
            <span class="stu-done">{{ labDone(row) }}/{{ labTotalStudents(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="班级均分" width="90" align="center">
          <template #default="{ row }">
            <span v-if="labAvg(row) !== null">{{ labAvg(row) }}</span>
            <span v-else class="stu-done">—</span>
          </template>
        </el-table-column>
        <el-table-column label="排课窗口" min-width="220">
          <template #default="{ row }">
            <template v-if="row.schedules?.length">
              <div v-for="s in row.schedules" :key="s.id" class="schedule-line">
                <span class="schedule-class">{{ s.classroom_name }}</span>
                <span class="schedule-time">
                  {{ s.open_at ? fmtDT(s.open_at) : '未设时间' }} ~ {{ s.close_at ? fmtDT(s.close_at) : '未设时间' }}
                </span>
              </div>
            </template>
            <span v-else class="schedule-none">未排课</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="openDetail(row)">详情</el-button>
            <el-button size="small" @click="openSchedule(row)">排课</el-button>
            <el-button v-if="row.status === 'draft'" size="small" type="success" @click="publish(row)">发布</el-button>
            <el-button v-if="row.status === 'published'" size="small" type="warning" @click="close(row)">下线</el-button>
            <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 排课弹窗 -->
    <el-dialog v-model="scheduleVisible" title="排课（班级开放窗口）" width="560">
      <el-alert
        v-if="scheduleForm.id"
        type="info"
        :closable="false"
        show-icon
        title="该实验已有排课记录，保存后将更新所选班级的开放窗口"
        style="margin-bottom: 12px"
      />
      <el-form :model="scheduleForm" label-width="90px">
        <el-form-item label="班级" required>
          <el-select v-model="scheduleForm.classroom" style="width: 100%">
            <el-option v-for="c in classes" :key="c.id" :value="c.id" :label="c.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="开放时间" required>
          <el-date-picker v-model="scheduleForm.open_at" type="datetime" style="width: 100%" />
        </el-form-item>
        <el-form-item label="截止时间" required>
          <el-date-picker v-model="scheduleForm.close_at" type="datetime" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="scheduleVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSchedule">保存</el-button>
      </template>
    </el-dialog>

    <!-- 实验详情抽屉：概况 + 学生完成统计 + 逐学生成绩 -->
    <el-drawer v-model="detailVisible" :title="currentLab?.title || '实验详情'" size="72%">
      <div v-loading="detailLoading" class="detail-body">
        <template v-if="currentLab">
          <!-- 实验概况 -->
          <div class="d-section">
            <div class="d-title">实验概况</div>
            <div class="d-grid">
              <div class="d-item"><span class="d-k">状态</span><el-tag :type="statusType(currentLab.status)" size="small">{{ statusText(currentLab.status) }}</el-tag></div>
              <div class="d-item"><span class="d-k">实验模板</span><span>{{ currentLab.template_title }}</span></div>
              <div class="d-item"><span class="d-k">满分</span><span>{{ currentLab.total_score }} 分（及格 {{ currentLab.pass_score }}）</span></div>
              <div class="d-item"><span class="d-k">标准时长</span><span>{{ currentLab.standard_minutes_display }} 分钟</span></div>
              <div class="d-item"><span class="d-k">题目权重</span><span>{{ currentLab.question_weight > 0 ? currentLab.question_weight : '纯步骤评分' }}</span></div>
              <div class="d-item"><span class="d-k">允许重做</span><span>{{ currentLab.allow_resubmit ? '是' : '否' }}</span></div>
            </div>
          </div>

          <!-- 学生完成统计 -->
          <div class="d-section">
            <div class="d-title">学生完成统计</div>
            <div class="stat-cards">
              <div class="stat-box">
                <div class="stat-num">{{ detailStats.expected }}</div>
                <div class="stat-label">应做人数</div>
              </div>
              <div class="stat-box ok">
                <div class="stat-num">{{ detailStats.submitted }}</div>
                <div class="stat-label">已提交</div>
              </div>
              <div class="stat-box ing">
                <div class="stat-num">{{ detailStats.ongoing }}</div>
                <div class="stat-label">进行中</div>
              </div>
              <div class="stat-box miss">
                <div class="stat-num">{{ detailStats.notStarted }}</div>
                <div class="stat-label">未开始</div>
              </div>
              <div class="stat-box avg">
                <div class="stat-num">{{ detailStats.avgScore ?? '—' }}</div>
                <div class="stat-label">提交均分</div>
              </div>
              <div class="stat-box avg">
                <div class="stat-num">{{ detailStats.avgSteps ?? '—' }}</div>
                <div class="stat-label">平均步骤通过</div>
              </div>
            </div>
            <el-progress
              v-if="detailStats.expected"
              :percentage="detailStats.submitRate"
              :stroke-width="10"
              :color="'#10b981'"
              :format="(p) => `提交率 ${p}%`"
              style="margin-top: 10px"
            />
          </div>

          <!-- 逐学生成绩 -->
          <div class="d-section">
            <div class="d-title">学生成绩</div>
            <el-table :data="detailRows" size="small">
              <el-table-column label="学生" min-width="100">
                <template #default="{ row }">{{ row.name }}<span class="sub-text">{{ row.username }}</span></template>
              </el-table-column>
              <el-table-column label="状态" width="84">
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
              <el-table-column label="步骤" width="70" align="center">
                <template #default="{ row }">{{ row.state === 'not_started' ? '—' : `${row.passed_steps ?? 0}/${row.total_steps ?? '—'}` }}</template>
              </el-table-column>
              <el-table-column prop="error_count" label="错误" width="56" align="center">
                <template #default="{ row }">{{ row.state === 'not_started' ? '—' : (row.error_count ?? 0) }}</template>
              </el-table-column>
              <el-table-column label="用时" width="66" align="center">
                <template #default="{ row }">
                  {{ row.state === 'not_started' ? '—' : `${Math.round((row.elapsed_seconds ?? 0) / 60)}分` }}
                </template>
              </el-table-column>
              <el-table-column label="提交时间" width="120">
                <template #default="{ row }">{{ row.submitted_at ? fmtDT(row.submitted_at) : '—' }}</template>
              </el-table-column>
              <el-table-column label="批阅" width="84">
                <template #default="{ row }">
                  <el-tag v-if="row.reviewed" type="success" size="small" effect="plain">已批阅</el-tag>
                  <span v-else class="sub-text">—</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="150" fixed="right">
                <template #default="{ row }">
                  <template v-if="row.state === 'submitted'">
                    <el-button size="small" link type="primary" @click="openReview(row)">批阅打分</el-button>
                    <el-button size="small" link type="warning" @click="reset(row)">重置</el-button>
                  </template>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </div>
    </el-drawer>

    <!-- 批阅抽屉：步骤分 + 附加题逐题作答与评分 -->
    <el-drawer v-model="reviewVisible" :title="`批阅 - ${currentSub?.name || ''}`" size="62%">
      <div v-loading="reviewLoading" class="detail-body">
        <template v-if="currentSub">
          <!-- 步骤分概况（只读，服务端计算） -->
          <div class="d-section">
            <div class="d-title">步骤评分（系统按过程数据计算）</div>
            <div class="d-grid">
              <div class="d-item"><span class="d-k">总分</span><span class="score-num">{{ currentSub.total_score ?? '—' }}</span></div>
              <div class="d-item"><span class="d-k">基础分</span><span>{{ bkOf(currentSub).base ?? '—' }} / {{ bkOf(currentSub).max_base ?? '—' }}</span></div>
              <div class="d-item"><span class="d-k">准确性</span><span>{{ bkOf(currentSub).accuracy ?? '—' }} / 5</span></div>
              <div class="d-item"><span class="d-k">效率</span><span>{{ bkOf(currentSub).efficiency ?? '—' }} / 5</span></div>
              <div class="d-item"><span class="d-k">完成度</span><span>{{ bkOf(currentSub).completion ?? '—' }} / 10</span></div>
              <div class="d-item"><span class="d-k">错误次数</span><span>{{ currentSub.error_count ?? 0 }}</span></div>
              <div class="d-item"><span class="d-k">用时</span><span>{{ Math.round((currentSub.elapsed_seconds ?? 0) / 60) }} 分钟</span></div>
            </div>
          </div>

          <!-- 附加题逐题批阅 -->
          <div class="d-section">
            <div class="d-title">附加题作答（{{ qAnswers.length }} 题）</div>
            <el-alert
              v-if="!qAnswers.length"
              type="info" :closable="false" show-icon
              title="该实验未附加题目或学生尚未作答，直接提交总分即可"
            />
            <div v-for="qa in qAnswers" :key="qa.id" class="qa-card">
              <div class="qa-head">
                <el-tag size="small" effect="plain">{{ qa.lab_question?.qtype_display || qa.lab_question?.qtype || '题' }}</el-tag>
                <span class="qa-stem">{{ qa.lab_question?.stem || '(无题干)' }}</span>
                <span class="qa-score-tag">{{ qa.lab_question?.score }} 分</span>
              </div>
              <div class="qa-body">
                <div class="qa-row">
                  <span class="d-k">学生作答</span>
                  <span class="qa-text">{{ answerText(qa) || '（未作答）' }}</span>
                </div>
                <div class="qa-row">
                  <span class="d-k">参考答案</span>
                  <span class="qa-text qa-ref">{{ refAnswerText(qa) || '—' }}</span>
                </div>
                <div class="qa-row">
                  <span class="d-k">系统预评</span>
                  <span>
                    {{ qa.auto_score ?? '—' }} 分
                    <span v-if="qa.similarity != null" class="sub-text">相似度 {{ (Number(qa.similarity) * 100).toFixed(0) }}%</span>
                    <span class="sub-text">{{ qa.auto_comment }}</span>
                    <el-tag v-if="qa.pending_review" size="small" type="warning" effect="light" style="margin-left: 6px">待批阅</el-tag>
                  </span>
                </div>
                <div class="qa-row qa-grade">
                  <span class="d-k">教师评分</span>
                  <el-input-number
                    v-model="reviewScores[qa.lab_question?.id]"
                    :min="0"
                    :max="Number(qa.lab_question?.score || 5)"
                    :step="0.5"
                    size="small"
                  />
                </div>
              </div>
            </div>
          </div>

          <!-- 评语 -->
          <div class="d-section">
            <div class="d-title">评语</div>
            <el-form label-width="90px" style="max-width: 520px">
              <el-form-item label="评语">
                <el-input v-model="reviewForm.comment" type="textarea" :rows="3" placeholder="写给学生的评语（可选）" />
              </el-form-item>
            </el-form>
            <el-alert
              type="info" :closable="false" show-icon
              title="提交后系统按题目评分自动重算附题得分并合成总分，教师无需手动改总分"
            />
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="reviewVisible = false">取消</el-button>
        <el-button :loading="reviewSaving" type="primary" @click="saveReview">提交批阅（将通知学生）</el-button>
      </template>
    </el-drawer>

    <!-- 实验必读管理弹窗（教师：可编辑/恢复预设） -->
    <LabGuideDialog ref="guideDialog" is-teacher-view />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import request from '@/api/request'
import LabGuideDialog from '@/components/LabGuideDialog.vue'
import {
  listLabs, createLab, deleteLab, publishLab, closeLab,
  listLabTemplates, listLabSchedules, createLabSchedule,
  listLabSubmissions, reviewLabSubmission, resetLabSubmission,
  getLabAnswers, gradeLabSubmission,
} from '@/api/labs'

const route = useRoute()
const fixedCourseId = computed(() => Number(route.params.id) || null)
// 课程空间内新建实验：课程固定为当前路由课程，无需选择
const currentCourseName = computed(
  () => courses.value.find((c) => c.id === fixedCourseId.value)?.name || `课程 #${fixedCourseId.value}`,
)

const templates = ref([])
const courses = ref([])
const classes = ref([])
const labs = ref([])
const loading = ref(false)
const creating = ref(false)

const form = ref({ template: null, title: '', standard_minutes: 30, question_weight: 0 })

const scheduleVisible = ref(false)
const scheduleForm = ref({ lab: null, classroom: null, open_at: '', close_at: '' })
const currentLab = ref(null)

// 详情抽屉
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailRoster = ref([])   // 应做学生名单（排课班级的 active 学生）
const detailSubs = ref([])     // 该实验全部提交（含进行中）

const reviewVisible = ref(false)
const reviewLoading = ref(false)
const reviewSaving = ref(false)
const reviewForm = ref({ total_score: 0, comment: '' })
const currentSub = ref(null)
const qAnswers = ref([])          // 附加题逐题作答（含题目快照）
const reviewScores = ref({})      // { lab_question_id: 教师给分 }
const guideDialog = ref(null)

const statusText = (s) => ({ draft: '草稿', published: '已发布', closed: '已下线' }[s] || s)
const statusType = (s) => ({ draft: 'info', published: 'success', closed: 'warning' }[s] || 'info')

function fmtDT(t) {
  if (!t) return '—'
  const d = new Date(t)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 列表页快捷统计：某实验已完成/应做人数、均分（拉取过详情后才有缓存数据）。 */
const labStatsCache = ref({})
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
    const params = fixedCourseId.value ? { course: fixedCourseId.value } : undefined
    // 课程固定为当前课程：只需拉模板、实验列表、课程名（用于只读展示）
    const [t, l, c] = await Promise.all([listLabTemplates(), listLabs(params), request.get('/courses/', { params })])
    templates.value = t.results ?? t
    labs.value = (l.results ?? l)
    courses.value = (c.results ?? c)
  } finally {
    loading.value = false
  }
}

/** 拉取一个实验的统计（应做名单 + 提交记录），列表与详情共用。 */
async function fetchLabStats(lab) {
  const classroomIds = (lab.schedules || []).map((s) => s.classroom)
  if (!classroomIds.length) {
    return { expected: 0, submitted: 0, ongoing: 0, notStarted: 0, avgScore: null, avgSteps: null, submitRate: 0, roster: [], subs: [] }
  }
  const rosterReq = request.get('/class-students/', {
    params: { classroom: classroomIds, learn_status: 'active', page_size: 500 },
  })
  const subReq = listLabSubmissions({ lab: lab.id, page_size: 500 })
  const [rosterRes, subRes] = await Promise.all([rosterReq, subReq])
  let roster = rosterRes.results ?? rosterRes
  if (!Array.isArray(roster)) roster = []
  const subs = subRes.results ?? subRes
  const submitted = subs.filter((s) => s.status === 'submitted')
  const ongoing = subs.filter((s) => s.status !== 'submitted')
  const doneIds = new Set(submitted.map((s) => s.student))
  const scores = submitted.map((s) => Number(s.total_score || 0)).filter((n) => Number.isFinite(n))
  const avgScore = scores.length ? Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 10) / 10 : null
  const stepPairs = submitted.filter((s) => s.total_steps > 0)
  const avgSteps = stepPairs.length
    ? Math.round((stepPairs.reduce((a, s) => a + s.passed_steps / s.total_steps, 0) / stepPairs.length) * 100)
    : null
  return {
    expected: roster.length,
    submitted: submitted.length,
    ongoing: ongoing.length,
    notStarted: Math.max(0, roster.length - doneIds.size - ongoing.length),
    avgScore,
    avgSteps,
    submitRate: roster.length ? Math.round((submitted.length / roster.length) * 100) : 0,
    roster,
    subs,
  }
}

async function openDetail(row) {
  currentLab.value = row
  detailVisible.value = true
  detailLoading.value = true
  try {
    const st = await fetchLabStats(row)
    labStatsCache.value = { ...labStatsCache.value, [row.id]: st }
    detailRoster.value = st.roster
    detailSubs.value = st.subs
  } finally {
    detailLoading.value = false
  }
}

/** 详情表格行：名单为基线，合并提交状态；没排课时退化为纯提交列表。 */
const detailRows = computed(() => {
  const mapSub = (s, name, username) => ({
    id: s.id,
    name: name || s.student_name,
    username: username || s.student_username,
    state: s.status === 'submitted' ? 'submitted' : 'ongoing',
    total_score: s.total_score,
    passed_steps: s.passed_steps,
    total_steps: s.total_steps,
    error_count: s.error_count,
    elapsed_seconds: s.elapsed_seconds,
    score_breakdown: s.score_breakdown,
    reviewed: s.reviewed,
    submitted_at: s.submitted_at,
    student: s.student,
  })
  if (!detailRoster.value.length) {
    return detailSubs.value.map((s) => mapSub(s))
  }
  const byStudent = new Map(detailSubs.value.map((s) => [s.student, s]))
  return detailRoster.value.map((r) => {
    const s = byStudent.get(r.student)
    if (!s) {
      return { id: null, name: r.student_name, username: r.username, state: 'not_started' }
    }
    return mapSub(s, r.student_name, r.username)
  })
})

const detailStats = computed(() => labStatsCache.value[currentLab.value?.id] || {
  expected: 0, submitted: 0, ongoing: 0, notStarted: 0, avgScore: null, avgSteps: null, submitRate: 0,
})

async function create() {
  if (!form.value.template) {
    ElMessage.warning('请选择实验模板')
    return
  }
  creating.value = true
  try {
    // course 由路由注入：本页面仅存在于课程空间内
    await createLab({ ...form.value, course: fixedCourseId.value, title: form.value.title || undefined })
    ElMessage.success('实验已创建，排课并发布后学生可见')
    form.value = { template: null, title: '', standard_minutes: 30, question_weight: 0 }
    await load()
  } finally {
    creating.value = false
  }
}

async function openSchedule(row) {
  currentLab.value = row
  const res = await request.get('/classes/')
  classes.value = (res.results ?? res).filter(
    (c) => !c.courses || c.courses.some?.((cid) => cid === row.course) || true,
  )
  // 预填已有排课窗口（同班重排 = 更新窗口）
  let scheduleId = null
  let openAt = ''
  let closeAt = ''
  try {
    const sres = await listLabSchedules({ lab: row.id })
    const mine = (sres.results ?? sres)[0]
    if (mine) {
      scheduleId = mine.id
      openAt = mine.open_at || ''
      closeAt = mine.close_at || ''
    }
  } catch {
    // 拉取失败不阻塞排课
  }
  scheduleForm.value = { id: scheduleId, lab: row.id, classroom: null, open_at: openAt, close_at: closeAt }
  scheduleVisible.value = true
}

async function saveSchedule() {
  if (!scheduleForm.value.classroom) {
    ElMessage.warning('请选择班级')
    return
  }
  try {
    await createLabSchedule(scheduleForm.value)
    ElMessage.success('排课已保存')
    scheduleVisible.value = false
    await load()
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

async function openReview(row) {
  currentSub.value = { ...row, lab_total_score: currentLab.value?.total_score }
  reviewForm.value = { comment: '' }
  qAnswers.value = []
  reviewScores.value = {}
  reviewVisible.value = true
  reviewLoading.value = true
  try {
    if (row.id) {
      const res = await getLabAnswers(row.id)
      const list = res.results ?? res
      qAnswers.value = (Array.isArray(list) ? list : []).slice().sort(
        (a, b) => (a.lab_question?.order ?? 0) - (b.lab_question?.order ?? 0),
      )
      // 预填：已批过的用批改分，否则用系统预评分
      const init = {}
      for (const qa of qAnswers.value) {
        const qid = qa.lab_question?.id
        if (qid != null) init[qid] = Number(qa.score ?? qa.auto_score ?? 0)
      }
      reviewScores.value = init
    }
  } finally {
    reviewLoading.value = false
  }
}

function bkOf(sub) {
  return sub?.score_breakdown || {}
}

/** 学生作答文本：客观题映射选项，主观题取文本。 */
function answerText(qa) {
  const ans = qa.student_answer
  if (ans == null) return ''
  if (typeof ans === 'string') return ans
  const snap = qa.lab_question?.snapshot || {}
  const opts = snap.options || []
  const val = ans.value ?? ans.text ?? ans
  if (Array.isArray(val)) {
    const map = new Map(opts.map((o) => [o.key, o.content]))
    return val.map((k) => map.get(k) || k).join('；')
  }
  if (typeof val === 'string' && opts.length) {
    const hit = opts.find((o) => o.key === val)
    if (hit) return `${val}. ${hit.content}`
  }
  return String(val ?? '')
}

/** 参考答案文本（教师可见）。 */
function refAnswerText(qa) {
  const ans = qa.lab_question?.snapshot?.answer
  if (ans == null) return ''
  const opts = qa.lab_question?.snapshot?.options || []
  const val = ans.value ?? ans.text ?? ans
  if (Array.isArray(val)) {
    const map = new Map(opts.map((o) => [o.key, o.content]))
    return val.map((k) => map.get(k) || k).join('；')
  }
  if (typeof val === 'string' && opts.length) {
    const hit = opts.find((o) => o.key === val)
    if (hit) return `${val}. ${hit.content}`
  }
  return String(val ?? '')
}

async function saveReview() {
  if (!currentSub.value?.id) return
  reviewSaving.value = true
  try {
    // 逐题评分：后端按题目分重算附题得分并自动合成总分（无需教师改总分）
    const scores = Object.fromEntries(
      Object.entries(reviewScores.value).filter(([, v]) => v != null),
    )
    if (Object.keys(scores).length && qAnswers.value.length) {
      await gradeLabSubmission(currentSub.value.id, { scores })
    }
    // 评语非空时再走 review 接口落评语并通知学生
    if (reviewForm.value.comment) {
      await reviewLabSubmission(currentSub.value.id, { comment: reviewForm.value.comment })
    }
    ElMessage.success('批阅完成，成绩已通知学生')
    reviewVisible.value = false
    if (detailVisible.value && currentLab.value) await openDetail(currentLab.value)
  } catch (e) {
    ElMessage.error(e?.message || '批阅失败')
  } finally {
    reviewSaving.value = false
  }
}

async function reset(row) {
  if (!row.id) return
  await ElMessageBox.confirm(`重置后 ${row.name} 可重新做实验（旧成绩清空），确认？`, '提示', { type: 'warning' })
  await resetLabSubmission(row.id)
  ElMessage.success('已重置')
  if (currentLab.value) await openDetail(currentLab.value)
}

onMounted(load)
</script>

<style scoped>
.mb12 { margin-bottom: 12px; }
.weight-label { margin-right: 2px; }
.tip-ico { color: #94a3b8; cursor: help; font-size: 14px; vertical-align: -2px; }
.weight-tip p { margin: 0 0 4px; font-size: 12px; line-height: 1.6; }
.weight-tip p:last-child { margin-bottom: 0; }
.weight-tip b { color: #2563eb; }
.weight-row { display: flex; align-items: center; width: 100%; }
.weight-row .el-input-number { margin-right: auto; }
.create-btn { margin-left: auto; }
.schedule-line { display: flex; align-items: center; gap: 8px; line-height: 1.9; }
.schedule-class {
  flex-shrink: 0;
  padding: 1px 8px;
  border-radius: 4px;
  background: #ecf5ff;
  color: #409eff;
  font-size: 12px;
}
.schedule-time { color: #64748b; font-size: 12px; white-space: nowrap; }
.schedule-none { color: #cbd5e1; font-size: 12px; }
.stu-done { color: #475569; font-size: 13px; }

.detail-body { padding: 0 4px; }
.d-section { margin-bottom: 26px; }
.d-title {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 12px;
  padding-left: 8px;
  border-left: 3px solid #409eff;
}
.d-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px 24px;
  background: #f8fafc;
  border-radius: 8px;
  padding: 14px 16px;
}
.d-item { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #334155; }
.d-k { color: #94a3b8; flex-shrink: 0; }

.stat-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 12px; }
.stat-box {
  border-radius: 10px;
  padding: 14px 10px;
  text-align: center;
  background: #f8fafc;
}
.stat-box .stat-num { font-size: 24px; font-weight: 700; color: #1e293b; }
.stat-box .stat-label { margin-top: 4px; font-size: 12px; color: #94a3b8; }
.stat-box.ok { background: #ecfdf5; }
.stat-box.ok .stat-num { color: #059669; }
.stat-box.ing { background: #fff7ed; }
.stat-box.ing .stat-num { color: #d97706; }
.stat-box.miss { background: #fef2f2; }
.stat-box.miss .stat-num { color: #dc2626; }
.stat-box.avg { background: #eff6ff; }
.stat-box.avg .stat-num { color: #2563eb; }

.sub-text { color: #94a3b8; font-size: 12px; margin-left: 6px; }
.score-num { font-weight: 700; color: #2563eb; }

.qa-card {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 12px;
  background: #fff;
}
.qa-head { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 8px; }
.qa-stem { flex: 1; font-size: 13px; color: #1e293b; line-height: 1.6; }
.qa-score-tag { flex-shrink: 0; color: #94a3b8; font-size: 12px; }
.qa-body { display: grid; gap: 6px; }
.qa-row { display: flex; align-items: flex-start; gap: 10px; font-size: 13px; }
.qa-row .d-k { flex-shrink: 0; margin-top: 2px; }
.qa-text { color: #334155; line-height: 1.6; word-break: break-word; }
.qa-ref { color: #059669; }
.qa-grade { align-items: center; }
</style>
