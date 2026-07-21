<template>
  <div class="page-container stu-detail-page">
    <!-- 学生档案头部（返回 + 身份 + 状态一体） -->
    <div class="hero-card">
      <button class="back-circle" title="返回" @click="goBack">
        <el-icon :size="17"><ArrowLeft /></el-icon>
      </button>
      <span class="profile-avatar" :style="{ background: avatarBg(detail?.student?.name || '') }">
        <img
          v-if="detail?.student?.avatar"
          :src="detail.student.avatar"
          :alt="`${detail.student.name || '学生'}的头像`"
        />
        <template v-else>{{ (detail?.student?.name || '…').charAt(0) }}</template>
      </span>
      <div class="hero-info">
        <div class="hero-name">{{ detail?.student?.name || '学生详情' }}</div>
        <div class="hero-meta">
          <template v-if="detail">
            用户名 {{ detail.student.username }} · 加入班级于 {{ fmtDate(detail.student.joined_at) }}
          </template>
          <template v-else>该学生的练习、作业与考试情况</template>
        </div>
      </div>
      <div v-if="detail" class="hero-side">
        <div class="hero-tags">
          <span class="subtitle-chip">{{ detail.class_name }}</span>
          <span class="subtitle-chip">{{ detail.course_name }}</span>
          <el-tag v-for="w in detail.summary.warnings" :key="w" type="danger" size="small" effect="light" round class="warn-pulse">{{ w }}</el-tag>
          <el-tag v-if="!detail.summary.warnings.length" type="success" size="small" effect="light" round>状态正常</el-tag>
        </div>
        <div class="hero-last">
          最近学习：{{ detail.summary.last_active ? fmtDateTime(detail.summary.last_active) : '从未' }}
        </div>
      </div>
      <el-select
        v-if="courseOptions.length > 1"
        v-model="courseId"
        class="course-select"
        style="width: 200px"
        @change="load"
      >
        <el-option v-for="c in courseOptions" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
    </div>

    <div v-loading="loading" class="detail-wrap">
      <template v-if="detail">
        <!-- 学习概览 -->
        <el-row :gutter="16" class="stat-row">
          <el-col :xs="12" :sm="8" :lg="4" v-for="card in cards" :key="card.label">
            <div class="stat-card">
              <div class="stat-icon" :class="card.color">
                <el-icon :size="22"><component :is="card.icon" /></el-icon>
              </div>
              <div>
                <div class="stat-title">{{ card.label }}</div>
                <div class="stat-value">{{ 'num' in card ? (card.num == null ? '—' : fmtNum(displayed[card.label] ?? 0) + card.suffix) : card.value }}</div>
              </div>
            </div>
          </el-col>
        </el-row>

        <!-- 章节学习进度 -->
        <div class="data-card section-card">
          <div class="section-title">
            章节学习进度
            <span class="section-sub">按章节统计题库练习覆盖情况</span>
          </div>
          <div v-if="detail.progress?.chapters?.length" class="chapter-list">
            <div v-for="ch in detail.progress.chapters" :key="ch.catalog_id" class="chapter-item">
              <div class="chapter-head">
                <span class="chapter-title">{{ ch.title }}</span>
                <span v-if="ch.questions_total" class="chapter-meta">
                  已练 {{ ch.questions_practiced }}/{{ ch.questions_total }} 题
                  <template v-if="ch.accuracy != null"> · 正确率 {{ ch.accuracy }}%</template>
                </span>
                <span v-else class="chapter-meta chapter-none">暂无题目</span>
              </div>
              <div v-if="ch.questions_total" class="chapter-bar">
                <el-progress
                  :percentage="barsReady ? ch.coverage : 0"
                  :stroke-width="8"
                  :color="coverageColor(ch.coverage)"
                  :show-text="false"
                  style="flex: 1"
                />
                <span class="chapter-pct" :style="{ color: coverageColor(ch.coverage) }">{{ ch.coverage }}%</span>
              </div>
            </div>
          </div>
          <div v-else class="section-empty">暂无章节练习数据</div>
        </div>

        <!-- 作业 / 考试 -->
        <el-row :gutter="16">
          <el-col :md="12" :xs="24">
            <div class="data-card section-card">
              <div class="section-title">作业情况</div>
              <div v-if="detail.homeworks.length" class="item-list">
                <div v-for="hw in detail.homeworks" :key="hw.id" class="detail-item">
                  <span class="item-main">{{ hw.title }}</span>
                  <template v-if="hw.submitted">
                    <el-tag size="small" type="success" effect="light">{{ hw.correct_status }}</el-tag>
                    <span v-if="hw.score != null" class="item-score">{{ hw.score }} 分</span>
                    <el-tag v-if="hw.is_late" size="small" type="warning" effect="plain">迟交</el-tag>
                  </template>
                  <el-tag v-else size="small" type="danger" effect="light">未提交</el-tag>
                </div>
              </div>
              <div v-else class="section-empty">该课程暂无已发布作业</div>
            </div>
          </el-col>
          <el-col :md="12" :xs="24">
            <div class="data-card section-card">
              <div class="section-title">考试情况</div>
              <div v-if="detail.exams.length" class="item-list">
                <div v-for="ex in detail.exams" :key="ex.id" class="detail-item">
                  <span class="item-main">{{ ex.name }}</span>
                  <template v-if="ex.taken">
                    <el-tag size="small" type="success" effect="light">已参加</el-tag>
                    <span v-if="ex.score != null" class="item-score">{{ ex.score }} 分</span>
                  </template>
                  <el-tag v-else size="small" type="danger" effect="light">缺考</el-tag>
                </div>
              </div>
              <div v-else class="section-empty">该课程暂无考试</div>
            </div>
          </el-col>
        </el-row>

        <!-- 最近练习 -->
        <div class="data-card section-card">
          <div class="section-title">
            最近练习
            <span v-if="detail.recent_records.length" class="section-sub">最近 {{ detail.recent_records.length }} 条答题记录</span>
          </div>
          <div v-if="detail.recent_records.length" class="item-list">
            <div v-for="(r, i) in detail.recent_records" :key="i" class="detail-item">
              <el-icon :size="17" :color="r.is_correct ? '#10b981' : '#ef4444'" class="record-icon">
                <CircleCheckFilled v-if="r.is_correct" />
                <CircleCloseFilled v-else />
              </el-icon>
              <span class="item-main">{{ r.stem }}</span>
              <span class="record-meta">{{ r.qtype }} · {{ fmtDateTime(r.submitted_at) }}</span>
            </div>
          </div>
          <div v-else class="section-empty">还没有练习记录</div>
        </div>
      </template>
      <el-empty v-else-if="!loading" description="未找到该学生的统计数据" />
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, TrendCharts, Notebook, Files, Medal, Trophy, Flag,
  CircleCheckFilled, CircleCloseFilled,
} from '@element-plus/icons-vue'
import { listClasses } from '@/api/classroom'
import { getClassStudentDetail } from '@/api/analytics'

