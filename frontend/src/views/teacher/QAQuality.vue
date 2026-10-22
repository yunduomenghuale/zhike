<template>
  <div class="qa-quality">
    <header class="page-head">
      <div>
        <h1>问答质量<QaHelp text="学生向 AI 助手提问的检索命中、评价与上下文健康度——发现课程资料覆盖盲区，持续改进知识库。" /></h1>
      </div>
    </header>

    <section class="stats-panel" v-loading="qaLoading">
      <div class="stats-toolbar">
        <el-date-picker
          v-model="period.range"
          type="daterange"
          value-format="YYYY-MM-DD"
          unlink-panels
          range-separator="~"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :shortcuts="rangeShortcuts"
          clearable
          style="width:270px"
          @change="onRangeChange"
        />
        <span class="days-input">
          <span class="days-label">近</span>
          <el-input-number v-model="period.days" :min="1" :max="365" :step="1" controls-position="right" style="width:108px" @change="onDaysChange" />
          <span class="days-label">天</span>
        </span>
        <el-button :icon="Refresh" @click="reloadAll">刷新</el-button>
      </div>
      <p v-if="qaWindowText" class="window-note">当前窗口 {{ qaWindowText }}<QaHelp text="统计范围为本人负责课程的学生提问（含章节内提问与课程问答页提问）；纯图片提问跳过检索、不计入为空率分母。" /></p>

      <div v-if="qa?.alerts?.length" class="alerts">
        <div v-for="(alert, i) in qa.alerts" :key="i" class="alert" :class="alert.level">
          <el-icon><WarningFilled v-if="alert.level !== 'info'" /><InfoFilled v-else /></el-icon>
          <span>{{ alert.title }}：{{ alert.detail }}</span>
        </div>
      </div>

      <div class="stat-cards qa-cards">
        <div class="stat-card">
          <small>提问总量<QaHelp text="窗口内学生向 AI 助手提出的问题总数（含章节内提问与课程问答页提问）。" /></small>
          <strong>{{ fmtNum(qa?.totals?.questions) }}</strong>
          <span class="sub">跳过检索 {{ fmtNum(qa?.totals?.skip_retrieval) }} · 收到评价 {{ fmtNum(qa?.totals?.feedback?.rated) }}</span>
        </div>
        <div class="stat-card">
          <small>检索为空率<QaHelp text="检索未命中任何课程片段的提问占比。分母已排除纯图片提问（跳过检索、直接走视觉理解）。偏高说明课程资料对问题的覆盖不足。" /></small>
          <strong :class="qaRateTone(qa?.totals?.empty_retrieval?.rate, { badAbove: 0.3, warnAbove: 0.2 })">{{ fmtPct(qa?.totals?.empty_retrieval?.rate) }}</strong>
          <span class="sub">空检索 {{ fmtNum(qa?.totals?.empty_retrieval?.count) }} 条</span>
          <span class="delta" :class="qaDelta(qa?.totals?.empty_retrieval?.rate, qa?.totals?.empty_retrieval?.rate_previous).tone" :title="`上周期 ${fmtPct(qa?.totals?.empty_retrieval?.rate_previous)}`">{{ qaDelta(qa?.totals?.empty_retrieval?.rate, qa?.totals?.empty_retrieval?.rate_previous).text }}</span>
        </div>
        <div class="stat-card">
          <small>改写触发率<QaHelp text="多轮追问时，系统把口语化问题改写成可独立检索的问题的占比（仅用于检索，学生看到的仍是原问题）。首轮提问天然不触发改写。" /></small>
          <strong>{{ fmtPct(qa?.totals?.rewrite?.rate) }}</strong>
          <span class="sub">触发改写 {{ fmtNum(qa?.totals?.rewrite?.count) }} 条</span>
          <span class="delta" :class="qaDelta(qa?.totals?.rewrite?.rate, qa?.totals?.rewrite?.rate_previous).tone" :title="`上周期 ${fmtPct(qa?.totals?.rewrite?.rate_previous)}`">{{ qaDelta(qa?.totals?.rewrite?.rate, qa?.totals?.rewrite?.rate_previous).text }}</span>
        </div>
        <div class="stat-card">
          <small>学生好评率<QaHelp text="学生点「有用」的占比，分母为点过评价的提问（有用 ÷（有用+无用））。请配合「评价覆盖率」一起看，避免小样本误导。" /></small>
          <strong :class="qaRateTone(qa?.totals?.feedback?.rate, { badBelow: 0.6, warnBelow: 0.8 })">{{ fmtPct(qa?.totals?.feedback?.rate) }}</strong>
          <span class="sub">有用 {{ fmtNum(qa?.totals?.feedback?.positive) }} / {{ fmtNum(qa?.totals?.feedback?.rated) }}</span>
          <span class="delta" :class="qaDelta(qa?.totals?.feedback?.rate, qa?.totals?.feedback?.rate_previous, { goodWhenUp: true }).tone" :title="`上周期 ${fmtPct(qa?.totals?.feedback?.rate_previous)}`">{{ qaDelta(qa?.totals?.feedback?.rate, qa?.totals?.feedback?.rate_previous, { goodWhenUp: true }).text }}</span>
        </div>
        <div class="stat-card">
          <small>评价覆盖率<QaHelp text="收到学生评价的提问占比（分母为全部提问）。覆盖率低时，好评率的参考意义有限。" /></small>
          <strong>{{ fmtPct(qa?.totals?.feedback?.coverage) }}</strong>
          <span class="sub">评价 {{ fmtNum(qa?.totals?.feedback?.rated) }} / {{ fmtNum(qa?.totals?.questions) }} 条</span>
          <span class="delta" :class="qaDelta(qa?.totals?.feedback?.coverage, qa?.totals?.feedback?.coverage_previous).tone" :title="`上周期 ${fmtPct(qa?.totals?.feedback?.coverage_previous)}`">{{ qaDelta(qa?.totals?.feedback?.coverage, qa?.totals?.feedback?.coverage_previous).text }}</span>
        </div>
        <div class="stat-card">
          <small>兜底触发率<QaHelp text="当前轮检索为空时，用上一轮检索到的片段继续作答的提问占比。偏高说明追问场景下检索连续落空。" /></small>
          <strong :class="qaRateTone(qa?.totals?.fallback?.rate, { badAbove: 0.2, warnAbove: 0.1 })">{{ fmtPct(qa?.totals?.fallback?.rate) }}</strong>
          <span class="sub">触发兜底 {{ fmtNum(qa?.totals?.fallback?.count) }} 条</span>
          <span class="delta" :class="qaDelta(qa?.totals?.fallback?.rate, qa?.totals?.fallback?.rate_previous).tone" :title="`上周期 ${fmtPct(qa?.totals?.fallback?.rate_previous)}`">{{ qaDelta(qa?.totals?.fallback?.rate, qa?.totals?.fallback?.rate_previous).text }}</span>
        </div>
      </div>

      <div class="chart-card">
        <div class="chart-head">
          <h3>日趋势<QaHelp text="按天聚合的检索为空率与学生好评率（分母口径同指标卡）；当天无提问时折线断开。滑动圆点可查看当日数值。" /></h3>
        </div>
        <svg v-if="qaPointCount" viewBox="0 0 680 220" class="trend-chart" preserveAspectRatio="xMidYMid meet">
          <line v-for="g in qaGridValues" :key="'grid' + g" :x1="44" :x2="664" :y1="qaY(g)" :y2="qaY(g)" stroke="#e8eef7" stroke-width="1" />
          <text :x="38" :y="qaY(qaAxisMax) + 4" text-anchor="end" class="axis-label">{{ fmtPct(qaAxisMax) }}</text>
          <text :x="38" :y="qaY(qaAxisMax / 2) + 4" text-anchor="end" class="axis-label">{{ fmtPct(qaAxisMax / 2) }}</text>
          <text :x="38" :y="qaY(0) + 4" text-anchor="end" class="axis-label">0%</text>
          <polyline v-for="(seg, i) in qaFeedbackSegments" :key="'f' + i" :points="seg" fill="none" stroke="#16a34a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          <polyline v-for="(seg, i) in qaEmptySegments" :key="'e' + i" :points="seg" fill="none" stroke="#dc2626" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          <g v-for="(row, i) in qaTrendDays" :key="row.date">
            <circle v-if="row.feedback_rate != null" :cx="qaX(i, qaPointCount)" :cy="qaY(row.feedback_rate)" r="2.5" fill="#16a34a">
              <title>{{ row.date }} · 学生好评率 {{ fmtPct(row.feedback_rate) }}</title>
            </circle>
            <circle v-if="row.empty_rate != null" :cx="qaX(i, qaPointCount)" :cy="qaY(row.empty_rate)" r="2.5" fill="#dc2626">
              <title>{{ row.date }} · 检索为空率 {{ fmtPct(row.empty_rate) }}</title>
            </circle>
            <text v-if="i % qaLabelEvery === 0" :x="qaX(i, qaPointCount)" :y="212" text-anchor="middle" class="axis-label">{{ row.date.slice(5) }}</text>
          </g>
        </svg>
        <el-empty v-else description="该时间范围内暂无问答记录" :image-size="60" />
        <p class="chart-legend">
          <span><i class="dot dot-red"></i>检索为空率</span>
          <span><i class="dot dot-green"></i>学生好评率</span>
        </p>
      </div>

      <div class="dist-card">
        <div class="dist-head">
          <h3>上下文降级分布<QaHelp text="上下文超限时的分级重试：L1 丢一半旧历史、L2 仅保留最近两轮、L4 丢弃全部历史。L4 占比突增通常意味着长会话频繁触发超限。" /></h3>
          <span v-if="qa?.degraded" class="toolbar-note">降级率 {{ fmtPct(qa.degraded.degraded_rate) }} · 环比上周期 {{ fmtPct(qa.degraded.degraded_rate_previous) }}</span>
        </div>
        <el-empty v-if="!qa?.totals?.questions" description="该时间范围内暂无问答记录" :image-size="60" />
        <template v-else>
          <div v-for="row in qaDegradedRows" :key="row.key" class="dist-row dist-static">
            <span class="dist-name" :title="row.label">{{ row.label }}</span>
            <span class="dist-bar"><i :style="{ width: row.width + '%', background: row.color }"></i></span>
            <span class="dist-calls">{{ fmtNum(row.count) }}</span>
            <span class="dist-pct">{{ row.pct }}</span>
          </div>
        </template>
      </div>

      <div class="dist-card">
        <div class="dist-head">
          <h3>引用来源分布<QaHelp text="回答引用的片段来源（知识库资料 / 讲解稿 / 课件 PPT / 两者组合）；一条回答引用多个片段时各计一次；早期无来源标记的历史记录计入「其他」。" /></h3>
        </div>
        <el-empty v-if="!qaSourceRows.length" description="该时间范围内暂无问答记录" :image-size="60" />
        <template v-else>
          <div v-for="row in qaSourceRows" :key="row.key" class="dist-row dist-static">
            <span class="dist-name" :title="row.label">{{ row.label }}</span>
            <span class="dist-bar"><i :style="{ width: row.width + '%', background: row.color }"></i></span>
            <span class="dist-calls">{{ fmtNum(row.count) }}</span>
            <span class="dist-pct">{{ row.pct }}</span>
          </div>
        </template>
      </div>

      <div class="logs-card">
        <div class="logs-head">
          <h3>课程质量排行<QaHelp text="按课程聚合的提问量、检索为空率、学生好评率与降级率。红色为超阈值（为空率>30%、降级率>20%），黄色为关注区间（为空率 20~30%、降级率 10~20%）；好评率评价数不足 5 条时不参与着色。" /></h3>
          <span class="toolbar-note">默认按检索为空率从高到低（最需关注的课程在前），点击表头可改排序</span>
        </div>
        <el-table :data="qa?.by_course || []" size="small" class="qa-quality-table" scrollbar-always-on :default-sort="{ prop: 'empty_rate', order: 'descending' }">
          <el-table-column label="课程" min-width="180">
            <template #default="{ row }"><strong>{{ row.course_name }}</strong></template>
          </el-table-column>
          <el-table-column label="提问量" width="90" sortable :sort-method="(a, b) => a.questions - b.questions">
            <template #default="{ row }">{{ fmtNum(row.questions) }}</template>
          </el-table-column>
          <el-table-column label="为空率" width="100" sortable :sort-by="(row) => row.empty_rate == null ? -1 : row.empty_rate">
            <template #default="{ row }"><span :class="qaRateTone(row.empty_rate, { badAbove: 0.3, warnAbove: 0.2 })">{{ fmtPct(row.empty_rate) }}</span></template>
          </el-table-column>
          <el-table-column label="好评率" width="100" sortable :sort-by="(row) => row.feedback_rate == null ? -1 : row.feedback_rate">
            <template #default="{ row }">
              <span v-if="row.rated < 5" class="muted">样本少</span>
              <span v-else :class="qaRateTone(row.feedback_rate, { badBelow: 0.6, warnBelow: 0.8 })">{{ fmtPct(row.feedback_rate) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="评价数" width="90" sortable :sort-method="(a, b) => a.rated - b.rated">
            <template #default="{ row }">{{ fmtNum(row.rated) }}</template>
          </el-table-column>
          <el-table-column label="降级率" width="100" sortable :sort-by="(row) => row.degraded_rate == null ? -1 : row.degraded_rate">
            <template #default="{ row }"><span :class="qaRateTone(row.degraded_rate, { badAbove: 0.2, warnAbove: 0.1 })">{{ fmtPct(row.degraded_rate) }}</span></template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 问题下钻：类型 + 课程筛选，点击行看完整问答详情 -->
      <div class="logs-card">
        <div class="logs-head">
          <h3>问题下钻<QaHelp text="按类型查看本人课程的学生提问明细：检索为空（口径同看板，已排除纯图片提问）、差评（学生点了「无用」）或全部。点击任意一行查看完整问答、参考来源与上下文状态。" /></h3>
          <div class="logs-filters">
            <el-select v-model="issueType" style="width:150px" @change="reloadIssues">
              <el-option label="全部问题" value="all" />
              <el-option label="检索为空" value="empty" />
              <el-option label="学生差评" value="disliked" />
            </el-select>
            <el-select v-model="issueCourse" clearable placeholder="全部课程" style="width:180px" @change="reloadIssues">
              <el-option v-for="c in courseOptions" :key="c.course_id" :label="c.course_name" :value="String(c.course_id)" />
            </el-select>
          </div>
        </div>
        <el-table
          v-loading="issuesLoading"
          :data="issues"
          size="small"
          class="qa-issues-table"
          scrollbar-always-on
          empty-text="该筛选条件下暂无问题"
          @row-click="openIssue"
        >
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="课程" min-width="130">
            <template #default="{ row }">{{ row.course_name }}</template>
          </el-table-column>
          <el-table-column label="学生" width="90">
            <template #default="{ row }">{{ row.student_name || '匿名' }}</template>
          </el-table-column>
          <el-table-column label="问题" min-width="220">
            <template #default="{ row }"><span class="ellipsis" :title="row.question">{{ row.question }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="150">
            <template #default="{ row }">
              <span class="issue-tags">
                <el-tag v-if="row.skip_retrieval" size="small" type="info">纯图片</el-tag>
                <el-tag v-else-if="!row.cited_chunks?.length" size="small" type="danger">检索为空</el-tag>
                <el-tag v-if="row.degraded_level === 4" size="small" type="warning">上下文全丢</el-tag>
                <el-tag v-else-if="row.degraded_level > 0" size="small" type="warning" effect="plain">降级 L{{ row.degraded_level }}</el-tag>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="评价" width="80">
            <template #default="{ row }">
              <span v-if="row.feedback === 1" class="feedback-good">有用</span>
              <span v-else-if="row.feedback === -1" class="feedback-bad">无用</span>
              <span v-else class="muted">未评</span>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="issuesTotal > 0"
          class="pager"
          layout="total, sizes, prev, pager, next"
          :total="issuesTotal"
          :current-page="issuesPage"
          :page-size="issuesPageSize"
          :page-sizes="[20, 50, 100]"
          @current-change="onIssuesPage"
          @size-change="onIssuesSize"
        />
      </div>
    </section>

    <!-- 问题详情抽屉：完整问答 + 参考来源 + 上下文状态 -->
    <el-drawer v-model="drawer.visible" title="问题详情" size="42%">
      <div v-if="drawer.row" class="issue-detail">
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="提问时间">{{ fmtTime(drawer.row.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="课程">{{ drawer.row.course_name }}</el-descriptions-item>
          <el-descriptions-item label="章节">{{ drawer.row.catalog_title || '课程级提问' }}</el-descriptions-item>
          <el-descriptions-item label="学生">{{ drawer.row.student_name || '匿名' }}</el-descriptions-item>
          <el-descriptions-item label="学生评价">
            {{ drawer.row.feedback === 1 ? '有用' : drawer.row.feedback === -1 ? '无用' : '未评价' }}
          </el-descriptions-item>
          <el-descriptions-item label="上下文状态">
            <span v-if="drawer.row.degraded_level > 0">L{{ drawer.row.degraded_level }} 降级</span>
            <span v-else>正常</span>
            <small v-if="drawer.row.skip_retrieval" class="block">纯图片提问（跳过检索）</small>
          </el-descriptions-item>
        </el-descriptions>
        <div class="detail-block">
          <h4>学生问题</h4>
          <p class="detail-text">{{ drawer.row.question }}</p>
        </div>
        <div v-if="drawer.row.rewritten_question" class="detail-block">
          <h4>改写后检索问题</h4>
          <p class="detail-text muted">{{ drawer.row.rewritten_question }}</p>
        </div>
        <div class="detail-block">
          <h4>AI 回答</h4>
          <div class="qa-answer" v-html="renderQaAnswer(drawer.row.answer || '')"></div>
          <CitedSources v-if="drawer.row.cited_chunks?.length" :cited="drawer.row.cited_chunks" />
          <p v-else-if="!drawer.row.skip_retrieval" class="empty-cite">该回答未引用任何课程片段（检索为空）</p>
          <p v-else class="empty-cite">纯图片提问：直接走视觉理解，未检索课程资料</p>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'
import { ElTooltip } from 'element-plus'
import { InfoFilled, QuestionFilled, Refresh, WarningFilled } from '@element-plus/icons-vue'
import { getTeacherQAQualityStats, listTeacherQAIssues } from '@/api/knowledge'
import CitedSources from '@/components/qa/CitedSources.vue'
import { renderQaAnswer } from '@/utils/markdown'

// 指标说明气泡：统计字样右上角的圆形小图标（SVG 问号，非文字字形），悬停显示口径解释
// 坑：span 由 ElTooltip 默认插槽内的 h() 创建，拿不到本组件作用域 ID——
// 普通 .qa-help 选择器（编译为 .qa-help[data-v-xxx]）永远匹配不上，样式必须用 :deep() 后代选择器
const QaHelp = defineComponent({
  name: 'QaHelp',
  props: { text: { type: String, required: true } },
  setup(props) {
    return () => h(ElTooltip, { content: props.text, placement: 'top', 'show-after': 150 }, {
      default: () => h('span', { class: 'qa-help' }, [h(QuestionFilled)]),
    })
  },
})

// 周期三方式并存：快捷/自定义起止走日历窗（start/end），近 N 天走滚动窗（days）；
// 默认 30 天（教师数据量小于平台全量，窗口更长信号更稳）
const period = reactive({ mode: 'days', days: 30, range: [] })
const rangeShortcuts = [
  { text: '今天', value: () => { const t = new Date(); return [t, t] } },
  { text: '近 7 天', value: () => { const t = new Date(); const s = new Date(t); s.setDate(s.getDate() - 6); return [s, t] } },
  { text: '近 30 天', value: () => { const t = new Date(); const s = new Date(t); s.setDate(s.getDate() - 29); return [s, t] } },
  { text: '近 90 天', value: () => { const t = new Date(); const s = new Date(t); s.setDate(s.getDate() - 89); return [s, t] } },
]
function periodParams() {
  if (period.mode === 'range' && period.range?.length === 2) {
    return { start: period.range[0], end: period.range[1] }
  }
  return { days: period.days }
}

// ---------------- 统计 ----------------
const qaLoading = ref(false)
const qa = ref(null)

async function loadQA() {
  qaLoading.value = true
  try {
    qa.value = await getTeacherQAQualityStats(periodParams())
  } finally { qaLoading.value = false }
}

const qaWindowText = computed(() => {
  const w = qa.value?.window
  if (!w) return ''
  const s = w.start.slice(0, 10), e = w.end.slice(0, 10)
  const ps = w.previous_start.slice(0, 10), pe = w.previous_end.slice(0, 10)
  return `${s} ~ ${e}（${w.days} 天）· 对比上周期 ${ps} ~ ${pe}`
})

function fmtNum(v) {
  if (v == null) return '0'
  if (v >= 10000) return (v / 10000).toFixed(1).replace(/\.0$/, '') + ' 万'
  return String(v)
}
function fmtPct(v) { return v == null ? '—' : (v * 100).toFixed(1) + '%' }
function fmtTime(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '' }

// 指标卡着色：badAbove/warnAbove 越高越坏（为空率/兜底率/降级率）；
// badBelow/warnBelow 越低越坏（好评率）
function qaRateTone(value, { badAbove, warnAbove, badBelow, warnBelow } = {}) {
  if (value == null) return ''
  if (badAbove != null) return value > badAbove ? 'bad' : (warnAbove != null && value > warnAbove ? 'warn' : '')
  if (badBelow != null) return value < badBelow ? 'bad' : (warnBelow != null && value < warnBelow ? 'warn' : '')
  return ''
}
// 环比：涨红跌绿（中文语境）；好评率反向（goodWhenUp）；上周期无数据给「新增」
function deltaInfo(cur, prev, { goodWhenUp = false } = {}) {
  if (cur == null || prev == null) return { text: '—', tone: 'none' }
  if (prev === 0) {
    if (cur === 0) return { text: '持平', tone: 'flat' }
    return { text: '新增', tone: goodWhenUp ? 'good' : 'up' }
  }
  const ratio = (cur - prev) / prev
  if (Math.abs(ratio) < 0.001) return { text: '持平', tone: 'flat' }
  const text = `${ratio > 0 ? '↑' : '↓'} ${(Math.abs(ratio) * 100).toFixed(0)}%`
  if (goodWhenUp) return { text, tone: ratio > 0 ? 'good' : 'bad' }
  return { text, tone: ratio > 0 ? 'up' : 'down' }
}
function qaDelta(cur, prev, options = {}) {
  return deltaInfo(cur, prev, options)
}

// 日趋势：为空率（红）/ 好评率（绿）双折线；null（当天无提问）断开
const qaTrendDays = computed(() => qa.value?.daily || [])
const qaPointCount = computed(() => qaTrendDays.value.length)
const qaTrendMax = computed(() => Math.max(
  0,
  ...qaTrendDays.value.flatMap(r => [r.empty_rate || 0, r.feedback_rate || 0]),
))
const qaAxisMax = computed(() => {
  const m = qaTrendMax.value
  if (m <= 0.1) return 0.2
  if (m <= 0.25) return 0.5
  if (m <= 0.5) return 0.75
  return 1
})
const qaGridValues = computed(() => [qaAxisMax.value, qaAxisMax.value / 2, 0])
const QA_PLOT = { top: 12, height: 178, left: 44, right: 16 }
function qaX(i, n) {
  if (n <= 1) return (680 - QA_PLOT.left - QA_PLOT.right) / 2 + QA_PLOT.left
  return QA_PLOT.left + (i * (680 - QA_PLOT.left - QA_PLOT.right)) / (n - 1)
}
function qaY(v) { return QA_PLOT.top + QA_PLOT.height - (v / qaAxisMax.value) * QA_PLOT.height }
function qaSeries(key) {
  const rows = qaTrendDays.value
  const segments = []
  let cur = []
  rows.forEach((r, i) => {
    if (r[key] == null) {
      if (cur.length) { segments.push(cur.join(' ')); cur = [] }
      return
    }
    cur.push(`${qaX(i, rows.length)},${qaY(r[key])}`)
  })
  if (cur.length) segments.push(cur.join(' '))
  return segments
}
const qaEmptySegments = computed(() => qaSeries('empty_rate'))
const qaFeedbackSegments = computed(() => qaSeries('feedback_rate'))
const qaLabelEvery = computed(() => Math.max(1, Math.ceil(qaPointCount.value / 10)))

// 降级分布（L0 未降级 / L1 丢一半 / L2 近两轮 / L4 全丢）
const qaDegradedLabels = { L0: 'L0 未降级', L1: 'L1 丢一半', L2: 'L2 近两轮', L4: 'L4 全丢' }
const qaDegradedColors = {
  L0: 'linear-gradient(90deg,#93c5fd,#2563eb)',
  L1: 'linear-gradient(90deg,#c4b5fd,#7c3aed)',
  L2: 'linear-gradient(90deg,#7dd3fc,#0284c7)',
  L4: 'linear-gradient(90deg,#fca5a5,#dc2626)',
}
const qaDegradedRows = computed(() => {
  const d = qa.value?.degraded
  if (!d) return []
  const total = qa.value?.totals?.questions || 0
  const max = Math.max(1, ...['L0', 'L1', 'L2', 'L4'].map(k => d[k] || 0))
  return ['L0', 'L1', 'L2', 'L4'].map(k => ({
    key: k,
    label: qaDegradedLabels[k],
    count: d[k] || 0,
    width: Math.max(2, ((d[k] || 0) / max) * 100),
    pct: total ? (((d[k] || 0) / total) * 100).toFixed(1) + '%' : '—',
    color: qaDegradedColors[k],
  }))
})

// 引用来源分布（material 资料 / script 讲解稿 / ppt 课件 / script+ppt 与 ppt+script 同义组合 / unknown 历史记录无来源键）
// 后端已把 ppt+script 归一为 script+ppt（qa_stats._SOURCE_KEY_ALIAS），此处补映射仅为防御 raw key 裸奔
const qaSourceLabels = { material: '知识库资料', script: '讲解稿', ppt: '课件 PPT', 'ppt+script': '讲解稿+课件', 'script+ppt': '讲解稿+课件', unknown: '其他' }
const qaSourceColors = { material: 'linear-gradient(90deg,#93c5fd,#2563eb)', script: 'linear-gradient(90deg,#c4b5fd,#7c3aed)', ppt: 'linear-gradient(90deg,#7dd3fc,#0284c7)', 'ppt+script': 'linear-gradient(90deg,#5eead4,#0d9488)', 'script+ppt': 'linear-gradient(90deg,#5eead4,#0d9488)', unknown: 'linear-gradient(90deg,#cbd5e1,#94a3b8)' }
const qaSourceRows = computed(() => {
  const src = qa.value?.by_source || {}
  const entries = Object.entries(src)
  if (!entries.length) return []
  const total = entries.reduce((a, [, c]) => a + c, 0)
  const max = Math.max(...entries.map(([, c]) => c))
  return entries
    .map(([key, count]) => ({
      key,
      label: qaSourceLabels[key] || key,
      count,
      width: Math.max(2, (count / max) * 100),
      pct: total ? ((count / total) * 100).toFixed(1) + '%' : '—',
      color: qaSourceColors[key] || qaSourceColors.unknown,
    }))
    .sort((a, b) => b.count - a.count)
})

// ---------------- 问题下钻 ----------------
const issueType = ref('all')
const issueCourse = ref('')
const issues = ref([]), issuesTotal = ref(0), issuesPage = ref(1), issuesPageSize = ref(20), issuesLoading = ref(false)

// 课程下拉取自有提问的课程（窗口内无提问的课程没有可下钻的问题）
const courseOptions = computed(() => qa.value?.by_course || [])

async function loadIssues() {
  issuesLoading.value = true
  try {
    const params = { ...periodParams(), type: issueType.value, page: issuesPage.value, page_size: issuesPageSize.value }
    if (issueCourse.value) params.course = issueCourse.value
    const result = await listTeacherQAIssues(params)
    issues.value = result?.results || []
    issuesTotal.value = result?.total || 0
  } finally { issuesLoading.value = false }
}
function reloadIssues() { issuesPage.value = 1; loadIssues() }
function onIssuesPage(page) { issuesPage.value = page; loadIssues() }
function onIssuesSize(size) { issuesPageSize.value = size; issuesPage.value = 1; loadIssues() }

// 问题详情抽屉
const drawer = reactive({ visible: false, row: null })
function openIssue(row) {
  drawer.row = row
  drawer.visible = true
}

// ---------------- 周期联动 ----------------
function reloadAll() { loadQA(); reloadIssues() }
function onRangeChange(value) {
  if (!value) { period.range = []; return }  // 清空不改变当前生效窗口
  period.mode = 'range'
  reloadAll()
}
function onDaysChange() {
  period.mode = 'days'
  reloadAll()
}

onMounted(reloadAll)
</script>

<style scoped>
.qa-quality{color:#0f172a}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:22px;margin-bottom:22px}.eyebrow{margin-bottom:6px;color:#2563eb;font-size:12px;font-weight:850;letter-spacing:.16em}h1,h2,h3,h4,p{margin:0}h1{font-size:30px}.page-head p{margin-top:7px;color:#8190a8}
.stats-panel{display:grid;gap:16px}.stats-toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:14px 18px;border:1px solid #e5edf8;border-radius:22px;background:rgba(255,255,255,.94);box-shadow:0 16px 40px rgba(37,99,235,.07)}.toolbar-note{color:#94a3b8;font-size:12px;line-height:1.5}.window-note{padding:0 4px;color:#64748b;font-size:12px}.days-input{display:inline-flex;align-items:center;gap:6px}.days-label{color:#64748b;font-size:13px}
.alerts{display:grid;gap:8px}.alert{display:flex;align-items:flex-start;gap:8px;padding:11px 15px;border-radius:14px;font-size:13px;line-height:1.6}.alert.warning{background:#fffbeb;border:1px solid #fde68a;color:#b45309}.alert.error{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c}.alert.info{background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8}.alert .el-icon{margin-top:2px;flex:0 0 auto}
.stat-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.stat-card{padding:15px 17px;display:grid;gap:3px;border:1px solid #e5edf8;border-radius:18px;background:rgba(255,255,255,.94);box-shadow:0 16px 40px rgba(37,99,235,.07)}.stat-card small{color:#94a3b8;font-size:12px}.stat-card strong{font-size:24px;color:#0f172a}.stat-card strong.good{color:#16a34a}.stat-card strong.bad{color:#dc2626}.stat-card strong.warn{color:#d97706}.stat-card .sub{color:#94a3b8;font-size:12px}
/* 环比：涨红跌绿（成功率反向：good/bad） */
.delta{font-size:12px;font-weight:700}.delta.up,.delta.bad{color:#dc2626}.delta.down,.delta.good{color:#16a34a}.delta.flat,.delta.none{color:#94a3b8;font-weight:400}
.chart-card,.dist-card,.logs-card{padding:18px;border:1px solid #e5edf8;border-radius:22px;background:rgba(255,255,255,.94);box-shadow:0 16px 40px rgba(37,99,235,.07)}
.chart-card h3,.dist-card h3,.logs-card h3{font-size:16px;margin-bottom:12px}.chart-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px}.chart-head h3{margin-bottom:0}.trend-chart{width:100%;height:220px;display:block}.axis-label{font-size:10px;fill:#94a3b8}
.chart-legend{display:flex;align-items:center;gap:18px;margin:10px 0 0;color:#64748b;font-size:12px}.chart-legend .dot{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:5px;vertical-align:-1px}.chart-legend .dot-red{background:#dc2626}.chart-legend .dot-green{background:#16a34a}
.dist-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:6px}.dist-head h3{margin-bottom:0}
.dist-row{display:grid;grid-template-columns:minmax(88px,150px) 1fr 58px 52px;align-items:center;gap:10px;width:100%;padding:7px 10px}.dist-static{border:0;background:transparent;text-align:left;font:inherit;color:inherit}
.dist-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:600}
.dist-bar{height:8px;border-radius:5px;background:#eef3fa;overflow:hidden}.dist-bar i{display:block;height:100%;border-radius:5px}
.dist-calls{font-size:13px;font-weight:700;text-align:right}.dist-pct{font-size:12px;color:#64748b;text-align:right}
.logs-head{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:12px}.logs-filters{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
/* 圆形小图标徽章：QaHelp 的 span 无作用域 ID（见 script 注释），必须 :deep() */
:deep(.qa-help){display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;margin-left:5px;border-radius:50%;background:#f1f5f9;color:#64748b;font-size:11px;cursor:help;vertical-align:-1px;flex:0 0 auto;transition:background .15s,color .15s}:deep(.qa-help:hover){background:#dbeafe;color:#2563eb}
.muted{color:#64748b;font-size:12px}
.qa-quality-table,.qa-issues-table{width:100%;font-size:13px}.qa-quality-table :deep(.el-table .cell),.qa-issues-table :deep(.el-table .cell){white-space:nowrap}
/* 全局隐藏 EP 滚动条会让表格列总宽超容器时看不到横滚条（假截断）：本表需要时显式放行 */
.qa-quality-table :deep(.el-table .el-scrollbar__bar.is-horizontal),.qa-issues-table :deep(.el-table .el-scrollbar__bar.is-horizontal){display:block!important}
.qa-issues-table :deep(.el-table__row){cursor:pointer}
.issue-tags{display:inline-flex;gap:5px;flex-wrap:wrap}
.feedback-good{color:#16a34a;font-weight:600}.feedback-bad{color:#dc2626;font-weight:600}
.pager{margin-top:14px;justify-content:flex-end}
.ellipsis{display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:bottom}
/* 详情抽屉 */
.issue-detail :deep(.el-descriptions__content){word-break:break-all;line-height:1.6}
.detail-block{margin-top:18px}.detail-block h4{margin-bottom:8px;color:#334155;font-size:14px}
.detail-text{color:#0f172a;font-size:13px;line-height:1.8;white-space:pre-wrap;word-break:break-word}.detail-text.muted{color:#64748b}
.qa-answer{color:#0f172a;font-size:13px;line-height:1.8;word-break:break-word}.qa-answer :deep(p){margin:0 0 8px}.qa-answer :deep(strong){font-weight:700}.qa-answer :deep(ul),.qa-answer :deep(ol){padding-left:20px;margin:0 0 8px}.qa-answer :deep(.cite-sup){color:#2563eb;cursor:pointer;font-weight:600;padding:0 1px}
.empty-cite{margin-top:10px;color:#94a3b8;font-size:12px}
.block{display:block;margin-top:3px;color:#64748b;font-size:12px}
@media(max-width:1200px){.stat-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:720px){.stat-cards{grid-template-columns:1fr}}
</style>
