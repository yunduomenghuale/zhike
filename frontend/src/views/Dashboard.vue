<template>
  <div class="page-container dashboard">
    <div class="dash-hero">
      <div>
        <div class="dash-hello">{{ greeting }}，{{ profile?.real_name || profile?.username || '同学' }}</div>
        <div class="dash-sub">{{ today }} · 欢迎回到智课平台</div>
      </div>
      <span class="dash-role">{{ roleName }}</span>
    </div>

    <div class="feature-grid animate-list">
      <button
        v-for="f in features"
        :key="f.label"
        type="button"
        class="feature-card"
        @click="handleSelect(f)"
      >
        <span class="feature-icon" :style="{ color: f.color, background: f.bg }">
          <el-icon :size="24"><component :is="f.icon" /></el-icon>
        </span>
        <span class="feature-main">
          <span class="feature-label">{{ f.label }}</span>
          <span class="feature-desc">{{ f.desc }}</span>
        </span>
        <el-icon class="feature-arrow"><ArrowRight /></el-icon>
      </button>
    </div>

    <!-- 学生多课程选择：同一学生加入多个班级时，课程级入口弹课程选择，点击即进入 -->
    <el-dialog
      v-model="coursePickerVisible"
      :title="`选择课程 · ${pickerLabel || '课程空间'}`"
      width="480px"
      align-center
      append-to-body
      class="course-picker-dialog"
    >
      <div v-loading="coursesLoading" class="course-picker-list">
        <button
          v-for="c in pickerCourses"
          :key="c.id"
          type="button"
          class="course-picker-item"
          @click="pickCourse(c)"
        >
          <span class="picker-course-icon">
            <el-icon :size="20"><Reading /></el-icon>
          </span>
          <span class="picker-course-main">
            <span class="picker-course-name">{{ c.name }}</span>
            <span class="picker-course-meta">{{ c.className || pickerMetaFallback }}</span>
          </span>
          <el-icon class="picker-course-go"><ArrowRight /></el-icon>
        </button>
        <el-empty v-if="!coursesLoading && !pickerCourses.length" :description="pickerRole === 'teacher' ? '还没有创建课程' : '还没有加入任何班级'" :image-size="60" />
      </div>
      <template #footer>
        <div class="course-picker-footer">
          <el-button @click="coursePickerVisible = false">取消</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/store/user'
import { listCourses } from '@/api/course'
import { listClasses } from '@/api/classroom'
import {
  ArrowRight,
  ChatDotRound,
  Collection,
  DataAnalysis,
  Document,
  EditPen,
  HomeFilled,
  Notebook,
  Reading,
  School,
  Setting,
  TrendCharts,
  UserFilled,
  VideoPlay,
} from '@element-plus/icons-vue'

const router = useRouter()
const userStore = useUserStore()
const profile = computed(() => userStore.profile)

// 课程级入口（教师/学生通用）：多课程弹选择、单课程直达、无课程走独立页
const courses = ref([])
const studentCourses = ref([])
let studentCoursesPromise = null
let teacherCoursesPromise = null
const coursesLoading = ref(false)

// 学生课程级入口：等待课程列表加载完成（避免加载完成前点击误判为"无课程"）
function ensureStudentCourses() {
  if (userStore.profile?.role !== 'student') return Promise.resolve([])
  if (!studentCoursesPromise) {
    coursesLoading.value = true
    studentCoursesPromise = listClasses()
      .then((data) => {
        const rows = data.results ?? data
        const map = new Map()
        rows.forEach((row) => {
          const ids = row.courses?.length ? row.courses : [row.course]
          ids.filter(Boolean).forEach((id, index) => {
            const cid = Number(id)
            if (!map.has(cid)) {
              map.set(cid, { id: cid, name: row.course_names?.[index] || row.course_name || `课程 ${cid}`, className: row.name })
            }
          })
        })
        studentCourses.value = [...map.values()]
        return studentCourses.value
      })
      .catch(() => {
        studentCourses.value = []
        return studentCourses.value
      })
      .finally(() => {
        coursesLoading.value = false
      })
  }
  return studentCoursesPromise
}

// 教师课程级入口：等待课程列表加载完成（避免加载完成前点击误判为"无课程"）
function ensureTeacherCourses() {
  if (userStore.profile?.role !== 'teacher') return Promise.resolve([])
  if (!teacherCoursesPromise) {
    coursesLoading.value = true
    teacherCoursesPromise = listCourses()
      .then((data) => {
        const rows = data.results ?? data
        courses.value = rows
        return courses.value
      })
      .catch(() => {
        courses.value = []
        return courses.value
      })
      .finally(() => {
        coursesLoading.value = false
      })
  }
  return teacherCoursesPromise
}

// 多课程选择弹窗状态
const coursePickerVisible = ref(false)
const pickerLabel = ref('')
const pickerTab = ref('')
const pickerRole = ref('student')
const pickerMetaFallback = computed(() => (pickerRole.value === 'teacher' ? '我教授的课程' : '已加入课程'))
// 弹窗课程列表按角色取数：教师用所授课程，学生用已加入班级的课程
const pickerCourses = computed(() => (pickerRole.value === 'teacher' ? courses.value : studentCourses.value))

