<template>
  <div class="page-container admin-overview" v-loading="loading">
    <header class="page-head">
      <div>
        <div class="eyebrow">PLATFORM ADMIN</div>
        <h1>管理概览</h1>
        <p>集中查看账号规模、教学资源运行情况与平台趋势。</p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" @click="load">刷新数据</el-button>
        <el-button :icon="Tickets" @click="router.push('/admin/audit')">操作审计</el-button>
        <el-button type="primary" :icon="UserFilled" @click="router.push('/admin/users')">管理用户</el-button>
      </div>
    </header>

    <el-alert v-if="loadError" class="load-error" type="error" show-icon :closable="false" :title="loadError" />

    <section class="metric-grid">
      <article
        v-for="card in metrics" :key="card.label" class="metric-card clickable"
        :style="{ '--metric-color': card.color, '--metric-bg': card.bg }"
        @click="router.push(card.to)"
      >
        <span class="metric-icon"><el-icon><component :is="card.icon" /></el-icon></span>
        <div class="metric-copy">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.note }}</small>
          <StatDeltaTag v-if="card.delta" v-bind="card.delta" />
        </div>
      </article>
    </section>

    <section v-if="loaded" class="health-strip">
      <div class="health-title">
        <span class="health-dot"></span>
        <div><strong>业务数据库实时统计</strong><small>更新时间：{{ refreshedAt }}</small></div>
      </div>
      <div class="health-items">
        <span>活跃账号 <b>{{ activeRate }}%</b></span>
        <span>启用课程 <b>{{ courseRate }}%</b></span>
        <span>开课班级 <b>{{ classRate }}%</b></span>
        <span v-if="trends.summary?.active_students">
          周期活跃学生 <b>{{ trends.summary.active_students.current }}</b>
        </span>
      </div>
    </section>

    <section class="data-panel trend-panel">
      <div class="panel-head">
        <div><h2>平台趋势</h2><p>新增用户 / 课程 / 班级与日活跃学生</p></div>
        <el-radio-group v-model="trendDays" size="small" @change="loadTrends">
          <el-radio-button :value="7">近 7 天</el-radio-button>
          <el-radio-button :value="30">近 30 天</el-radio-button>
        </el-radio-group>
      </div>
      <TrendChart :labels="trendLabels" :series="trendSeries" :loading="trendLoading" />
    </section>

    <section class="overview-grid">
      <article class="data-panel">
        <div class="panel-head">
          <div><h2>待办与异常</h2><p>需要关注的积压事项，点击前往处理</p></div>
        </div>
        <div v-if="alertLoading" class="empty">加载中…</div>
        <AlertBanner v-else :items="alerts" @jump="onAlertJump" />
      </article>

      <article class="data-panel">
        <div class="panel-head">
          <div><h2>最近新增用户</h2><p>新注册与后台创建的账号</p></div>
          <el-button link type="primary" @click="router.push('/admin/users')">查看全部 <el-icon><ArrowRight /></el-icon></el-button>
        </div>
        <div v-if="!data.recent_users?.length" class="empty">暂无用户数据</div>
        <div v-else class="user-list">
          <div v-for="item in data.recent_users" :key="item.id" class="user-row">
            <el-avatar :size="40" :src="item.avatar || ''" :icon="UserFilled" />
            <div class="row-main"><strong>{{ item.real_name || item.username }}</strong><span>@{{ item.username }}</span></div>
            <el-tag size="small" effect="light" :type="roleType(item.role)">{{ item.role_display }}</el-tag>
            <time>{{ formatDate(item.date_joined) }}</time>
          </div>
        </div>
      </article>

      <article class="data-panel">
        <div class="panel-head">
          <div><h2>最近创建课程</h2><p>课程状态及关联规模</p></div>
          <el-button link type="primary" @click="router.push('/admin/teaching')">教学监管 <el-icon><ArrowRight /></el-icon></el-button>
        </div>
        <div v-if="!data.recent_courses?.length" class="empty">暂无课程数据</div>
        <div v-else class="course-list">
          <div v-for="item in data.recent_courses" :key="item.id" class="course-row">
            <span class="course-icon"><el-icon><Reading /></el-icon></span>
            <div class="row-main"><strong>{{ item.name }}</strong><span>{{ item.teacher_name || item.teacher_username }} · {{ item.term || '未设置学期' }}</span></div>
            <div class="course-count"><b>{{ item.student_count }}</b><span>学生</span></div>
            <el-tag size="small" effect="light" :type="courseType(item.status)">{{ item.status_display }}</el-tag>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, DataAnalysis, Reading, Refresh, School, Tickets, UserFilled } from '@element-plus/icons-vue'
