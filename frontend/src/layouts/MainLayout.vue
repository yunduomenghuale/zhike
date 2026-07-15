<template>
  <main class="layout app-page">
    <header class="header app-topbar">
      <button type="button" class="app-brand" @click="router.push('/dashboard')">
        <span class="brand-orbit" aria-hidden="true"></span>
        <span>智课平台</span>
      </button>

      <div v-if="searchEnabled" class="header-center">
        <el-input
          v-model="searchKeyword"
          :placeholder="searchPlaceholder"
          :prefix-icon="Search"
          class="global-search"
          clearable
          @keyup.enter="applyGlobalSearch"
          @clear="applyGlobalSearch"
        />
      </div>

      <div class="header-right">
        <el-badge is-dot class="head-badge">
          <button class="icon-btn" title="通知" @click="onBell">
            <el-icon><Bell /></el-icon>
          </button>
        </el-badge>
        <button class="icon-btn" title="全屏" @click="toggleFullscreen">
          <el-icon><FullScreen /></el-icon>
        </button>
        <button class="icon-btn" :title="isDark ? '浅色模式' : '深色模式'" @click="toggleDark">
          <el-icon><component :is="isDark ? Sunny : Moon" /></el-icon>
        </button>

        <el-dropdown @command="onCommand" trigger="click">
          <div class="user">
            <el-avatar :size="34" :icon="UserFilled" class="user-avatar" />
            <div class="user-info">
              <div class="user-name">{{ profile?.real_name || profile?.username || '用户' }}</div>
              <div class="user-role">{{ profile?.role_display }}</div>
            </div>
            <el-icon><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">
                <el-icon><SwitchButton /></el-icon> 退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div class="app-stage">
      <aside class="aside app-rail">
        <button type="button" class="space-cover" @click="router.push('/dashboard')">
          <span class="space-visual">
            <el-icon><HomeFilled /></el-icon>
          </span>
          <span class="space-title">个人空间</span>
          <span class="space-user">{{ profile?.real_name || profile?.username || '智课用户' }}</span>
        </button>

        <div class="menu-wrap">
          <el-menu :default-active="route.meta.activeMenu || route.path" router class="menu">
            <el-menu-item index="/dashboard">
              <el-icon><HomeFilled /></el-icon>
              <span>工作台</span>
            </el-menu-item>

            <template v-for="group in menuGroups" :key="group.title">
              <el-menu-item
                v-for="item in group.items"
                :key="item.index"
                :index="item.index"
              >
                <el-icon><component :is="item.icon" /></el-icon>
                <span>{{ item.label }}</span>
              </el-menu-item>
            </template>
          </el-menu>
        </div>

        <div class="aside-footer">
          <el-icon><Sunny /></el-icon>
          <span>让教学更智能</span>
        </div>
      </aside>

      <section class="app-main-panel">
        <div class="main">
          <router-view v-slot="{ Component }">
            <transition name="fade-slide" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'