const route = useRoute()
const router = useRouter()
const classId = Number(route.params.classId)
const studentId = Number(route.params.studentId)

const loading = ref(false)
const detail = ref(null)
const courseId = ref(Number(route.query.course) || null)
const courseOptions = ref([])

const cards = computed(() => {
  const s = detail.value?.summary || {}
  const p = detail.value?.progress || {}
  return [
    { label: '学习进度', num: p.percent, suffix: '%', icon: 'Flag', color: 'blue' },
    { label: '练习正确率', num: s.accuracy, suffix: '%', icon: 'TrendCharts', color: 'green' },
    { label: '章节练习', value: `${s.practice_correct ?? 0}/${s.practice_total ?? 0} 题`, icon: 'Notebook', color: 'purple' },
    { label: '作业提交', value: `${s.homework_submitted ?? 0}/${s.homework_total ?? 0}`, icon: 'Files', color: 'orange' },
    { label: '考试参加', value: `${s.exam_taken ?? 0}/${s.exam_total ?? 0}`, icon: 'Medal', color: 'orange' },
    { label: '考试均分', num: s.avg_exam_score, suffix: '', icon: 'Trophy', color: 'red' },
  ]
})

// 数字滚动动画（count-up）
const displayed = ref({})
const barsReady = ref(false)

function fmtNum(v) {
  if (v == null) return '—'
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}