// 最近学习记忆按角色隔离，避免师生账号互串
function lastCourseKey(role) {
  return `zhike.lastCourseId.${role === 'teacher' ? 'teacher' : 'student'}`
}

function readLastCourseId(role) {
  try {
    const v = Number(localStorage.getItem(lastCourseKey(role)))
    return Number.isFinite(v) && v > 0 ? v : null
  } catch {
    return null
  }
}

function rememberLastCourseId(role, id) {
  try {
    localStorage.setItem(lastCourseKey(role), String(id))
  } catch {
    // 隐私模式等场景下忽略持久化失败
  }
}

// 课程级入口（学生/教师通用）：多课程先弹选择（点击即进入，最近学习的排在前），单课程直达，无课程走独立页空态
async function openCourseFeature(tab, fallback, label) {
  const role = userStore.profile?.role
  pickerRole.value = role === 'teacher' ? 'teacher' : 'student'
  const list = pickerRole.value === 'teacher' ? await ensureTeacherCourses() : await ensureStudentCourses()
  if (list.length > 1) {
    pickerTab.value = tab
    pickerLabel.value = label
    const last = readLastCourseId(pickerRole.value)
    if (last) list.sort((a, b) => (b.id === last) - (a.id === last))
    coursePickerVisible.value = true
    return
  }
  if (list.length === 1) {
    rememberLastCourseId(pickerRole.value, list[0].id)
    router.push(`/${pickerRole.value}/courses/${list[0].id}/${tab}`)
    return
  }
  router.push(fallback)
}

// 点击课程项即进入对应课程空间（一步完成，无需再点"进入"）
function pickCourse(c) {
  rememberLastCourseId(pickerRole.value, c.id)
  coursePickerVisible.value = false
  router.push(`/${pickerRole.value}/courses/${c.id}/${pickerTab.value}`)
}

onMounted(() => {
  // 预热课程列表缓存，使工作台点击课程级入口时弹窗即时可用
  if (userStore.profile?.role === 'teacher') ensureTeacherCourses()
  if (userStore.profile?.role === 'student') ensureStudentCourses()
})

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '上午好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const today = new Date().toLocaleDateString('zh-CN', {
  month: 'long',
  day: 'numeric',
  weekday: 'long',
})

const roleName = computed(() => profile.value?.role_display || '')

const teacherFeatures = computed(() => [
  { label: '课程管理', desc: '维护课程与目录', path: '/teacher/courses', icon: Reading, color: '#2563eb', bg: '#eff6ff' },
  { label: '班级管理', desc: '管理班级与学生', path: '/teacher/classes', icon: School, color: '#10b981', bg: '#ecfdf5' },
  { label: '知识库', desc: '上传资料与问答', tab: 'knowledge', path: '/teacher/knowledge', icon: Collection, color: '#8b5cf6', bg: '#f5f3ff' },
  { label: '题库', desc: '维护试题资源', tab: 'questions', path: '/teacher/questions', icon: EditPen, color: '#f59e0b', bg: '#fff7ed' },
  { label: '作业管理', desc: '布置与批改作业', tab: 'homework', path: '/teacher/homework', icon: Notebook, color: '#0ea5e9', bg: '#f0f9ff' },
  { label: '考试', desc: '组卷与发布考试', tab: 'exams', path: '/teacher/exams', icon: Document, color: '#ef4444', bg: '#fef2f2' },
  { label: '学习统计', desc: '查看学习数据', tab: 'analytics', path: '/teacher/analytics', icon: TrendCharts, color: '#14b8a6', bg: '#ecfeff' },
  { label: '个人中心', desc: '维护账号资料', path: '/profile', icon: HomeFilled, color: '#64748b', bg: '#f1f5f9' },
])

const studentFeatures = computed(() => [
  { label: '我的课程', desc: '进入课程学习', path: '/student/my-classes', icon: Reading, color: '#2563eb', bg: '#eff6ff' },
  { label: '课程学习', desc: '章节与完整讲解', tab: 'learning', path: '/student/learning', icon: VideoPlay, color: '#10b981', bg: '#ecfdf5' },
  { label: '知识库提问', desc: '向知识库提问', tab: 'qa', path: '/student/qa', icon: ChatDotRound, color: '#8b5cf6', bg: '#f5f3ff' },
  { label: '我的作业', desc: '提交课程作业', tab: 'homework', path: '/student/homework', icon: Notebook, color: '#0ea5e9', bg: '#f0f9ff' },
  { label: '我的考试', desc: '参加考试答题', tab: 'exams', path: '/student/exams', icon: Document, color: '#ef4444', bg: '#fef2f2' },
  { label: '错题本', desc: '复盘错题记录', tab: 'wrong', path: '/student/wrong', icon: Collection, color: '#f59e0b', bg: '#fff7ed' },
  { label: '我的班级', desc: '查看所在班级', path: '/student/my-classes', icon: School, color: '#14b8a6', bg: '#ecfeff' },
  { label: '个人中心', desc: '维护账号资料', path: '/profile', icon: HomeFilled, color: '#64748b', bg: '#f1f5f9' },
])