import {
  HomeFilled, Reading, School, Collection, EditPen, Document,
  VideoPlay, ChatDotRound, ArrowDown, UserFilled, Search, SwitchButton, Sunny,
  Bell, FullScreen, Moon, Notebook,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const { profile } = storeToRefs(userStore)
const searchKeyword = ref('')
let searchTimer = null
const searchableRoutes = new Set(['courses', 'course-catalog', 'course-chapters', 'questions', 'course-questions'])

const searchPlaceholderMap = {
  courses: '按课程名称搜索',
  'course-catalog': '搜索章节',
  'course-chapters': '搜索章节',
  questions: '搜索题干',
  'course-questions': '搜索题干',
  knowledge: '搜索知识库',
  classes: '搜索班级',
  homework: '搜索作业',
  exams: '搜索考试',
  learning: '搜索课程',
}

const searchPlaceholder = computed(() => (
  searchPlaceholderMap[route.name] || '搜索功能、数据...'
))
const searchEnabled = computed(() => searchableRoutes.has(route.name))

function applyGlobalSearch() {
  if (!searchEnabled.value) return
  const keyword = searchKeyword.value.trim()
  router.replace({
    path: route.path,
    query: {
      ...route.query,
      search: keyword || undefined,
      page: undefined,
    },
  })
}

watch(searchKeyword, () => {
  if (!searchEnabled.value) return
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(applyGlobalSearch, 300)
})

watch(
  () => route.fullPath,
  () => {
    window.clearTimeout(searchTimer)
    searchKeyword.value = String(route.query.search || '')
  },
  { immediate: true },
)

// 深色模式：切换 html.dark，Element Plus 组件随暗色变量自动适配
const isDark = ref(document.documentElement.classList.contains('dark'))
function toggleDark() {
  const el = document.documentElement
  el.classList.add('theme-transition') // 切换瞬间启用颜色过渡
  isDark.value = !isDark.value
  el.classList.toggle('dark', isDark.value)
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
  window.setTimeout(() => el.classList.remove('theme-transition'), 450)
}

// 全屏切换
function toggleFullscreen() {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen?.()
  else document.exitFullscreen?.()
}

function onBell() {
  ElMessage.info('暂无新通知')
}

const menuGroups = computed(() => {
  const isTeacher = profile.value?.role === 'teacher'
  if (isTeacher) {
    return [
      {
        title: '教师端',
        items: [
          { index: '/teacher/courses', label: '课程管理', icon: 'Reading' },
          { index: '/teacher/classes', label: '班级管理', icon: 'School' },
        ],
      },
    ]
  }
  return [
    {
      title: '学生端',
      items: [
        { index: '/student/my-classes', label: '我的班级', icon: 'School' },
        { index: '/student/learning', label: '课程学习', icon: 'VideoPlay' },
        { index: '/student/qa', label: '知识库提问', icon: 'ChatDotRound' },
        { index: '/student/homework', label: '我的作业', icon: 'Notebook' },
        { index: '/student/exams', label: '我的考试', icon: 'Document' },
        { index: '/student/wrong', label: '错题本', icon: 'Collection' },
      ],
    },
  ]
})

onMounted(() => {
  if (!profile.value) userStore.fetchProfile()
})

function onCommand(cmd) {
  if (cmd === 'logout') {
    userStore.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout {
  height: 100%;
}

.aside {
  background: var(--el-bg-color);
  border-right: 1px solid var(--el-border-color-light);
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 12px rgba(15, 23, 42, 0.04);
  z-index: 10;
}

.logo {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.logo-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #2563eb, #4f46e5);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
}

.logo-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.2;
}

.logo-sub {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.2;
}

.menu-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 16px 12px;
}

.menu {
  background: transparent;
  border-right: none;
}

.menu :deep(.el-menu-item) {
  height: 46px;
  line-height: 46px;
  border-radius: 10px;
  margin-bottom: 4px;
  color: var(--el-text-color-regular);
  font-size: 14px;
  transition: all 0.2s ease;
}

.menu :deep(.el-menu-item:hover) {
  background: var(--el-fill-color);
  color: var(--el-color-primary);
}

.menu :deep(.el-menu-item.is-active) {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-weight: 600;
}

.menu :deep(.el-menu-item.is-active::before) {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 4px;
  background: #2563eb;
  border-radius: 0 4px 4px 0;
}

.menu :deep(.el-icon) {
  color: inherit;
}

.menu :deep(.el-menu-item-group__title) {
  padding: 16px 12px 8px;
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.aside-footer {
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: relative;
  /* 与下方内容区（.main）使用同一背景变量，融为一体、无分割线 */
  background: var(--el-bg-color-page);
  height: 52px;
  padding: 0 24px;
}

.header-left {
  flex-shrink: 0;
}

.page-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.2;
}

/* 相对整个顶栏定位（偏左），不受标题宽度变化影响，切页时位置固定不动 */
.header-center {
  position: absolute;
  left: 40%;
  top: 50%;
  transform: translate(-50%, -50%);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.global-search {
  width: 240px;
  transition: width 0.3s ease;
}

/* 点击/聚焦时展开变宽，失焦后收回 */
.global-search:focus-within {
  width: 340px;
}

/* 灰色圆角框（圆角适中），默认/悬停/聚焦三态完全一致 */
.global-search :deep(.el-input__wrapper),
.global-search :deep(.el-input__wrapper:hover),
.global-search :deep(.el-input__wrapper.is-focus) {
  border-radius: 8px;
  background: var(--el-fill-color-dark);
  box-shadow: 0 0 0 1px var(--el-border-color-light) inset;
}

/* 顶栏图标按钮 */
.icon-btn {
  width: 38px;
  height: 38px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--el-text-color-regular);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  transition: background 0.2s ease, color 0.2s ease;
}

.icon-btn:hover {
  background: var(--el-fill-color);
  color: var(--el-color-primary);
}

.head-badge :deep(.el-badge__content.is-dot) {
  top: 6px;
  right: 8px;
}

.user {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  padding: 6px 10px;
  border-radius: 10px;
  transition: background 0.2s ease;
}

.user:hover {
  background: var(--el-fill-color);
}

.user-avatar {
  background: linear-gradient(135deg, #2563eb, #4f46e5);
  color: #fff;
  flex-shrink: 0;
}

.user-info {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.user-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.user-role {
  font-size: 12px;
  color: #64748b;
}

.main {
  /* 与顶栏同一背景变量，二者完全一致 */
  background: var(--el-bg-color-page);
  padding: 0;
  overflow-y: auto;
}

/* 小屏适配 */
@media screen and (max-width: 768px) {
  .login-container {
    width: 100%;
    max-width: 420px;
    min-height: 720px;
  }

  .form-box {
    padding: 32px;
  }

  .form-box,
  .toggle-panel {
    width: 100%;
  }

  .form-box.login {
    top: 0;
    left: 0;
  }

  .form-box.register {
    top: 0;
    left: 0;
    transform: translateY(100%);
  }

  .login-container.active .form-box.login {
    transform: translateY(-100%);
  }

  .login-container.active .form-box.register {
    transform: translateY(0);
  }

  .toggle-box::before {
    top: 0;
    left: 0;
    width: 100%;
    height: 40%;
    border-radius: 0 0 50px 50px;
  }

  .login-container.active .toggle-box::before {
    top: 60%;
    left: 0;
    border-radius: 50px 50px 0 0;
  }

  .toggle-left {
    top: 0;
    left: 0;
  }

  .toggle-right {
    top: 60%;
    right: 0;
  }
}

/* Warm glass application shell */
.layout {
  background: #f1f5fb;
}

.aside {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(239, 246, 255, 0.88));
  border-right: 1px solid rgba(37, 99, 235, 0.1);
  box-shadow:
    18px 0 50px rgba(37, 99, 235, 0.1),
    inset -1px 0 0 rgba(255, 255, 255, 0.68);
  backdrop-filter: blur(22px) saturate(1.12);
}

.logo {
  height: 74px;
  border-bottom: 1px solid rgba(37, 99, 235, 0.08);
}

.logo-icon {
  border-radius: 15px;
  background:
    radial-gradient(circle at 50% 50%, rgba(255, 255, 255, 0.2), transparent 32%),
    linear-gradient(135deg, #2563eb, #4f46e5);
  box-shadow: 0 14px 30px rgba(37, 99, 235, 0.24);
}

.logo-title {
  color: #0f172a;
  font-weight: 850;
}

.logo-sub,
.aside-footer {
  color: #94a3b8;
}

.aside-footer {
  border-top: 1px solid rgba(37, 99, 235, 0.08);
}

.menu-wrap {
  padding: 18px 12px;
}

.menu :deep(.el-menu-item) {
  height: 48px;
  line-height: 48px;
  margin-bottom: 8px;
  border-radius: 18px;
  color: #475569;
  font-size: 15px;
  font-weight: 720;
}

.menu :deep(.el-menu-item:hover) {
  background: rgba(219, 234, 254, 0.66);
  color: #2563eb;
  transform: translateX(2px);
}

.menu :deep(.el-menu-item.is-active) {
  color: #fff;
  background: linear-gradient(135deg, #2563eb, #3b82f6);
  font-weight: 820;
  box-shadow: 0 14px 30px rgba(37, 99, 235, 0.22);
}

.menu :deep(.el-menu-item.is-active::before) {
  display: none;
}

.header {
  background: rgba(255, 255, 255, 0.88);
  padding: 0 28px;
  color: #0f172a;
  box-shadow: 0 16px 38px rgba(37, 99, 235, 0.08);
  backdrop-filter: blur(20px) saturate(1.12);
  z-index: 8;
}

.page-title {
  color: #0f172a;
  font-weight: 850;
}

.global-search :deep(.el-input__wrapper),
.global-search :deep(.el-input__wrapper:hover),
.global-search :deep(.el-input__wrapper.is-focus) {
  border-radius: 999px;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(239, 246, 255, 0.82));
  box-shadow:
    0 14px 28px rgba(37, 99, 235, 0.1),
    0 5px 12px rgba(15, 23, 42, 0.06),
    inset 0 1px 1px rgba(255, 255, 255, 0.98),
    inset 0 -1px 2px rgba(37, 99, 235, 0.08),
    0 0 0 1px rgba(37, 99, 235, 0.14) inset;
}

.global-search :deep(.el-input__inner) {
  color: #0f172a;
}

.global-search :deep(.el-input__inner::placeholder) {
  color: #94a3b8;
}

.icon-btn {
  color: #64748b;
  box-shadow:
    inset 0 1px 1px rgba(255, 255, 255, 0.78),
    inset 0 -1px 2px rgba(37, 99, 235, 0.05);
}

.icon-btn:hover,
.user:hover {
  background: rgba(219, 234, 254, 0.72);
  color: #2563eb;
}

.user-avatar {
  background: linear-gradient(135deg, #2563eb, #4f46e5);
}

.user-name {
  color: #0f172a;
}

.user-role {
  color: #64748b;
}

.main {
  background: #f1f5fb;
}

/* Match the standalone course workspace shell. */
.app-page {
  min-height: 100vh;
  position: relative;
  overflow: hidden;
  display: block;
  background:
    radial-gradient(circle at 24% 26%, rgba(96, 165, 250, 0.22), transparent 26rem),
    radial-gradient(circle at 76% 54%, rgba(37, 99, 235, 0.14), transparent 32rem),
    linear-gradient(135deg, #f8fbff 0%, #eef4fb 48%, #f6f9fd 100%);
  color: #0f172a;
}

.app-page::before {
  content: "";
  position: absolute;
  inset: 60px auto 0 0;
  width: min(56vw, 820px);
  background:
    linear-gradient(118deg, rgba(255, 255, 255, 0.92) 0%, rgba(219, 234, 254, 0.58) 30%, transparent 58%);
  filter: blur(16px);
  opacity: 0.92;
  pointer-events: none;
}

.app-page::after {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(to bottom, rgba(241, 245, 251, 0.9), transparent 18%, transparent 82%, rgba(241, 245, 251, 0.94)),
    linear-gradient(to right, rgba(241, 245, 251, 0.88), transparent 20%, transparent 82%, rgba(241, 245, 251, 0.92));
  pointer-events: none;
}

.app-topbar {
  height: 52px;
  position: relative;
  z-index: 3;
  padding: 0 30px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 16px 38px rgba(37, 99, 235, 0.08);
  backdrop-filter: blur(20px) saturate(1.12);
}

.app-brand {
  border: 0;
  padding: 0;
  background: transparent;
  color: #0f172a;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 800;
  cursor: pointer;
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

.app-stage {
  position: relative;
  z-index: 1;
  height: calc(100vh - 52px);
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 24px;
  padding: 26px 38px 30px;
  box-sizing: border-box;
}

.app-rail {
  width: auto !important;
  min-height: 0;
  height: 100%;
  border: 1px solid rgba(37, 99, 235, 0.1);
  border-radius: 30px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow:
    0 28px 70px rgba(37, 99, 235, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(24px) saturate(1.18);
  overflow: hidden;
}

.space-cover {
  width: 100%;
  border: 0;
  padding: 30px 22px 28px;
  display: grid;
  justify-items: center;
  gap: 11px;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.space-visual {
  width: 84px;
  height: 84px;
  border-radius: 24px;
  display: grid;
  place-items: center;
  background: rgba(239, 246, 255, 0.9);
  color: #2563eb;
  font-size: 34px;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.72),
    0 16px 36px rgba(37, 99, 235, 0.12);
}

.space-title {
  color: #0f172a;
  font-size: 18px;
  font-weight: 850;
  line-height: 1.35;
}

.space-user {
  max-width: 100%;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-rail .menu-wrap {
  padding: 0 18px 20px;
}

.app-rail .menu :deep(.el-menu-item) {
  height: 46px;
  line-height: 46px;
  margin-bottom: 8px;
  padding: 0 15px !important;
  border-radius: 14px;
  font-size: 15px;
  font-weight: 760;
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease,
    color 0.18s ease,
    background-color 0.18s ease;
}

.app-rail .menu :deep(.el-menu-item:hover) {
  color: #2563eb;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.95), rgba(219, 234, 254, 0.66));
  box-shadow:
    0 10px 22px rgba(37, 99, 235, 0.09),
    inset 0 1px 1px rgba(255, 255, 255, 0.9),
    inset 0 -1px 2px rgba(37, 99, 235, 0.06);
  transform: translateX(2px);
}

.app-rail .menu :deep(.el-menu-item.is-active) {
  color: #fff;
  background: #3b82f6;
  box-shadow:
    0 10px 22px rgba(37, 99, 235, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.app-rail .menu :deep(.el-menu-item.is-active:hover) {
  color: #fff;
  background: #2563eb;
  box-shadow:
    0 12px 26px rgba(37, 99, 235, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.24);
}

.app-rail .aside-footer {
  margin-top: auto;
  border-top: 1px solid rgba(37, 99, 235, 0.08);
}

.app-main-panel {
  min-width: 0;
  min-height: 0;
  height: 100%;
  border: 1px solid rgba(37, 99, 235, 0.1);
  border-radius: 30px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow:
    0 30px 80px rgba(37, 99, 235, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.74);
  backdrop-filter: blur(22px) saturate(1.12);
  overflow: hidden;
}

.app-main-panel .main {
  height: 100%;
  padding: 0;
  overflow-y: auto;
  background: transparent;
}

.app-main-panel .main :deep(.page-container) {
  min-height: 100%;
  padding: 30px 36px 36px;
  box-sizing: border-box;
  background: transparent;
}

@media (max-width: 1024px) {
  .app-stage {
    grid-template-columns: 1fr;
    padding: 22px;
    overflow-y: auto;
  }

  .app-rail {
    height: auto;
    min-height: auto;
  }

  .space-cover,
  .app-rail .aside-footer {
    display: none;
  }

  .app-rail .menu-wrap {
    padding: 14px;
  }

  .app-rail .menu {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }

  .app-rail .menu :deep(.el-menu-item) {
    margin: 0;
    justify-content: center;
  }

  .app-main-panel {
    height: auto;
    min-height: calc(100vh - 178px);
  }
}

@media (max-width: 720px) {
  .app-topbar {
    padding: 0 16px;
  }

  .app-brand span:last-child,
  .user-info,
  .head-badge {
    display: none;
  }

  .header-center {
    position: static;
    transform: none;
    margin-left: auto;
  }

  .global-search,
  .global-search:focus-within {
    width: min(42vw, 220px);
  }

  .app-stage {
    padding: 14px;
    gap: 14px;
  }

  .app-rail .menu {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .app-main-panel,
  .app-rail {
    border-radius: 22px;
  }

  .app-main-panel .main :deep(.page-container) {
    padding: 20px 16px 24px;
  }
}
</style>
