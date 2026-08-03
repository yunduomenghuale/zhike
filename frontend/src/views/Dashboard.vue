<template>
  <div class="page-container dashboard">
    <section class="workspace-helix" aria-label="工作台功能入口">
      <HelixFeatureCarousel
        :items="features"
        background="var(--workspace-bg)"
        aria-label="工作台功能入口"
        @select="handleSelect"
      />
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/store/user'
import HelixFeatureCarousel from '@/components/HelixFeatureCarousel.vue'
import {
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

const teacherFeatures = [
  { label: '工作台', desc: '总览教学事项', path: '/dashboard', icon: HomeFilled, color: '#2563eb', bg: '#eff6ff' },
  { label: '课程管理', desc: '维护课程与目录', path: '/teacher/courses', icon: Reading, color: '#2563eb', bg: '#eff6ff' },
  { label: '班级管理', desc: '管理班级与学生', path: '/teacher/classes', icon: School, color: '#10b981', bg: '#ecfdf5' },
  { label: '知识库', desc: '上传资料与问答', path: '/teacher/knowledge', icon: Collection, color: '#8b5cf6', bg: '#f5f3ff' },
  { label: '题库', desc: '维护试题资源', path: '/teacher/questions', icon: EditPen, color: '#f59e0b', bg: '#fff7ed' },
  { label: '作业管理', desc: '布置与批改作业', path: '/teacher/homework', icon: Notebook, color: '#0ea5e9', bg: '#f0f9ff' },
  { label: '考试', desc: '组卷与发布考试', path: '/teacher/exams', icon: Document, color: '#ef4444', bg: '#fef2f2' },
  { label: '学习统计', desc: '查看学习数据', path: '/teacher/analytics', icon: TrendCharts, color: '#14b8a6', bg: '#ecfeff' },
]

const studentFeatures = [
  { label: '工作台', desc: '查看学习入口', path: '/dashboard', icon: HomeFilled, color: '#2563eb', bg: '#eff6ff' },
  { label: '我的班级', desc: '查看所在班级', path: '/student/my-classes', icon: School, color: '#10b981', bg: '#ecfdf5' },
  { label: '课程学习', desc: '进入课程内容', path: '/student/learning', icon: VideoPlay, color: '#2563eb', bg: '#eff6ff' },
  { label: '知识库提问', desc: '向知识库提问', path: '/student/qa', icon: ChatDotRound, color: '#8b5cf6', bg: '#f5f3ff' },
  { label: '我的作业', desc: '提交课程作业', path: '/student/homework', icon: Notebook, color: '#0ea5e9', bg: '#f0f9ff' },
  { label: '我的考试', desc: '参加考试答题', path: '/student/exams', icon: Document, color: '#ef4444', bg: '#fef2f2' },
  { label: '错题本', desc: '复盘错题记录', path: '/student/wrong', icon: Collection, color: '#f59e0b', bg: '#fff7ed' },
]

const adminFeatures = [
  { label: '管理概览', desc: '查看平台运行数据', path: '/admin/overview', icon: DataAnalysis, color: '#2563eb', bg: '#eff6ff' },
  { label: '用户管理', desc: '维护教师与学生账号', path: '/admin/users', icon: UserFilled, color: '#8b5cf6', bg: '#f5f3ff' },
  { label: '教学监管', desc: '监管课程与班级状态', path: '/admin/teaching', icon: Reading, color: '#10b981', bg: '#ecfdf5' },
  { label: '大模型配置', desc: '配置模型并测试连接', path: '/admin/ai-settings', icon: Setting, color: '#0ea5e9', bg: '#f0f9ff' },
  { label: '个人中心', desc: '维护管理员账号资料', path: '/profile', icon: HomeFilled, color: '#f59e0b', bg: '#fff7ed' },
]

const features = computed(() => {
  if (userStore.profile?.role === 'admin') return adminFeatures
  if (userStore.profile?.role === 'student') return studentFeatures
  return teacherFeatures
})

function handleSelect(item) {
  if (item.path) router.push(item.path)
}
</script>

<style scoped>
.dashboard {
  --workspace-bg: #f6f9fd;
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  padding: 0;
  overflow: hidden;
  background: var(--workspace-bg);
  color: #0f172a;
}

.dashboard::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: min(64vw, 920px);
  background: linear-gradient(116deg, rgba(255, 255, 255, 0.56) 0%, rgba(239, 246, 255, 0.34) 36%, transparent 60%);
  filter: blur(18px);
  opacity: 0.9;
  pointer-events: none;
}

.dashboard::after {
  content: '';
  position: absolute;
  inset: 0;
  background:
    linear-gradient(to bottom, var(--workspace-bg) 0%, transparent 18%, transparent 78%, var(--workspace-bg) 100%),
    linear-gradient(to right, var(--workspace-bg) 0%, transparent 18%, transparent 82%, var(--workspace-bg) 100%);
  opacity: 0.62;
  pointer-events: none;
}

.workspace-helix {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  min-height: 0;
}

@media (max-width: 1100px), (prefers-reduced-motion: reduce) {
  .dashboard { height: auto; min-height: 100%; overflow: visible; }
  .workspace-helix { height: auto; padding: 16px; }
}
</style>