const adminFeatures = [
  { label: '管理概览', desc: '查看平台运行数据', path: '/admin/overview', icon: DataAnalysis, color: '#2563eb', bg: '#eff6ff' },
  { label: '用户管理', desc: '维护教师与学生账号', path: '/admin/users', icon: UserFilled, color: '#8b5cf6', bg: '#f5f3ff' },
  { label: '教学监管', desc: '监管课程与班级状态', path: '/admin/teaching', icon: Reading, color: '#10b981', bg: '#ecfdf5' },
  { label: '大模型配置', desc: '配置模型并测试连接', path: '/admin/ai-settings', icon: Setting, color: '#0ea5e9', bg: '#f0f9ff' },
  { label: '个人中心', desc: '维护管理员账号资料', path: '/profile', icon: HomeFilled, color: '#f59e0b', bg: '#fff7ed' },
]

const features = computed(() => {
  if (userStore.profile?.role === 'admin') return adminFeatures
  if (userStore.profile?.role === 'student') return studentFeatures.value
  return teacherFeatures.value
})

function handleSelect(item) {
  if (item.tab) {
    openCourseFeature(item.tab, item.path, item.label)
    return
  }
  if (item.path) router.push(item.path)
}
</script>

<style scoped>
.dashboard {
  min-height: 100%;
}

.dash-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
  padding: 22px 26px;
  border: 1px solid rgba(37, 99, 235, 0.09);
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.95), rgba(255, 255, 255, 0.96) 60%);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.07);
}

.dash-hello {
  color: var(--gray-900);
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0.01em;
}

.dash-sub {
  margin-top: 6px;
  color: var(--gray-500);
  font-size: 13.5px;
}

.dash-role {
  flex-shrink: 0;
  padding: 5px 14px;
  border-radius: 999px;
  background: var(--primary-50);
  color: var(--primary-600);
  font-size: 13px;
  font-weight: 700;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.25);
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 14px;
}

.feature-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px;
  border: 1px solid rgba(37, 99, 235, 0.09);
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(248, 251, 255, 0.9));
  box-shadow: 0 8px 22px rgba(37, 99, 235, 0.06);
  cursor: pointer;
  text-align: left;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.feature-card:hover {
  transform: translateY(-2px);
  border-color: rgba(96, 165, 250, 0.45);
  box-shadow: 0 14px 32px rgba(37, 99, 235, 0.12);
}

.feature-icon {
  width: 50px;
  height: 50px;
  display: grid;
  flex: 0 0 50px;
  place-items: center;
  border-radius: 14px;
  transition: transform 0.25s ease;
}

.feature-card:hover .feature-icon {
  transform: scale(1.08) rotate(-3deg);
}

.feature-main {
  display: grid;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.feature-label {
  color: var(--gray-900);
  font-size: 15.5px;
  font-weight: 750;
}

.feature-desc {
  overflow: hidden;
  color: var(--gray-400);
  font-size: 12.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feature-arrow {
  flex-shrink: 0;
  color: var(--gray-300);
  font-size: 15px;
  transition: color 0.18s ease, transform 0.18s ease;
}

.feature-card:hover .feature-arrow {
  color: var(--primary-600);
  transform: translateX(3px);
}

@media (max-width: 640px) {
  .dash-hero {
    padding: 18px 20px;
  }

  .dash-hello {
    font-size: 19px;
  }
}

/* 学生多课程选择弹窗 */
.course-picker-list {
  display: grid;
  gap: 10px;
  min-height: 60px;
}

.course-picker-item {
  display: flex;
  align-items: center;
  gap: 13px;
  width: 100%;
  padding: 14px 16px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(248, 251, 255, 0.9));
  cursor: pointer;
  text-align: left;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.course-picker-item:hover {
  transform: translateY(-1px);
  border-color: rgba(96, 165, 250, 0.45);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.1);
}

.picker-course-icon {
  width: 40px;
  height: 40px;
  display: grid;
  flex: 0 0 40px;
  place-items: center;
  border-radius: 12px;
  background: var(--primary-50, #eff6ff);
  color: var(--primary-600, #2563eb);
}

.picker-course-main {
  display: grid;
  gap: 3px;
  min-width: 0;
  flex: 1;
}

.picker-course-name {
  overflow: hidden;
  color: var(--gray-900);
  font-size: 15px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picker-course-meta {
  color: var(--gray-400);
  font-size: 12.5px;
}

.picker-course-go {
  flex-shrink: 0;
  color: var(--gray-300, #cbd5e1);
  font-size: 16px;
}

.course-picker-item:hover .picker-course-go {
  color: var(--primary-500, #3b82f6);
}

.course-picker-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