import { getAdminAlerts, getAdminOverview, getAdminTrends } from '@/api/admin'
import TrendChart from '@/components/charts/TrendChart.vue'
import StatDeltaTag from '@/components/admin/StatDeltaTag.vue'
import AlertBanner from '@/components/admin/AlertBanner.vue'

const router = useRouter()
const loading = ref(false)
const loaded = ref(false)
const loadError = ref('')
const data = reactive({ meta: {}, users: {}, teaching: {}, recent_users: [], recent_courses: [] })

// ---- 趋势 ----
const trendDays = ref(7)
const trendLoading = ref(false)
const trends = reactive({ days: 7, daily: [], summary: {} })

// ---- 待办与异常 ----
const alertLoading = ref(false)
const alerts = ref([])

const percent = (part, total) => total ? Math.round((part / total) * 100) : 0
const activeRate = computed(() => percent(data.users.active, data.users.total))
const courseRate = computed(() => percent(data.teaching.active_courses, data.teaching.courses))
const classRate = computed(() => percent(data.teaching.open_classes, data.teaching.classes))
const refreshedAt = computed(() => data.meta.refreshed_at
  ? new Date(data.meta.refreshed_at).toLocaleString('zh-CN', { hour12: false })
  : '尚未获取')

const deltaProps = (field, suffix) => {
  const row = trends.summary?.[field]
  return row ? { delta: row.delta, deltaPct: row.delta_pct, suffix } : null
}

const metrics = computed(() => [
  {
    label: '平台用户', to: '/admin/users',
    value: loaded.value ? data.users.total : '—',
    note: loaded.value ? `${data.users.teachers} 位教师 · ${data.users.students} 位学生 · ${data.users.admins} 位管理员` : '等待数据库返回',
    icon: UserFilled, color: '#2563eb', bg: '#eff6ff',
    delta: deltaProps('new_users', '较上周期'),
  },
  {
    label: '课程总数', to: '/admin/teaching',
    value: loaded.value ? data.teaching.courses : '—',
    note: loaded.value ? `${data.teaching.active_courses} 门正在启用` : '等待数据库返回',
    icon: Reading, color: '#8b5cf6', bg: '#f5f3ff',
    delta: deltaProps('new_courses', '较上周期'),
  },
  {
    label: '教学班级', to: '/admin/teaching',
    value: loaded.value ? data.teaching.classes : '—',
    note: loaded.value ? `${data.teaching.open_classes} 个正在开课` : '等待数据库返回',
    icon: School, color: '#10b981', bg: '#ecfdf5',
    delta: deltaProps('new_classes', '较上周期'),
  },
  {
    label: '学习关系', to: '/admin/teaching',
    value: loaded.value ? data.teaching.enrollments : '—',
    note: loaded.value ? `${data.teaching.homeworks} 份作业 · ${data.teaching.exams} 场考试` : '等待数据库返回',
    icon: DataAnalysis, color: '#f59e0b', bg: '#fff7ed',
    delta: deltaProps('active_students', '活跃学生较上周期'),
  },
])

const trendLabels = computed(() => trends.daily.map((d) => d.date.slice(5)))
const trendSeries = computed(() => [
  { name: '新增用户', color: '#2563eb', values: trends.daily.map((d) => d.new_users) },
  { name: '新增课程', color: '#8b5cf6', values: trends.daily.map((d) => d.new_courses) },
  { name: '新增班级', color: '#10b981', values: trends.daily.map((d) => d.new_classes) },
  { name: '活跃学生', color: '#f59e0b', values: trends.daily.map((d) => d.active_students) },
])

function roleType(role) { return role === 'admin' ? 'danger' : role === 'teacher' ? 'warning' : 'primary' }
function courseType(status) { return status === 'active' ? 'success' : status === 'archived' ? 'info' : 'warning' }
function formatDate(value) { return value ? new Date(value).toLocaleDateString('zh-CN') : '—' }
function onAlertJump(item) { if (item.jump_url) router.push(item.jump_url) }

