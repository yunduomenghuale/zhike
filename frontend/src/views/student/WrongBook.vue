<template>
  <div class="page-container">
    <div class="page-header wrong-page-header">
      <div>
        <div class="page-title-line">
          <div class="page-title">我的错题本</div>
          <span v-if="!loading" class="wrong-count">{{ filteredRows.length }} 道</span>
        </div>
        <div class="page-subtitle">自动收录练习与考试中的错题，随时复习巩固</div>
      </div>
      <el-select v-if="!fixedCourseId" v-model="courseId" class="course-filter" placeholder="全部课程" clearable @change="load">
        <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
    </div>

    <div v-loading="loading" class="wrong-list">
      <el-card v-for="(q, i) in filteredRows" :key="q.question_id" shadow="never" class="wrong-card">
        <div class="q-head">
          <div class="q-meta">
            <span class="q-idx">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="q-type">{{ q.qtype_display }}</span>
            <span class="q-scene">{{ q.scene }}</span>
          </div>
          <span class="review-label">待巩固</span>
        </div>
        <div class="q-stem">{{ q.stem }}</div>

        <div v-if="q.options?.length" class="q-options">
          <div v-for="o in q.options" :key="o.key" class="opt" :class="optClass(q, o.key)">
            <span class="opt-key">{{ o.key }}</span>
            <span class="opt-text">{{ o.text }}</span>
            <span v-if="isCorrectOption(q, o.key)" class="opt-state right">
              <el-icon><CircleCheckFilled /></el-icon>正确答案
            </span>
            <span v-else-if="isMyOption(q, o.key)" class="opt-state wrong">
              <el-icon><CircleCloseFilled /></el-icon>你的选择
            </span>
          </div>
        </div>

        <div v-if="!q.options?.length" class="answer-grid">
          <div class="answer-box wrong">
            <div class="answer-label"><el-icon><CircleCloseFilled /></el-icon>你的答案</div>
            <strong>{{ fmt(q.my_answer) }}</strong>
          </div>
          <div class="answer-box right">
            <div class="answer-label"><el-icon><CircleCheckFilled /></el-icon>正确答案</div>
            <strong>{{ fmt(q.correct_answer) }}</strong>
          </div>
        </div>

        <div v-if="q.analysis" class="analysis">
          <div class="analysis-title"><el-icon><Reading /></el-icon>答案解析</div>
          <div class="analysis-copy">{{ q.analysis }}</div>
        </div>
      </el-card>
      <div v-if="!loading && !filteredRows.length" class="empty-panel">
        <el-empty :description="rows.length ? '没有匹配的错题' : '太棒了，暂无错题！'" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { CircleCheckFilled, CircleCloseFilled, Reading } from '@element-plus/icons-vue'
import { listClasses } from '@/api/classroom'
import { getMyWrongQuestions } from '@/api/analytics'

const route = useRoute()
const courses = ref([])
const courseId = ref(null)
const rows = ref([])
const loading = ref(false)
const fixedCourseId = computed(() => Number(route.params.id) || null)
const keyword = computed(() => String(route.query.search || '').trim().toLowerCase())
const filteredRows = computed(() => {
  if (!keyword.value) return rows.value
  return rows.value.filter((q) => [
    q.stem,
    q.analysis,
    q.scene,
    q.qtype_display,
    ...(q.options || []).map((o) => o.text),
  ].some((text) => String(text || '').toLowerCase().includes(keyword.value)))
})

function fmt(a) {
  if (!a) return '（未作答）'
  if (a.key) return a.key
  if (a.keys) return a.keys.join(', ')
  if (a.blanks) return a.blanks.join(' / ')
  if (a.text) return a.text
  return '—'
}
function isCorrectOption(q, key) {
  return q.correct_answer?.key === key || (q.correct_answer?.keys || []).includes(key)
}
function isMyOption(q, key) {
  return q.my_answer?.key === key || (q.my_answer?.keys || []).includes(key)
}
function optClass(q, key) {
  const correct = isCorrectOption(q, key)
  const mine = isMyOption(q, key)
  if (correct) return 'opt-right'
  if (mine) return 'opt-wrong'
  return ''
}

async function loadCourses() {
  const data = await listClasses()
  const map = new Map()
  ;(data.results ?? data).forEach((row) => {
    const ids = row.courses?.length ? row.courses : [row.course]
    ids.filter(Boolean).forEach((id, index) => {
      map.set(id, { id, name: row.course_names?.[index] || row.course_name || `课程 ${id}` })
    })
  })
  courses.value = [...map.values()]
}
async function load() {
  loading.value = true
  try {
    const activeCourseId = fixedCourseId.value || courseId.value
    const data = await getMyWrongQuestions(activeCourseId ? { course: activeCourseId } : {})
    rows.value = data.results
  } finally {
    loading.value = false
  }
}

watch(fixedCourseId, (id) => {
  courseId.value = id || null
  load()
})

onMounted(() => {
  if (fixedCourseId.value) courseId.value = fixedCourseId.value
  loadCourses()
  load()
})
</script>

<style scoped>
.wrong-page-header {
  align-items: flex-end;
}

