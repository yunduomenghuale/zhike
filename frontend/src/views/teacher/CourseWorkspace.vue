<template>
  <main class="course-page">
    <header class="course-topbar">
      <button type="button" class="brand-link" @click="router.push('/dashboard')">
        <span class="brand-orbit"></span>
        <span>智课平台</span>
      </button>
      <button type="button" class="top-action" @click="router.push('/teacher/courses')">
        返回个人空间
      </button>
    </header>

    <div class="course-stage">
      <aside class="course-rail">
        <div class="course-cover" @click="goTab('course-chapters')">
          <div class="cover-visual">
            <el-icon><Reading /></el-icon>
          </div>
          <div class="cover-name">{{ course?.name || '课程空间' }}</div>
          <div class="cover-term">{{ course?.term || '未设置学期' }}</div>
        </div>

        <nav class="course-menu" aria-label="课程功能">
          <button
            v-for="item in tabs"
            :key="item.name"
            type="button"
            class="course-menu-item"
            :class="{ active: route.name === item.name }"
            @click="goTab(item.name)"
          >
            <span class="menu-icon">
              <el-icon><component :is="item.icon" /></el-icon>
            </span>
            <span class="menu-text">{{ item.label }}</span>
          </button>
        </nav>
      </aside>

      <section class="course-main-panel">
        <div class="course-content">
          <router-view />
        </div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Collection,
  Document,
  EditPen,
  Notebook,
  Reading,
  TrendCharts,
} from '@element-plus/icons-vue'
import { listCourses } from '@/api/course'

const route = useRoute()
const router = useRouter()
const course = ref(null)

const tabs = [
  { name: 'course-chapters', label: '章节与课件', icon: Reading },
  { name: 'course-knowledge', label: '知识库', icon: Collection },
  { name: 'course-questions', label: '题库', icon: EditPen },
  { name: 'course-homework', label: '作业', icon: Notebook },
  { name: 'course-exams', label: '考试', icon: Document },
  { name: 'course-analytics', label: '学习统计', icon: TrendCharts },
]

const courseId = computed(() => Number(route.params.id) || null)
const activeTab = computed(() => tabs.find((item) => item.name === route.name))

async function loadCourse() {
  if (!courseId.value) return
  const data = await listCourses()
  const list = data.results ?? data
  course.value = list.find((item) => Number(item.id) === courseId.value) || null
  updatePageTitle()
}

function updatePageTitle() {
  const courseName = course.value?.name || '课程空间'
  const tabName = activeTab.value?.label
  document.title = tabName ? `${courseName} - ${tabName}` : courseName
}

function goTab(name) {
  router.push({ name, params: { id: courseId.value } })
}

onMounted(loadCourse)
watch(courseId, loadCourse)
watch(activeTab, updatePageTitle)
</script>

