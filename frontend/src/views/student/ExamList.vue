<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">我的考试</div>
        <div class="page-subtitle">查看可参加的考试，进入答题页后请遵守考试规则</div>
      </div>
    </div>

    <div class="exam-shell">
      <TableSkeleton v-if="loading" :cols="5" />
      <div v-else-if="filteredExams.length" class="exam-list course-standard-list">
        <article v-for="row in filteredExams" :key="row.id" class="exam-row course-standard-row">
          <div class="exam-row-left">
            <span class="exam-kind">考试</span>
            <div class="exam-copy">
              <div class="exam-title">{{ row.name }}</div>
              <div class="exam-meta">
                <span>{{ row.class_name || '未设置班级' }}</span>
                <span v-if="formatWindow(row)"><el-icon><Clock /></el-icon>{{ formatWindow(row) }}</span>
                <span>{{ row.duration }} 分钟</span>
                <strong>{{ row.total_score || 0 }} 分</strong>
              </div>
            </div>
          </div>
          <div class="exam-actions course-standard-actions">
            <button class="exam-action course-standard-action-btn primary" type="button" @click="enter(row)">
              <el-icon><EditPen /></el-icon>进入考试
            </button>
          </div>
        </article>
      </div>
      <el-empty v-else description="暂无可参加的考试">
        <template #description>
          <div class="empty-text">{{ exams.length ? '没有匹配的考试' : '暂无可参加的考试' }}</div>
          <div class="empty-tip">{{ exams.length ? '换个关键词试试' : '考试发布后会自动出现在这里' }}</div>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useRoute } from 'vue-router'
import { Clock, EditPen } from '@element-plus/icons-vue'
import { listExams } from '@/api/exam'

const router = useRouter()
const route = useRoute()
const exams = ref([])
const loading = ref(false)
const fixedCourseId = computed(() => Number(route.params.id) || null)
const keyword = computed(() => String(route.query.search || '').trim().toLowerCase())
const filteredExams = computed(() => {
  if (!keyword.value) return exams.value
  return exams.value.filter((row) => [
    row.name,
    row.class_name,
    row.status_display,
  ].some((text) => String(text || '').toLowerCase().includes(keyword.value)))
})

async function load() {
  loading.value = true
  try {
    const data = await listExams(fixedCourseId.value ? { course: fixedCourseId.value } : undefined)
    exams.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

function enter(row) {
  router.push(`/student/exams/${row.id}/take`)
}

function formatDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (num) => String(num).padStart(2, '0')
  return `${date.getMonth() + 1}/${date.getDate()} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatWindow(row) {
  const start = formatDateTime(row.start_at)
  const end = formatDateTime(row.end_at)
  if (start && end) return `${start} - ${end}`
  return start || end
}

watch(fixedCourseId, () => load())

onMounted(load)
</script>

<style scoped>
.exam-list {
  display: flex;
  flex-direction: column;
}
.exam-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.exam-row-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}
.exam-kind {
  flex: 0 0 auto;
  min-width: 56px;
  height: 30px;
  padding: 0 12px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #2563eb;
  background: #eff6ff;
  font-size: 12.5px;
  font-weight: 700;
}
.exam-copy {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px 12px;
}
.exam-title {
  max-width: 420px;
  overflow: hidden;
  color: #0f172a;
  font-size: 15px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.exam-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  color: #64748b;
  font-size: 12.5px;
}
.exam-meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.exam-action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  color: #2563eb;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
.exam-action:hover {
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

.empty-text {
  font-size: 14px;
  color: #64748b;
  margin-bottom: 4px;
}

.empty-tip {
  font-size: 12px;
  color: #94a3b8;
}
@media (max-width: 768px) {
  .exam-row {
    flex-direction: column;
    align-items: stretch;
  }
  .exam-actions {
    display: flex;
    justify-content: flex-end;
  }
}
</style>
