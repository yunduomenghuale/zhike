<template>
  <div class="page-container analytics-page">
    <div class="page-header">
      <div>
        <div class="page-title">学习统计</div>
        <div class="page-subtitle">查看班级学习进度、成绩与学习预警</div>
      </div>
      <el-select v-model="classId" class="module-select" placeholder="选择班级" style="width: 280px" @change="load">
        <el-option v-for="c in classes" :key="c.id" :label="`${classCourseNames(c)} / ${c.name}`" :value="c.id" />
      </el-select>
    </div>

    <el-empty v-if="!classId" description="请先选择班级" />

    <template v-else>
      <!-- 汇总卡片 -->
      <el-row :gutter="16" class="stat-row">
        <el-col :xs="12" :sm="8" :lg="showWarn ? 4 : 6" v-for="card in summaryCards" :key="card.label">
          <div class="stat-card">
            <div class="stat-icon" :class="card.color">
              <el-icon :size="24"><component :is="card.icon" /></el-icon>
            </div>
            <div>
              <div class="stat-title">{{ card.label }}</div>
              <div class="stat-value">{{ card.value }}</div>
            </div>
          </div>
        </el-col>
      </el-row>

      <!-- 学生明细 -->
      <el-card shadow="never" class="data-card">
        <TableSkeleton v-if="loading" :cols="6" />
        <el-table v-else :data="students" class="module-table" stripe>
          <el-table-column prop="name" label="学生" width="110" fixed />
          <el-table-column label="章节练习" min-width="150">
            <template #default="{ row }">
              <span v-if="row.practice_total">
                {{ row.practice_correct }}/{{ row.practice_total }} 题
                <el-tag size="small" :type="accType(row.accuracy)" effect="light" style="margin-left: 6px">
                  正确率 {{ row.accuracy }}%
                </el-tag>
              </span>
              <span v-else class="muted">未做练习</span>
            </template>
          </el-table-column>
          <el-table-column label="作业" width="110" align="center">
            <template #default="{ row }">
              <span :class="{ warn: row.homework_submitted < row.homework_total }">
                {{ row.homework_submitted }}/{{ row.homework_total }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="考试" width="150" align="center">
            <template #default="{ row }">
              {{ row.exam_taken }}/{{ row.exam_total }}
              <el-tag v-if="row.avg_exam_score !== null" size="small" effect="plain" style="margin-left: 6px">
                均分 {{ row.avg_exam_score }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近学习" width="170">
            <template #default="{ row }">{{ row.last_active ? fmtDate(row.last_active) : '—' }}</template>
          </el-table-column>
          <el-table-column label="预警" min-width="180">
            <template #default="{ row }">
              <el-tag v-for="w in row.warnings" :key="w" type="danger" size="small" effect="light" round style="margin: 2px 4px 2px 0">
                {{ w }}
              </el-tag>
              <el-tag v-if="!row.warnings.length" type="success" size="small" effect="light" round>正常</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!loading && !students.length" description="班级暂无学生" />
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { User, TrendCharts, Medal, Files, Warning } from '@element-plus/icons-vue'
import { listClasses } from '@/api/classroom'
import { getClassStats } from '@/api/analytics'

const classes = ref([])
const classId = ref(null)
const loading = ref(false)
const summary = ref({})
const students = ref([])
const route = useRoute()
const fixedCourseId = computed(() => Number(route.params.id) || null)
const showWarn = computed(() => (summary.value.warning_count ?? 0) > 0)

function classCourseNames(item) {
  return item.course_names?.join('、') || item.course_name || '未关联课程'
}

function activeCourseId() {
  const classroom = classes.value.find((item) => item.id === classId.value)
  return fixedCourseId.value || classroom?.course || null
}

const summaryCards = computed(() => [
  { label: '学生人数', value: summary.value.student_count ?? 0, icon: 'User', color: 'blue' },
  { label: '平均正确率', value: summary.value.avg_accuracy != null ? summary.value.avg_accuracy + '%' : '—', icon: 'TrendCharts', color: 'green' },
  { label: '平均考试分', value: summary.value.avg_exam_score ?? '—', icon: 'Medal', color: 'orange' },
  { label: '作业提交率', value: summary.value.homework_rate != null ? summary.value.homework_rate + '%' : '—', icon: 'Files', color: 'purple' },
  { label: '预警人数', value: summary.value.warning_count ?? 0, icon: 'Warning', color: 'red' },
])

function accType(a) {
  if (a == null) return 'info'
  if (a >= 80) return 'success'
  if (a >= 60) return 'warning'
  return 'danger'
}
function fmtDate(t) {
  return new Date(t).toLocaleString()
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
    summary.value = {}
    students.value = []
  }
}
async function load() {
  if (!classId.value) return
  loading.value = true
  try {
    const data = await getClassStats(classId.value, { course: activeCourseId() })
    summary.value = data.summary
    students.value = data.students
  } finally {
    loading.value = false
  }
}

onMounted(loadClasses)
</script>

<style scoped>
.analytics-page :deep(.data-card) { padding: 0; }
.analytics-page :deep(.page-header) {
  min-height: 58px;
  margin-bottom: 18px;
  padding-bottom: 18px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.82);
}
.module-select :deep(.el-select__wrapper) {
  min-height: 42px;
  border-radius: 12px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbe5f2;
}
.module-select :deep(.el-select__wrapper.is-focused) {
  background: #fff;
  box-shadow: inset 0 0 0 1px #60a5fa, 0 0 0 3px rgba(96, 165, 250, 0.12);
}
.stat-row {
  margin-bottom: 24px;
}
.stat-card {
  min-height: 94px;
  border: 1px solid rgba(37, 99, 235, 0.08);
  border-radius: 16px;
  padding: 18px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.07);
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.stat-icon {
  width: 46px;
  height: 46px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-icon.blue { background: #eff6ff; color: #2563eb; }
.stat-icon.green { background: #ecfdf5; color: #10b981; }
.stat-icon.orange { background: #fff7ed; color: #f59e0b; }
.stat-icon.purple { background: #f5f3ff; color: #8b5cf6; }
.stat-icon.red { background: #fef2f2; color: #ef4444; }
.stat-title { font-size: 13px; color: #64748b; font-weight: 650; }
.stat-value { margin-top: 3px; font-size: 23px; font-weight: 800; color: #0f172a; }
.module-table {
  --el-table-border-color: transparent;
  --el-table-header-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-row-hover-bg-color: transparent;
  background: transparent;
}
.module-table :deep(.el-table__inner-wrapper::before) { display: none; }
.module-table :deep(th.el-table__cell) {
  padding: 0 14px 10px;
  border-bottom: 0;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
  background: transparent;
}
.module-table :deep(td.el-table__cell) {
  padding: 17px 14px;
  border-bottom: 10px solid transparent;
  color: #334155;
  background: rgba(255, 255, 255, 0.8);
}
.module-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: #fff; }
.module-table :deep(.el-table__body tr > td.el-table__cell:first-child) { border-top-left-radius: 15px; border-bottom-left-radius: 15px; }
.module-table :deep(.el-table__body tr > td.el-table__cell:last-child) { border-top-right-radius: 15px; border-bottom-right-radius: 15px; }
.muted { color: var(--el-text-color-placeholder); }
.warn { color: #f56c6c; font-weight: 600; }
</style>
