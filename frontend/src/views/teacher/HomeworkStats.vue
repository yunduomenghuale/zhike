<template>
  <div class="page-container homework-stats-page" v-loading="loading">
    <!-- 常驻返回栏：课程空间内 page-header 被 CourseWorkspaceShell 隐藏、全局入口滚动后头部也会移出视口，
         故返回入口独立常驻（sticky），不依赖 page-header（与考试统计页一致） -->
    <div class="page-back-bar">
      <el-button :icon="ArrowLeft" @click="goBack">返回作业列表</el-button>
      <span class="page-back-title">作业统计<template v-if="stats?.homework?.title"> · {{ stats.homework.title }}</template></span>
    </div>

    <div class="page-header">
      <div>
        <div class="page-title">作业统计</div>
        <div class="page-subtitle">
          {{ stats?.homework?.title || '作业' }} · {{ stats?.homework?.class_name || '' }} · {{ stats?.homework?.course_name || '' }}
          <template v-if="stats?.homework?.mode_display"> · {{ stats.homework.mode_display }}</template>
        </div>
      </div>
      <div class="page-header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <template v-if="stats">
      <!-- 总览卡片 -->
      <div class="stat-cards">
        <div class="stat-card">
          <div class="stat-value primary">{{ ov.student_count }}</div>
          <div class="stat-label">应交人数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value success">{{ ov.submitted }}</div>
          <div class="stat-label">已提交</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" :class="{ danger: ov.unsubmitted > 0 }">{{ ov.unsubmitted }}</div>
          <div class="stat-label">未提交</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" :class="{ warn: ov.late_count > 0 }">{{ ov.late_count }}</div>
          <div class="stat-label">逾期提交</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" :class="{ warn: ov.pending_count > 0 }">{{ ov.pending_count }}</div>
          <div class="stat-label">待批改</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ fmtScore(ov.avg_score) }}</div>
          <div class="stat-label">平均分（总分 {{ fmtScore(stats.homework.total_score) }}）</div>
        </div>
        <div class="stat-card">
          <div class="stat-value success">{{ fmtScore(ov.max_score) }}</div>
          <div class="stat-label">最高分</div>
        </div>
        <div class="stat-card">
          <div class="stat-value danger">{{ fmtScore(ov.min_score) }}</div>
          <div class="stat-label">最低分</div>
        </div>
        <div class="stat-card">
          <div class="stat-value primary">{{ fmtPct(ov.pass_rate) }}</div>
          <div class="stat-label">及格率（60%）</div>
        </div>
        <div class="stat-card">
          <div class="stat-value success">{{ fmtPct(ov.excellent_rate) }}</div>
          <div class="stat-label">优秀率（85%）</div>
        </div>
      </div>

      <!-- 图表：总分分布 + 逐题得分率（题库作业才有逐题数据） -->
      <el-row :gutter="16" class="chart-row">
        <el-col :xs="24" :lg="9">
          <el-card shadow="never" class="chart-card">
            <template #header>
              <div class="chart-title">总分分布</div>
            </template>
            <div v-if="maxDistCount > 0" class="dist-chart">
              <div v-for="item in stats.score_distribution" :key="item.range" class="dist-col">
                <span class="dist-count">{{ item.count || '' }}</span>
                <div class="dist-bar" :style="{ height: distHeight(item.count) }" />
                <span class="dist-range">{{ item.range }}</span>
              </div>
            </div>
            <el-empty v-else description="暂无成绩数据" :image-size="60" />
          </el-card>
        </el-col>
        <el-col :xs="24" :lg="15">
          <el-card shadow="never" class="chart-card">
            <template #header>
              <div class="chart-title">逐题得分率（客观题为正确率）</div>
            </template>
            <div v-if="isQuestionsMode && filteredQuestions.length" class="qrate-chart">
              <div v-for="q in filteredQuestions" :key="q.question_id" class="qrate-row">
                <span class="qrate-name" :title="q.stem">第 {{ q.order }} 题</span>
                <div class="qrate-track">
                  <div class="qrate-bar" :class="rateTone(rateOf(q))" :style="{ width: rateOf(q) + '%' }" />
                </div>
                <span class="qrate-num">{{ rateOf(q) }}%</span>
              </div>
            </div>
            <el-empty v-else :description="isQuestionsMode ? '暂无题目数据' : '附件作业暂无逐题数据'" :image-size="60" />
          </el-card>
        </el-col>
      </el-row>

      <!-- 题目统计：仅题库作业；题型筛选归属本题表（同时作用于上方逐题得分率图） -->
      <el-card v-if="isQuestionsMode" shadow="never" class="table-card">
        <template #header>
          <div class="table-head">
            <div class="chart-title">题目答题统计</div>
            <div class="table-head-filters question-filters">
              <el-select v-model="qtypeFilter" style="width: 130px">
                <el-option v-for="opt in qtypeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
              <span class="toolbar-count">共 {{ filteredQuestions.length }} 题</span>
            </div>
          </div>
        </template>
        <el-table :data="filteredQuestions" stripe>
          <el-table-column type="expand">
            <template #default="{ row }">
              <div v-if="row.options" class="opt-dist">
                <div class="opt-dist-title">选项分布（按原题顺序，共 {{ row.answered_n }} 份作答）</div>
                <div v-for="opt in row.options" :key="opt.key" class="opt-dist-row">
                  <span class="opt-dist-key" :class="{ correct: opt.is_correct }">{{ opt.key }}.</span>
                  <span class="opt-dist-text" :title="opt.text">{{ opt.text }}</span>
                  <div class="opt-dist-track">
                    <div
                      class="opt-dist-bar"
                      :class="{ correct: opt.is_correct }"
                      :style="{ width: optPct(opt.count, row.answered_n) + '%' }"
                    />
                  </div>
                  <span class="opt-dist-count">{{ opt.count }} 人</span>
                  <el-tag v-if="opt.is_correct" type="success" size="small" effect="plain" round>正确答案</el-tag>
                </div>
              </div>
              <div v-else class="opt-dist-empty">本题为主观题，无选项分布</div>
            </template>
          </el-table-column>
          <el-table-column prop="order" label="题号" width="60" align="center" />
          <el-table-column label="题型" width="90" align="center">
            <template #default="{ row }"><el-tag size="small" effect="light" round>{{ row.qtype_display }}</el-tag></template>
          </el-table-column>
          <el-table-column label="题干" min-width="220">
            <template #default="{ row }">
              <span class="stem-text" :title="row.stem">{{ row.stem }}</span>
              <QuestionImage :question="row" />
            </template>
          </el-table-column>
          <el-table-column prop="score" label="分值" width="70" align="center" />
          <el-table-column label="平均分" width="90" align="center">
            <template #default="{ row }">{{ fmtScore(row.avg_score) }}</template>
          </el-table-column>
          <el-table-column label="满分率" width="90" align="center">
            <template #default="{ row }">{{ fmtPct(row.full_rate) }}</template>
          </el-table-column>
          <el-table-column label="零分率" width="90" align="center">
            <template #default="{ row }">{{ fmtPct(row.zero_rate) }}</template>
          </el-table-column>
          <el-table-column label="正确率/得分率" min-width="160">
            <template #default="{ row }">
              <div class="cell-rate">
                <span class="cell-rate-num">{{ row.correct_rate != null ? row.correct_rate + '%' : rateOf(row) + '%' }}</span>
                <div class="cell-rate-track">
                  <div
                    class="cell-rate-bar"
                    :class="rateTone(row.correct_rate != null ? row.correct_rate : rateOf(row))"
                    :style="{ width: (row.correct_rate != null ? row.correct_rate : rateOf(row)) + '%' }"
                  />
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="未作答" width="80" align="center">
            <template #default="{ row }">
              <span :class="{ 'text-danger': row.unanswered > 0 }">{{ row.unanswered }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 学生提交与成绩：状态/成绩/搜索筛选归属本表 -->
      <el-card shadow="never" class="table-card">
        <template #header>
          <div class="table-head">
            <div class="chart-title">学生提交与成绩</div>
            <div class="table-head-filters rank-filters">
              <el-select v-model="statusFilter" style="width: 120px">
                <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
              <el-select v-model="scoreFilter" style="width: 130px">
                <el-option v-for="opt in scoreOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
              <el-input v-model="keyword" placeholder="搜索学生姓名/学号" clearable style="width: 180px" />
              <span class="toolbar-count">共 {{ filteredRankings.length }} 人</span>
            </div>
          </div>
        </template>
        <el-table :data="filteredRankings" stripe>
          <el-table-column label="排名" width="70" align="center">
            <template #default="{ row }">
              <span v-if="row.rank" class="rank-num" :class="rankTone(row.rank)">{{ row.rank }}</span>
              <span v-else class="text-muted">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="student_name" label="学生" width="120" />
          <el-table-column label="状态" width="110" align="center">
            <template #default="{ row }">
              <el-tag effect="light" round size="small" :type="statusTone(row.status)">{{ row.status_display }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="得分" width="100" align="center">
            <template #default="{ row }">
              <strong v-if="row.score != null">{{ fmtScore(row.score) }}</strong>
              <span v-else-if="row.status === 'submitted' && row.objective_score" class="text-muted">客观 {{ fmtScore(row.objective_score) }} 分</span>
              <span v-else class="text-muted">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="objective_score" label="客观题分" width="100" align="center">
            <template #default="{ row }">{{ fmtScore(row.objective_score) }}</template>
          </el-table-column>
          <el-table-column label="提交时间" min-width="150">
            <template #default="{ row }">{{ row.submitted_at ? new Date(row.submitted_at).toLocaleString() : '-' }}</template>
          </el-table-column>
          <el-table-column label="逾期" width="80" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_late" type="danger" size="small" effect="light" round>逾期</el-tag>
              <span v-else class="text-muted">-</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <el-empty v-else-if="!loading" description="暂无统计数据" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { getHomeworkStats } from '@/api/homework'
import QuestionImage from '@/components/QuestionImage.vue'

const route = useRoute()
const router = useRouter()
// 两种入口：课程空间 /teacher/courses/:id/homework/:homeworkId/stats 与全局 /teacher/homework/:id/stats
const homeworkId = Number(route.params.homeworkId || route.params.id)
const courseId = computed(() => {
  const m = route.path.match(/^\/teacher\/courses\/(\d+)\/homework\//)
  return m ? Number(m[1]) : null
})

const loading = ref(false)
const stats = ref(null)

// 筛选条件
const statusFilter = ref('all')
const scoreFilter = ref('all')
const keyword = ref('')
const qtypeFilter = ref('all')

const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'submitted', label: '待批改' },
  { value: 'returned', label: '已发布成绩' },
  { value: 'unsubmitted', label: '未提交' },
]
const scoreOptions = [
  { value: 'all', label: '全部成绩' },
  { value: 'excellent', label: '优秀（≥85%）' },
  { value: 'pass', label: '及格（≥60%）' },
  { value: 'fail', label: '不及格' },
  { value: 'unscored', label: '未出分' },
]
const qtypeOptions = [
  { value: 'all', label: '全部题型' },
  { value: 'single', label: '单选题' },
  { value: 'multi', label: '多选题' },
  { value: 'judge', label: '判断题' },
  { value: 'blank', label: '填空题' },
  { value: 'short', label: '简答题' },
]

const ov = computed(() => stats.value?.overview || {})
const isQuestionsMode = computed(() => stats.value?.homework?.mode === 'questions')

async function load() {
  loading.value = true
  try {
    stats.value = await getHomeworkStats(homeworkId)
  } finally {
    loading.value = false
  }
}

function goBack() {
  if (courseId.value) {
    router.push(`/teacher/courses/${courseId.value}/homework`)
  } else {
    router.push('/teacher/homework')
  }
}

// ---- 格式化 ----
function fmtScore(v) {
  if (v == null) return '-'
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}
function fmtPct(v) {
  return v == null ? '-' : v + '%'
}

// ---- 总分分布图 ----
const maxDistCount = computed(() =>
  Math.max(0, ...(stats.value?.score_distribution || []).map((d) => d.count)),
)
function distHeight(count) {
  if (!maxDistCount.value) return '0%'
  return Math.max(count > 0 ? 4 : 0, Math.round((count / maxDistCount.value) * 100)) + '%'
}

// ---- 逐题得分率 ----
function rateOf(q) {
  // 主观题无 correct_rate，用平均分/分值折算得分率
  if (q.correct_rate != null) return q.correct_rate
  if (q.avg_score == null || !q.score) return 0
  return Math.min(100, Math.round((q.avg_score / q.score) * 100))
}
function rateTone(rate) {
  if (rate >= 80) return 'good'
  if (rate >= 60) return 'mid'
  return 'bad'
}
function rankTone(rank) {
  if (rank === 1) return 'gold'
  if (rank === 2) return 'silver'
  if (rank === 3) return 'bronze'
  return ''
}
function statusTone(status) {
  return { submitted: 'warning', graded: 'primary', returned: 'success', unsubmitted: 'info' }[status] || 'info'
}

// ---- 筛选 ----
const passLine = computed(() => (stats.value?.homework?.total_score || 0) * 0.6)
const excellentLine = computed(() => (stats.value?.homework?.total_score || 0) * 0.85)

const filteredRankings = computed(() => {
  let rows = stats.value?.rankings || []
  if (statusFilter.value !== 'all') {
    rows = rows.filter((r) => r.status === statusFilter.value)
  }
  if (scoreFilter.value !== 'all') {
    rows = rows.filter((r) => {
      const t = r.score
      if (scoreFilter.value === 'unscored') return t == null
      if (t == null) return false
      if (scoreFilter.value === 'excellent') return t >= excellentLine.value
      if (scoreFilter.value === 'pass') return t >= passLine.value
      return t < passLine.value
    })
  }
  const kw = keyword.value.trim().toLowerCase()
  if (kw) {
    rows = rows.filter((r) => String(r.student_name || '').toLowerCase().includes(kw))
  }
  return rows
})

const filteredQuestions = computed(() => {
  let rows = stats.value?.question_stats || []
  if (qtypeFilter.value !== 'all') {
    rows = rows.filter((q) => q.qtype === qtypeFilter.value)
  }
  return rows
})

function optPct(count, total) {
  if (!total) return 0
  return Math.round((count / total) * 100)
}

onMounted(load)
</script>

<style scoped>
.homework-stats-page {
  padding-bottom: 40px;
}
.page-header-actions {
  display: flex;
  gap: 10px;
}
.stat-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  padding: 14px 16px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
  text-align: center;
}
.stat-value {
  font-size: 24px;
  font-weight: 800;
  color: #0f172a;
  line-height: 1.2;
}
.stat-value.primary { color: #2563eb; }
.stat-value.success { color: #059669; }
.stat-value.warn { color: #d97706; }
.stat-value.danger { color: #dc2626; }
.stat-label {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}
.chart-row {
  margin-bottom: 16px;
}
.chart-card {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}
.chart-card :deep(.el-card__header) {
  padding: 12px 16px;
  border-bottom: 1px solid #f1f5f9;
}
.chart-title {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
}
/* 总分分布：竖状条形图 */
.dist-chart {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  height: 180px;
  padding: 8px 4px 0;
}
.dist-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
  gap: 6px;
}
.dist-count {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
  min-height: 16px;
}
.dist-bar {
  width: 70%;
  max-width: 42px;
  min-height: 2px;
  border-radius: 6px 6px 0 0;
  background: linear-gradient(180deg, #60a5fa, #2563eb);
}
.dist-range {
  font-size: 11.5px;
  color: #64748b;
  white-space: nowrap;
}
/* 逐题得分率：横条 */
.qrate-chart {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.qrate-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.qrate-name {
  flex: 0 0 64px;
  font-size: 12.5px;
  color: #475569;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.qrate-track {
  flex: 1;
  height: 12px;
  border-radius: 999px;
  background: #f1f5f9;
  overflow: hidden;
}
.qrate-bar {
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s;
}
.qrate-bar.good { background: #10b981; }
.qrate-bar.mid { background: #f59e0b; }
.qrate-bar.bad { background: #ef4444; }
.qrate-num {
  flex: 0 0 44px;
  text-align: right;
  font-size: 12.5px;
  font-weight: 700;
  color: #334155;
}
/* 常驻返回栏（sticky：课程空间头部被隐藏/全局滚动后仍可返回） */
.page-back-bar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(8px);
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(15, 23, 42, 0.08);
}
.page-back-title {
  font-size: 14px;
  font-weight: 700;
  color: #334155;
}
/* 表头筛选：每组筛选条件归属各自列表 */
.table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.table-head-filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.toolbar-count {
  font-size: 12.5px;
  color: #64748b;
  white-space: nowrap;
}
.table-card {
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  margin-bottom: 16px;
}
.table-card :deep(.el-card__header) {
  padding: 12px 16px;
  border-bottom: 1px solid #f1f5f9;
}
.stem-text {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.cell-rate {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cell-rate-num {
  flex: 0 0 40px;
  font-size: 12.5px;
  font-weight: 700;
  color: #334155;
}
.cell-rate-track {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: #f1f5f9;
  overflow: hidden;
}
.cell-rate-bar {
  height: 100%;
  border-radius: 999px;
}
.cell-rate-bar.good { background: #10b981; }
.cell-rate-bar.mid { background: #f59e0b; }
.cell-rate-bar.bad { background: #ef4444; }
.rank-num {
  font-weight: 800;
  color: #334155;
}
.rank-num.gold { color: #d97706; }
.rank-num.silver { color: #64748b; }
.rank-num.bronze { color: #b45309; }
.text-muted { color: #94a3b8; }
.text-danger { color: #dc2626; font-weight: 600; }
/* 选项分布（展开行） */
.opt-dist {
  padding: 4px 12px 10px;
}
.opt-dist-title {
  margin-bottom: 10px;
  font-size: 12.5px;
  font-weight: 600;
  color: #475569;
}
.opt-dist-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 6px 0;
}
.opt-dist-key {
  flex: 0 0 20px;
  font-weight: 700;
  color: #334155;
}
.opt-dist-key.correct { color: #059669; }
.opt-dist-text {
  flex: 0 0 40%;
  font-size: 12.5px;
  color: #475569;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.opt-dist-track {
  flex: 1;
  height: 10px;
  border-radius: 999px;
  background: #f1f5f9;
  overflow: hidden;
}
.opt-dist-bar {
  height: 100%;
  border-radius: 999px;
  background: #94a3b8;
}
.opt-dist-bar.correct { background: #10b981; }
.opt-dist-count {
  flex: 0 0 56px;
  text-align: right;
  font-size: 12.5px;
  color: #334155;
}
.opt-dist-empty {
  padding: 8px 12px;
  font-size: 12.5px;
  color: #94a3b8;
}
</style>
