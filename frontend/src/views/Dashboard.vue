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

// 课程级入口默认进入第一门课程的课程空间（页内可再切换班级）
const courses = ref([])
const studentCourses = ref([])
const firstCourseId = computed(() => courses.value[0]?.id || null)
const firstStudentCourseId = computed(() => studentCourses.value[0]?.id || null)
function courseTab(tab, fallback) {
  return firstCourseId.value ? `/teacher/courses/${firstCourseId.value}/${tab}` : fallback
}
function studentCourseTab(tab, fallback) {
  return firstStudentCourseId.value ? `/student/courses/${firstStudentCourseId.value}/${tab}` : fallback
}

onMounted(async () => {
  try {
    const data = await listCourses()
    courses.value = data.results ?? data
  } catch {
    courses.value = []
  }
  if (userStore.profile?.role === 'student') {
    try {
      const data = await listClasses()
      const rows = data.results ?? data
      const map = new Map()
      rows.forEach((row) => {
        const ids = row.courses?.length ? row.courses : [row.course]
        ids.filter(Boolean).forEach((id, index) => {
          map.set(Number(id), { id: Number(id), name: row.course_names?.[index] || row.course_name || `课程 ${id}` })
        })
      })
      studentCourses.value = [...map.values()]
    } catch {
      studentCourses.value = []
    }
  }
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
  { label: '知识库', desc: '上传资料与问答', path: courseTab('knowledge', '/teacher/knowledge'), icon: Collection, color: '#8b5cf6', bg: '#f5f3ff' },
  { label: '题库', desc: '维护试题资源', path: courseTab('questions', '/teacher/questions'), icon: EditPen, color: '#f59e0b', bg: '#fff7ed' },
  { label: '作业管理', desc: '布置与批改作业', path: courseTab('homework', '/teacher/homework'), icon: Notebook, color: '#0ea5e9', bg: '#f0f9ff' },
  { label: '考试', desc: '组卷与发布考试', path: courseTab('exams', '/teacher/exams'), icon: Document, color: '#ef4444', bg: '#fef2f2' },
  { label: '学习统计', desc: '查看学习数据', path: courseTab('analytics', '/teacher/analytics'), icon: TrendCharts, color: '#14b8a6', bg: '#ecfeff' },
  { label: '个人中心', desc: '维护账号资料', path: '/profile', icon: HomeFilled, color: '#64748b', bg: '#f1f5f9' },
])

const studentFeatures = computed(() => [
  { label: '我的课程', desc: '进入课程学习', path: '/student/my-classes', icon: Reading, color: '#2563eb', bg: '#eff6ff' },
  { label: '课程学习', desc: '章节与完整讲解', path: studentCourseTab('learning', '/student/learning'), icon: VideoPlay, color: '#10b981', bg: '#ecfdf5' },
  { label: '知识库提问', desc: '向知识库提问', path: studentCourseTab('qa', '/student/qa'), icon: ChatDotRound, color: '#8b5cf6', bg: '#f5f3ff' },
  { label: '我的作业', desc: '提交课程作业', path: studentCourseTab('homework', '/student/homework'), icon: Notebook, color: '#0ea5e9', bg: '#f0f9ff' },
  { label: '我的考试', desc: '参加考试答题', path: studentCourseTab('exams', '/student/exams'), icon: Document, color: '#ef4444', bg: '#fef2f2' },
  { label: '错题本', desc: '复盘错题记录', path: studentCourseTab('wrong', '/student/wrong'), icon: Collection, color: '#f59e0b', bg: '#fff7ed' },
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
</style>
