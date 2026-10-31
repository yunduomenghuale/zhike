<template>
  <div class="page-container">
    <div v-loading="loading">
      <el-row :gutter="16" class="class-grid animate-list">
        <el-col :xs="24" :sm="12" v-for="c in filteredClasses" :key="`${c.classId}-${c.id}`">
          <article class="class-card" @click="openCourse(c, 'student-course-learning')">
            <span class="class-icon">
              <el-icon :size="26"><Reading /></el-icon>
            </span>
            <div class="class-main">
              <div class="class-name" :title="c.courseName">{{ c.courseName }}</div>
              <div v-if="c.intro" class="class-intro" :title="c.intro">{{ c.intro }}</div>
              <div class="class-meta">
                <span class="class-chip" :title="c.className">{{ c.className }}</span>
                <el-tag :type="classStatusMeta(c.status).type" effect="light" round class="class-status">
                  {{ classStatusMeta(c.status).label }}
                </el-tag>
              </div>
              <div v-if="courseProgress[c.id] != null" class="class-progress-row">
                <el-progress
                  :percentage="courseProgress[c.id]"
                  :stroke-width="6"
                  :show-text="false"
                  color="#2563eb"
                  class="class-progress-bar"
                />
                <span class="class-progress-text">学习进度 {{ courseProgress[c.id] }}%</span>
              </div>
            </div>
            <el-icon class="class-arrow"><ArrowRight /></el-icon>
          </article>
        </el-col>
      </el-row>
      <el-empty v-if="!loading && !filteredClasses.length" :description="courseCards.length ? '没有匹配的课程' : '还没有分配课程，请联系学校管理员'" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Reading, ArrowRight } from '@element-plus/icons-vue'
import { listClasses } from '@/api/classroom'
import { classStatusMeta } from '@/utils/classStatus'
import { listCatalogs, listCourses, listWatchProgress } from '@/api/course'
import { chapterProgress } from '@/utils/learningProgress'

const route = useRoute()
const router = useRouter()
const classes = ref([])
const loading = ref(false)
const courseProgress = ref({}) // courseId -> 总进度百分比
const courseIntro = ref({})    // courseId -> 课程简介（教师填写，学生端展示）

// 课程总进度：各章进度平均（无记录的章计 0%）
async function loadCourseProgress(courseIds) {
  const result = {}
  await Promise.all(courseIds.map(async (cid) => {
    try {
      const [cats, progress] = await Promise.all([
        listCatalogs({ course: cid, tree: 1 }),
        listWatchProgress({ course: cid }),
      ])
      const chapters = (cats.results ?? cats).length
      const rows = progress.results ?? progress
      if (!chapters) {
        result[cid] = null
        return
      }
      let sum = 0
      rows.forEach((p) => {
        sum += chapterProgress(p).pct ?? 0
      })
      result[cid] = Math.round(sum / chapters)
    } catch {
      result[cid] = null
    }
  }))
  courseProgress.value = result
}
const keyword = computed(() => String(route.query.search || '').trim().toLowerCase())
const courseCards = computed(() => {
  const cards = []
  classes.value.forEach((item) => {
    const ids = item.courses?.length ? item.courses : [item.course]
    ids.filter(Boolean).forEach((id, index) => {
      cards.push({
        id: Number(id),
        classId: item.id,
        className: item.name,
        courseName: item.course_names?.[index] || item.course_name || `课程 ${id}`,
        intro: courseIntro.value[id] || '',
        status: item.status,
      })
    })
  })
  return cards
})
const filteredClasses = computed(() => {
  if (!keyword.value) return courseCards.value
  return courseCards.value.filter((c) => [
    c.className,
    c.courseName,
  ].some((text) => String(text || '').toLowerCase().includes(keyword.value)))
})

async function load() {
  loading.value = true
  try {
    // 班级接口只有课程名，课程简介要单独从课程接口取（学生可见课程，含 intro）
    const [data, courseData] = await Promise.all([
      listClasses(),
      listCourses({ page_size: 100 }).catch(() => ({})),
    ])
    classes.value = data.results ?? data
    const courseRows = courseData?.results ?? courseData
    const introMap = {}
    ;(Array.isArray(courseRows) ? courseRows : []).forEach((row) => {
      if (row?.intro) introMap[Number(row.id)] = row.intro
    })
    courseIntro.value = introMap
    const ids = [...new Set(courseCards.value.map((c) => c.id))]
    if (ids.length) loadCourseProgress(ids)
  } finally {
    loading.value = false
  }
}

function openCourse(course, name) {
  router.push({ name, params: { id: course.id } })
}

onMounted(load)
</script>

<style scoped>
/* 课程卡片：一行两张，内部三行结构（课程名 / 班级+状态 / 进度），
   名称完整可见（原一行三张列宽不足，课程名截断、班级名逐字竖排） */
.class-grid {
  row-gap: 16px;
}
.class-card {
  display: flex;
  align-items: center;
  gap: 15px;
  min-height: 122px;
  padding: 18px 20px;
  border: 1px solid rgba(37, 99, 235, 0.09);
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(248, 251, 255, 0.9));
  box-shadow: 0 8px 22px rgba(37, 99, 235, 0.06);
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.class-card:hover {
  transform: translateY(-2px);
  border-color: rgba(96, 165, 250, 0.45);
  box-shadow: 0 14px 32px rgba(37, 99, 235, 0.12);
}
.class-icon {
  width: 52px;
  height: 52px;
  display: grid;
  flex: 0 0 52px;
  place-items: center;
  border-radius: 14px;
  color: var(--primary-600);
  background: linear-gradient(145deg, #eff6ff, #ffffff);
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.16);
  transition: transform 0.25s ease;
}
.class-card:hover .class-icon {
  transform: scale(1.08) rotate(-3deg);
}
.class-main {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.class-name {
  overflow: hidden;
  color: var(--gray-900);
  font-size: 17px;
  font-weight: 750;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 课程简介：教师填写的介绍，两行截断，全文在 title 里悬停可见 */
.class-intro {
  margin-top: 4px;
  color: var(--gray-500, #8a94a2);
  font-size: 12px;
  line-height: 1.5;
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.class-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.class-chip {
  max-width: 70%;
  overflow: hidden;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--gray-100);
  color: var(--gray-500);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.class-status {
  flex-shrink: 0;
}
.class-progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.class-progress-bar {
  width: 160px;
  max-width: 45%;
  flex-shrink: 0;
}
.class-progress-bar :deep(.el-progress-bar__outer) {
  background: var(--gray-100);
}
.class-progress-text {
  color: var(--gray-500);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.class-arrow {
  flex-shrink: 0;
  color: var(--gray-300);
  font-size: 16px;
  transition: color 0.18s ease, transform 0.18s ease;
}
.class-card:hover .class-arrow {
  color: var(--primary-600);
  transform: translateX(3px);
}

</style>