function animateNumbers(targets) {
  const duration = 700
  const start = performance.now()
  const tick = (t) => {
    const k = Math.min(1, (t - start) / duration)
    const ease = 1 - Math.pow(1 - k, 3)
    const out = {}
    for (const [key, val] of Object.entries(targets)) {
      out[key] = Math.round(val * ease * 10) / 10
    }
    displayed.value = out
    if (k < 1) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

const AVATAR_COLORS = ['#2563eb', '#10b981', '#f59e0b', '#8b5cf6', '#06b6d4', '#f97316']
function avatarBg(name) {
  let hash = 0
  for (const ch of name || '') hash = (hash * 31 + ch.codePointAt(0)) >>> 0
  const color = AVATAR_COLORS[hash % AVATAR_COLORS.length]
  return `linear-gradient(135deg, ${color} 0%, ${color}cc 100%)`
}

function fmtDate(t) {
  if (!t) return '—'
  const d = new Date(t)
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}
function fmtDateTime(t) {
  if (!t) return '—'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${fmtDate(t)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function coverageColor(v) {
  if (v >= 80) return '#10b981'
  if (v >= 40) return '#f59e0b'
  return '#ef4444'
}

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/teacher/classes')
}

async function loadCourseOptions() {
  const data = await listClasses()
  const list = data.results ?? data
  const classroom = list.find((item) => item.id === classId)
  const ids = classroom?.courses?.length
    ? classroom.courses
    : (classroom?.course ? [classroom.course] : [])
  const names = classroom?.course_names || []
  courseOptions.value = ids.map((id, i) => ({ id, name: names[i] || classroom?.course_name || `课程 ${id}` }))
  if (!courseId.value && courseOptions.value.length) {
    courseId.value = courseOptions.value[0].id
  }
}

async function load() {
  loading.value = true
  try {
    detail.value = await getClassStudentDetail(classId, studentId, {
      course: courseId.value ?? undefined,
    })
    // 数字滚动 + 进度条生长
    const s = detail.value?.summary || {}
    const p = detail.value?.progress || {}
    animateNumbers({
      学习进度: p.percent ?? 0,
      练习正确率: s.accuracy ?? 0,
      考试均分: s.avg_exam_score ?? 0,
    })
    barsReady.value = false
    nextTick(() => {
      barsReady.value = true
    })
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadCourseOptions()
  load()
})
</script>

<style scoped>
.stu-detail-page :deep(.page-header) {
  min-height: 58px;
  margin-bottom: 18px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.back-circle {
  width: 36px;
  height: 36px;
  display: grid;
  flex: 0 0 36px;
  place-items: center;
  border: 1px solid var(--gray-200);
  border-radius: 50%;
  background: #fff;
  color: var(--gray-500);
  cursor: pointer;
  transition: all 0.18s ease;
}
.back-circle:hover {
  border-color: var(--primary-500);
  color: var(--primary-600);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
  transform: translateX(-2px);
}
.subtitle-chip {
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.9);
  color: var(--gray-500);
  font-size: 12px;
}
.course-select :deep(.el-select__wrapper) {
  min-height: 40px;
  border-radius: 12px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbe5f2;
}
.detail-wrap {
  min-height: 320px;
}

/* 学生档案头部卡 */
.hero-card {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
  padding: 18px 22px;
  border: 1px solid rgba(37, 99, 235, 0.08);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.9), rgba(255, 255, 255, 0.94) 55%);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.07);
  flex-wrap: wrap;
}
.hero-info {
  min-width: 0;
  flex: 1;
}
.profile-avatar {
  width: 54px;
  height: 54px;
  display: flex;
  flex: 0 0 54px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #fff;
  font-size: 21px;
  font-weight: 750;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.16);
  overflow: hidden;
}
.profile-avatar img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}
.hero-name {
  color: var(--gray-900);
  font-size: 20px;
  font-weight: 750;
}
.hero-meta {
  margin-top: 4px;
  color: var(--gray-500);
  font-size: 13px;
}
.hero-side {
  display: grid;
  gap: 6px;
  justify-items: end;
}
.hero-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.hero-last {
  color: var(--gray-400);
  font-size: 12.5px;
}

/* 概览卡 */
.stat-row {
  margin-bottom: 8px;
}
.stat-card {
  min-height: 92px;
  border: 1px solid rgba(37, 99, 235, 0.08);
  border-radius: var(--radius-lg);
  padding: 16px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.07);
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}
.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-icon.blue { background: var(--primary-50); color: var(--primary-600); }
.stat-icon.green { background: #ecfdf5; color: var(--success); }
.stat-icon.orange { background: #fff7ed; color: var(--warning); }
.stat-icon.purple { background: #f5f3ff; color: #8b5cf6; }
.stat-icon.red { background: #fef2f2; color: var(--danger); }
.stat-title { font-size: 13px; color: var(--gray-500); font-weight: 650; }
.stat-value { margin-top: 3px; font-size: 21px; font-weight: 800; color: var(--gray-900); }

/* 区块卡 */
.section-card {
  margin-bottom: 16px;
  padding: 18px 20px;
  border-radius: var(--radius-lg);
  height: calc(100% - 16px);
  box-sizing: border-box;
}
.section-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 12px;
  color: var(--gray-800);
  font-size: 15px;
  font-weight: 750;
}
.section-sub {
  color: var(--gray-400);
  font-size: 12px;
  font-weight: 400;
}
.item-list {
  display: grid;
  gap: 8px;
}
.detail-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border-radius: 12px;
  background: #fff;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.9);
}
.item-main {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--gray-700);
  font-size: 13.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.item-score {
  color: var(--primary-600);
  font-size: 13px;
  font-weight: 700;
}
.record-icon {
  flex-shrink: 0;
}
.record-meta {
  flex-shrink: 0;
  color: var(--gray-400);
  font-size: 12px;
}
.section-empty {
  padding: 22px 14px;
  border-radius: 12px;
  background: #f8fafc;
  color: var(--gray-400);
  font-size: 13px;
  text-align: center;
}

/* 章节学习进度 */
.chapter-list {
  display: grid;
  gap: 14px;
}
.chapter-item {
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.9);
}
.chapter-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.chapter-title {
  overflow: hidden;
  color: var(--gray-700);
  font-size: 13.5px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chapter-meta {
  flex-shrink: 0;
  color: var(--gray-400);
  font-size: 12px;
}
.chapter-none {
  color: var(--gray-300);
}
.chapter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.chapter-bar :deep(.el-progress-bar__outer) {
  background: var(--gray-100);
}
.chapter-pct {
  flex-shrink: 0;
  width: 38px;
  text-align: right;
  font-size: 13px;
  font-weight: 700;
}

@media (max-width: 768px) {
  .hero-side {
    justify-items: start;
  }
  .hero-tags {
    justify-content: flex-start;
  }
}
</style>