.page-title-line {
  display: flex;
  align-items: center;
  gap: 10px;
}

.wrong-count {
  height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  color: #2563eb;
  background: #eff6ff;
  font-size: 12px;
  font-weight: 700;
}

.course-filter {
  width: 240px;
}

.wrong-list {
  display: grid;
  gap: 16px;
}

.wrong-card {
  position: relative;
  overflow: hidden;
  border: 1px solid #e8edf5;
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.045);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.wrong-card::before {
  position: absolute;
  z-index: 1;
  top: 0;
  right: 0;
  left: 0;
  height: 3px;
  background: linear-gradient(90deg, #60a5fa, #2563eb 45%, #a5b4fc);
  content: '';
}

.wrong-card:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.2);
  box-shadow: 0 16px 36px rgba(37, 99, 235, 0.09);
}

.wrong-card :deep(.el-card__body) {
  padding: 24px 26px 26px;
}

.q-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.q-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.q-idx {
  min-width: 38px;
  height: 28px;
  padding: 0 9px;
  border-radius: 8px;
  background: #eaf2ff;
  color: #2563eb;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12.5px;
  font-weight: 800;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}

.q-type,
.q-scene,
.review-label {
  min-height: 26px;
  padding: 0 10px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  font-weight: 650;
}

.q-type {
  color: #2563eb;
  background: #eff6ff;
}

.q-scene {
  color: #64748b;
  background: #f3f6fa;
}

.review-label {
  flex: 0 0 auto;
  color: #b45309;
  background: #fff7ed;
}

.q-stem {
  margin-bottom: 18px;
  color: #0f172a;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.65;
  letter-spacing: 0.005em;
}

.q-options {
  display: grid;
  gap: 10px;
  margin-bottom: 18px;
}

.opt {
  min-height: 46px;
  padding: 8px 12px;
  border: 1px solid #e9eef5;
  border-radius: 12px;
  background: #f8fafc;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13.5px;
  line-height: 1.5;
}

.opt-key {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  color: #64748b;
  background: #fff;
  box-shadow: inset 0 0 0 1px #e2e8f0;
  font-size: 12px;
  font-weight: 750;
}

.opt-text {
  min-width: 0;
  flex: 1;
}

.opt-right {
  border-color: #bbf7d0;
  background: #f2fcf5;
  color: #166534;
}

.opt-right .opt-key {
  color: #15803d;
  background: #dcfce7;
  box-shadow: none;
}

.opt-wrong {
  border-color: #fecaca;
  background: #fff6f6;
  color: #991b1b;
}

.opt-wrong .opt-key {
  color: #dc2626;
  background: #fee2e2;
  box-shadow: none;
}

.opt-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: 700;
}

.opt-state.right {
  color: #16a34a;
}

.opt-state.wrong {
  color: #dc2626;
}

.answer-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.answer-box {
  min-width: 0;
  min-height: 72px;
  padding: 12px 14px;
  border: 1px solid;
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 7px;
}

.answer-box.wrong {
  border-color: #fee2e2;
  background: #fff8f8;
}

.answer-box.right {
  border-color: #dcfce7;
  background: #f7fdf8;
}

.answer-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #64748b;
  font-size: 12px;
  font-weight: 650;
}

.answer-box.wrong .answer-label .el-icon {
  color: #ef4444;
}

.answer-box.right .answer-label .el-icon {
  color: #16a34a;
}

.answer-box strong {
  overflow-wrap: anywhere;
  color: #0f172a;
  font-size: 14px;
  line-height: 1.5;
}

.analysis {
  margin-top: 14px;
  padding: 15px 16px;
  border: 1px solid #e6edf8;
  border-radius: 14px;
  background: #f8fbff;
}

.analysis-title {
  margin-bottom: 7px;
  display: flex;
  align-items: center;
  gap: 7px;
  color: #2563eb;
  font-size: 12.5px;
  font-weight: 750;
}

.analysis-copy {
  color: #526076;
  font-size: 13.5px;
  line-height: 1.75;
}

.empty-panel {
  min-height: 320px;
  border: 1px solid #e8edf5;
  border-radius: 20px;
  display: grid;
  place-items: center;
  background: #fff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
}

@media (max-width: 768px) {
  .wrong-page-header {
    align-items: stretch;
  }

  .course-filter {
    width: 100%;
  }

  .wrong-card :deep(.el-card__body) {
    padding: 20px 16px;
  }

  .q-head {
    align-items: flex-start;
  }

  .q-stem {
    margin-bottom: 16px;
    font-size: 15px;
  }

  .opt {
    align-items: flex-start;
  }

  .opt-key {
    margin-top: 1px;
  }

  .opt-state {
    width: 20px;
    overflow: hidden;
    gap: 8px;
    font-size: 0;
  }

  .opt-state .el-icon {
    flex: 0 0 auto;
    font-size: 16px;
  }

  .answer-grid {
    grid-template-columns: 1fr;
  }

  .answer-box {
    min-height: 66px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .wrong-card {
    transition: none;
  }

  .wrong-card:hover {
    transform: none;
  }
}
</style>