<style scoped>
.course-page {
  min-height: 100vh;
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(circle at 24% 26%, rgba(96, 165, 250, 0.22), transparent 26rem),
    radial-gradient(circle at 76% 54%, rgba(37, 99, 235, 0.14), transparent 32rem),
    linear-gradient(135deg, #f8fbff 0%, #eef4fb 48%, #f6f9fd 100%);
  color: #0f172a;
}

.course-page::before {
  content: "";
  position: absolute;
  inset: 72px auto 0 0;
  width: min(56vw, 820px);
  background:
    linear-gradient(118deg, rgba(255, 255, 255, 0.92) 0%, rgba(219, 234, 254, 0.58) 30%, transparent 58%);
  filter: blur(16px);
  opacity: 0.92;
  pointer-events: none;
}

.course-page::after {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(to bottom, rgba(241, 245, 251, 0.9), transparent 18%, transparent 82%, rgba(241, 245, 251, 0.94)),
    linear-gradient(to right, rgba(241, 245, 251, 0.88), transparent 20%, transparent 82%, rgba(241, 245, 251, 0.92));
  pointer-events: none;
}

.course-topbar {
  height: 64px;
  position: relative;
  z-index: 2;
  padding: 0 30px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(255, 255, 255, 0.88);
  color: #0f172a;
  box-shadow: 0 16px 38px rgba(37, 99, 235, 0.08);
  backdrop-filter: blur(20px) saturate(1.12);
}

.brand-link,
.top-action {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.brand-link {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 800;
}

.brand-orbit {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: inline-block;
  background:
    radial-gradient(circle at 50% 50%, #fff 0 26%, transparent 27%),
    conic-gradient(from 0deg, #2563eb, #60a5fa, #2563eb);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.14);
}

.top-action {
  height: 36px;
  padding: 0 16px;
  border-radius: 999px;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(239, 246, 255, 0.84));
  color: #2563eb;
  font-size: 14px;
  font-weight: 650;
  box-shadow:
    0 14px 28px rgba(37, 99, 235, 0.1),
    0 5px 12px rgba(15, 23, 42, 0.06),
    inset 0 1px 1px rgba(255, 255, 255, 0.98),
    inset 0 -1px 2px rgba(37, 99, 235, 0.08),
    0 0 0 1px rgba(37, 99, 235, 0.14) inset;
  transition: background-color 0.18s ease, color 0.18s ease;
}

.top-action:hover {
  background: rgba(219, 234, 254, 0.92);
  color: #1d4ed8;
}

.course-stage {
  position: relative;
  z-index: 1;
  min-height: calc(100vh - 64px);
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 24px;
  padding: 34px 38px 40px;
}

.course-rail {
  align-self: start;
  min-height: calc(100vh - 138px);
  border: 1px solid rgba(37, 99, 235, 0.1);
  border-radius: 30px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow:
    0 28px 70px rgba(37, 99, 235, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(24px) saturate(1.18);
  overflow: hidden;
}

.course-cover {
  padding: 30px 22px 28px;
  display: grid;
  justify-items: center;
  gap: 11px;
  cursor: pointer;
}

.cover-visual {
  width: 84px;
  height: 84px;
  border-radius: 24px;
  display: grid;
  place-items: center;
  background: rgba(239, 246, 255, 0.9);
  color: #2563eb;
  font-size: 36px;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.72),
    0 16px 36px rgba(37, 99, 235, 0.12);
}

.cover-name {
  max-width: 100%;
  text-align: center;
  color: #0f172a;
  font-size: 18px;
  font-weight: 850;
  line-height: 1.35;
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.cover-term {
  max-width: 100%;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-menu {
  padding: 0 18px 24px;
  display: grid;
  gap: 8px;
}

.course-menu-item {
  width: 100%;
  height: 46px;
  border: 0;
  border-radius: 14px;
  padding: 0 15px;
  background: transparent;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 15px;
  font-weight: 760;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease,
    color 0.18s ease,
    background-color 0.18s ease;
}

.course-menu-item:hover {
  color: #2563eb;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.95), rgba(219, 234, 254, 0.66));
  box-shadow:
    0 10px 22px rgba(37, 99, 235, 0.09),
    inset 0 1px 1px rgba(255, 255, 255, 0.9),
    inset 0 -1px 2px rgba(37, 99, 235, 0.06);
  transform: translateX(2px);
}

.course-menu-item.active {
  color: #fff;
  background: #3b82f6;
  box-shadow:
    0 10px 22px rgba(37, 99, 235, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.course-menu-item.active:hover {
  color: #fff;
  background: #2563eb;
  box-shadow:
    0 12px 26px rgba(37, 99, 235, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.24);
}

.menu-icon {
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  font-size: 17px;
  color: inherit;
  position: relative;
  z-index: 1;
}

.menu-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  position: relative;
  z-index: 1;
}

.course-main-panel {
  min-width: 0;
  min-height: calc(100vh - 138px);
  border: 1px solid rgba(37, 99, 235, 0.1);
  border-radius: 30px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow:
    0 30px 80px rgba(37, 99, 235, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.74);
  backdrop-filter: blur(22px) saturate(1.12);
  overflow: hidden;
}

.course-content {
  background: transparent;
}

.course-content :deep(.page-container) {
  padding: 26px 30px 32px;
}

.course-content :deep(.page-header) {
  display: none;
}

.course-content :deep(.data-card),
.course-content :deep(.el-card) {
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

@media (max-width: 1024px) {
  .course-stage {
    grid-template-columns: 1fr;
    padding: 22px;
  }

  .course-rail {
    min-height: auto;
  }

  .course-cover {
    display: none;
  }

  .course-menu {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    padding-top: 16px;
  }

  .course-menu-item {
    justify-content: center;
  }
}
</style>