async function loadTrends() {
  trendLoading.value = true
  try {
    const res = await getAdminTrends({ days: trendDays.value })
    trends.days = res.days
    trends.daily = res.daily || []
    trends.summary = res.summary || {}
  } catch {
    // 趋势失败不阻塞概览其余部分
  } finally {
    trendLoading.value = false
  }
}

async function loadAlerts() {
  alertLoading.value = true
  try {
    const res = await getAdminAlerts()
    alerts.value = res.items || []
  } catch {
    alerts.value = []
  } finally {
    alertLoading.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    Object.assign(data, await getAdminOverview())
    loaded.value = true
    loadError.value = ''
  } catch {
    loadError.value = '真实业务数据加载失败，请检查后端服务后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  loadTrends()
  loadAlerts()
})
</script>

<style scoped>
.admin-overview { color: #0f172a; }
.load-error { margin-bottom: 16px; }
.page-head { display:flex; align-items:flex-end; justify-content:space-between; gap:24px; margin-bottom:24px; }
.eyebrow { margin-bottom:6px; color:#2563eb; font-size:12px; font-weight:850; letter-spacing:.16em; }
h1,h2,p { margin:0; } h1 { font-size:30px; line-height:1.2; } .page-head p { margin-top:7px; color:#8190a8; }
.head-actions { display:flex; gap:10px; }
.metric-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; }
.metric-card,.data-panel,.health-strip { border:1px solid #e5edf8; background:rgba(255,255,255,.9); box-shadow:0 16px 38px rgba(37,99,235,.07); }
.metric-card { min-height:138px; padding:20px; border-radius:20px; display:flex; align-items:center; gap:15px; }
.metric-card.clickable { cursor:pointer; transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease; }
.metric-card.clickable:hover { transform:translateY(-3px); border-color:#bfdbfe; box-shadow:0 22px 44px rgba(37,99,235,.13); }
.metric-icon { width:50px; height:50px; border-radius:15px; display:grid; place-items:center; flex:0 0 auto; font-size:23px; color:var(--metric-color); background:var(--metric-bg); }
.metric-copy { min-width:0; display:grid; gap:3px; } .metric-copy>span { color:#718096; font-size:13px; font-weight:700; }
.metric-copy strong { font-size:27px; line-height:1.1; } .metric-copy small { color:#94a3b8; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.health-strip { margin:16px 0; padding:16px 20px; border-radius:18px; display:flex; align-items:center; justify-content:space-between; gap:20px; }
.health-title { display:flex; align-items:center; gap:11px; } .health-title>div { display:grid; gap:2px; } .health-title small { color:#94a3b8; }
.health-dot { width:10px; height:10px; border-radius:50%; background:#22c55e; box-shadow:0 0 0 6px #dcfce7; }
.health-items { display:flex; gap:28px; color:#64748b; font-size:13px; flex-wrap:wrap; } .health-items b { margin-left:5px; color:#0f172a; }
.trend-panel { border-radius:22px; padding:20px; margin-bottom:16px; }
.overview-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; }
.data-panel { border-radius:22px; padding:20px; min-height:340px; }
.panel-head { display:flex; justify-content:space-between; align-items:center; gap:12px; padding-bottom:16px; border-bottom:1px solid #edf2f8; }
.panel-head h2 { font-size:18px; } .panel-head p { margin-top:4px; color:#94a3b8; font-size:12px; }
.user-row,.course-row { min-height:62px; display:flex; align-items:center; gap:12px; border-bottom:1px solid #f1f5f9; }
.user-row:last-child,.course-row:last-child { border-bottom:0; } .row-main { min-width:0; flex:1; display:grid; gap:3px; }
.row-main strong,.row-main span { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; } .row-main span,time { color:#94a3b8; font-size:12px; }
.user-row time { width:78px; text-align:right; }.course-icon { width:40px;height:40px;border-radius:12px;display:grid;place-items:center;background:#eff6ff;color:#2563eb;font-size:18px; }
.course-count { display:grid; text-align:center;}.course-count span { color:#94a3b8;font-size:11px; }.empty { min-height:240px;display:grid;place-items:center;color:#94a3b8; }
@media(max-width:1200px){.metric-grid{grid-template-columns:repeat(2,1fr)}.overview-grid{grid-template-columns:1fr}}
@media(max-width:720px){.page-head,.health-strip{align-items:flex-start;flex-direction:column}.metric-grid{grid-template-columns:1fr}.head-actions{width:100%}.health-items{gap:14px;flex-wrap:wrap}.user-row time{display:none}}
</style>
