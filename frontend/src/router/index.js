import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'

// 每个角色的主页（工作台会按角色自适应展示对应内容）
const ROLE_HOME = '/dashboard'

const courseWorkspaceRoute = {
  path: '/teacher/courses/:id',
  component: () => import('@/views/teacher/CourseWorkspace.vue'),
  redirect: (to) => ({ name: 'course-chapters', params: { id: to.params.id } }),
  meta: { title: '课程空间', role: 'teacher' },
  children: [
    { path: 'chapters', name: 'course-chapters', component: () => import('@/views/teacher/CourseCatalog.vue'), meta: { title: '章节与课件', role: 'teacher' } },
    { path: 'knowledge', name: 'course-knowledge', component: () => import('@/views/teacher/KnowledgeBase.vue'), meta: { title: '知识库', role: 'teacher' } },
    { path: 'qa', name: 'course-qa', component: () => import('@/views/teacher/CourseQA.vue'), meta: { title: 'AI 问答', role: 'teacher' } },
    { path: 'questions', name: 'course-questions', component: () => import('@/views/teacher/QuestionManage.vue'), meta: { title: '题库', role: 'teacher' } },
    { path: 'homework', name: 'course-homework', component: () => import('@/views/teacher/HomeworkManage.vue'), meta: { title: '作业', role: 'teacher' } },
    { path: 'exams', name: 'course-exams', component: () => import('@/views/teacher/ExamManage.vue'), meta: { title: '考试', role: 'teacher' } },
    { path: 'analytics', name: 'course-analytics', component: () => import('@/views/teacher/Analytics.vue'), meta: { title: '学习统计', role: 'teacher' } },
  ],
}

const studentCourseWorkspaceRoute = {
  path: '/student/courses/:id',
  component: () => import('@/views/student/CourseWorkspace.vue'),
  redirect: (to) => ({ name: 'student-course-learning', params: { id: to.params.id } }),
  meta: { title: '课程空间', role: 'student' },
  children: [
    { path: 'learning', name: 'student-course-learning', component: () => import('@/views/student/Learning.vue'), meta: { title: '课程学习', role: 'student' } },
    { path: 'qa', name: 'student-course-qa', component: () => import('@/views/student/KnowledgeQA.vue'), meta: { title: 'AI 助教', role: 'student' } },
    { path: 'materials', name: 'student-course-materials', component: () => import('@/views/student/CourseMaterials.vue'), meta: { title: '课程资料', role: 'student' } },
    { path: 'homework', name: 'student-course-homework', component: () => import('@/views/student/MyHomework.vue'), meta: { title: '我的作业', role: 'student' } },
    { path: 'exams', name: 'student-course-exams', component: () => import('@/views/student/ExamList.vue'), meta: { title: '我的考试', role: 'student' } },
    { path: 'wrong', name: 'student-course-wrong', component: () => import('@/views/student/WrongBook.vue'), meta: { title: '错题本', role: 'student' } },
  ],
}

const routes = [
  { path: '/login', name: 'login', component: () => import('@/views/Login.vue'), meta: { public: true } },
  courseWorkspaceRoute,
  studentCourseWorkspaceRoute,
  { path: '/teacher/courses/:id/catalog', name: 'course-catalog', redirect: (to) => ({ name: 'course-chapters', params: { id: to.params.id } }) },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/Dashboard.vue'), meta: { title: '工作台' } },
      { path: 'profile', name: 'profile', component: () => import('@/views/Profile.vue'), meta: { title: '个人中心' } },

      { path: 'admin/overview', name: 'admin-overview', component: () => import('@/views/admin/AdminOverview.vue'), meta: { title: '管理概览', role: 'admin' } },
      { path: 'admin/users', name: 'admin-users', component: () => import('@/views/admin/AdminUsers.vue'), meta: { title: '用户管理', role: 'admin' } },
      { path: 'admin/teaching', name: 'admin-teaching', component: () => import('@/views/admin/AdminTeaching.vue'), meta: { title: '教学监管', role: 'admin' } },
      { path: 'admin/ai-settings', name: 'admin-ai-settings', component: () => import('@/views/admin/AdminAISettings.vue'), meta: { title: '大模型配置', role: 'admin' } },

      { path: 'teacher/courses', name: 'courses', component: () => import('@/views/teacher/CourseList.vue'), meta: { title: '课程管理', role: 'teacher' } },
      { path: 'teacher/classes', name: 'classes', component: () => import('@/views/teacher/ClassManage.vue'), meta: { title: '班级管理', role: 'teacher' } },
      { path: 'teacher/classes/:classId/students/:studentId', name: 'class-student-detail', component: () => import('@/views/teacher/StudentDetail.vue'), meta: { title: '学生详情', role: 'teacher' } },
      { path: 'teacher/knowledge', name: 'knowledge', component: () => import('@/views/teacher/KnowledgeBase.vue'), meta: { title: '知识库', role: 'teacher' } },
      { path: 'teacher/questions', name: 'questions', component: () => import('@/views/teacher/QuestionManage.vue'), meta: { title: '题库', role: 'teacher' } },
      { path: 'teacher/homework', name: 'homework', component: () => import('@/views/teacher/HomeworkManage.vue'), meta: { title: '作业管理', role: 'teacher' } },
      { path: 'teacher/exams', name: 'exams', component: () => import('@/views/teacher/ExamManage.vue'), meta: { title: '考试', role: 'teacher' } },
      { path: 'teacher/analytics', name: 'analytics', component: () => import('@/views/teacher/Analytics.vue'), meta: { title: '学习统计', role: 'teacher' } },

      { path: 'student/my-classes', name: 'my-classes', component: () => import('@/views/student/MyClasses.vue'), meta: { title: '我的班级', role: 'student' } },
      { path: 'student/learning', name: 'learning', component: () => import('@/views/student/Learning.vue'), meta: { title: '课程学习', role: 'student' } },
      { path: 'student/qa', name: 'qa', component: () => import('@/views/student/KnowledgeQA.vue'), meta: { title: '知识库提问', role: 'student' } },
      { path: 'student/homework', name: 'student-homework', component: () => import('@/views/student/MyHomework.vue'), meta: { title: '我的作业', role: 'student' } },
      { path: 'student/exams', name: 'student-exams', component: () => import('@/views/student/ExamList.vue'), meta: { title: '我的考试', role: 'student' } },
      { path: 'student/wrong', name: 'wrong-book', component: () => import('@/views/student/WrongBook.vue'), meta: { title: '错题本', role: 'student' } },
      { path: 'student/exams/:id/take', name: 'exam-taking', component: () => import('@/views/student/ExamTaking.vue'), meta: { title: '在线考试', role: 'student', activeMenu: '/student/my-classes' } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const userStore = useUserStore()
  const token = localStorage.getItem('access_token')

  // 公共页（登录/注册）：已登录则回主页，否则放行
  if (to.meta.public) {
    return token ? { path: ROLE_HOME } : true
  }

  // 未登录：拦到登录页并记住来源
  if (!token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 已登录但尚未加载资料（如刷新/直达 URL）：先拉取角色，失败则视为登录失效
  if (!userStore.profile) {
    try {
      await userStore.fetchProfile()
    } catch {
      userStore.logout()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }

  // 角色边界：页面声明了 meta.role 且与当前角色不符 → 送回本角色主页
  const role = userStore.profile?.role
  const need = to.meta.role
  if (need && role !== need && role !== 'admin') {
    ElMessage.warning('无权访问该页面，已返回工作台')
    return { path: ROLE_HOME }
  }

  return true
})

export default router
