<template>
  <view class="page">
    <AppHeader>
      <template #right>
        <view class="notify" hover-class="tap" @click="go('/pages/notifications/index', true)">
          <uni-icons type="notification" color="#334155" size="21" />
          <view v-if="unread" class="notify-dot"></view>
        </view>
      </template>
    </AppHeader>

    <scroll-view class="scroll" scroll-y refresher-enabled :refresher-triggered="refreshing" @refresherrefresh="refresh">
      <view class="content">
        <view v-if="profileIncomplete" class="profile-alert" hover-class="tap" @click="go('/pages/profile/edit')">
          <view class="alert-icon"><uni-icons type="info-filled" color="#f59e0b" size="20" /></view>
          <view class="alert-copy">
            <view class="alert-title">请完善个人资料</view>
            <view class="alert-desc">填写姓名和手机号后才能加入班级</view>
          </view>
          <uni-icons type="right" color="#d97706" size="14" />
        </view>

        <view class="hero">
          <view class="hero-glow"></view>
          <view class="date-row"><view class="date-dot"></view><text>{{ today }}</text></view>
          <view class="hero-main">
            <view class="hero-copy">
              <view class="greeting">{{ greeting }}，{{ displayName }}</view>
              <view class="welcome">欢迎回到智课平台，{{ isTeacher ? '开始今天的教学工作' : '继续今天的学习' }}</view>
            </view>
            <view class="role">{{ user?.role_display || (isTeacher ? '教师' : '学生') }}</view>
          </view>
          <view class="stats">
            <view class="stat"><view class="stat-value">{{ metrics.first }}</view><view class="stat-label">{{ isTeacher ? '课程' : '已加入班级' }}</view></view>
            <view class="divider"></view>
            <view class="stat"><view class="stat-value">{{ metrics.second }}</view><view class="stat-label">{{ isTeacher ? '班级' : '我的课程' }}</view></view>
            <view class="divider"></view>
            <view class="stat" @click="go('/pages/notifications/index', true)"><view class="stat-value">{{ unread }}</view><view class="stat-label">未读消息</view></view>
          </view>
        </view>

        <view class="section-head">
          <view><view class="section-title">{{ isTeacher ? '教学中心' : '学习中心' }}</view><view class="section-subtitle">今天想先做什么？</view></view>
        </view>

        <view class="action-grid">
          <view v-for="action in actions" :key="action.title" class="action-card" hover-class="card-tap" @click="go(action.url, action.root)">
            <view class="action-top">
              <view class="action-icon" :style="{ background: action.bg }"><uni-icons :type="action.icon" :color="action.color" size="24" /></view>
              <view class="round-arrow"><uni-icons type="right" color="#94a3b8" size="13" /></view>
            </view>
            <view class="action-title">{{ action.title }}</view>
            <view class="action-desc">{{ action.desc }}</view>
          </view>
        </view>

        <view class="section-head recent-head">
          <view><view class="section-title">{{ isTeacher ? '我的课程' : '继续学习' }}</view><view class="section-subtitle">最近可访问的课程</view></view>
          <view class="more" @click="go('/pages/courses/index', true)">全部</view>
        </view>

        <view v-if="loading" class="loading">正在加载…</view>
        <EmptyState v-else-if="!recentCourses.length" compact icon="list" title="还没有课程" :description="isTeacher ? '请在网页端创建第一门课程' : '完善资料后用邀请码加入班级'" />
        <view v-else class="course-list">
          <view v-for="course in recentCourses" :key="course.id" class="course-row" hover-class="tap" @click="openCourse(course)">
            <view class="course-mark"><uni-icons type="list" color="#2563eb" size="20" /></view>
            <view class="course-copy"><view class="course-name">{{ course.name }}</view><view class="course-meta">{{ course.meta }}</view></view>
            <uni-icons type="right" color="#cbd5e1" size="14" />
          </view>
        </view>
      </view>
    </scroll-view>
    <BottomNav active="home" :unread="unread" />
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import BottomNav from '@/components/BottomNav.vue'
import EmptyState from '@/components/EmptyState.vue'
import { getMe } from '@/api/auth.js'
import { listClasses, listCourses } from '@/api/courses.js'
import { listNotifications } from '@/api/notifications.js'

const user = ref(uni.getStorageSync('user') || null)
const rows = ref([])
const notifications = ref([])
const loading = ref(false)
const refreshing = ref(false)
const isTeacher = computed(() => user.value?.role === 'teacher')
const displayName = computed(() => user.value?.real_name || user.value?.username || '同学')
const profileIncomplete = computed(() => user.value?.role === 'student' && (!user.value?.real_name?.trim() || !user.value?.phone?.trim()))
const unread = computed(() => notifications.value.filter((item) => !item.is_read).length)
const greeting = computed(() => { const hour = new Date().getHours(); return hour < 6 ? '夜深了' : hour < 12 ? '上午好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好' })
const today = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })

const actions = computed(() => [
  { title: isTeacher.value ? '课程管理' : '我的课程', desc: isTeacher.value ? '查看课程与章节' : '进入章节继续学习', icon: 'list', color: '#2563eb', bg: '#eff6ff', url: '/pages/courses/index', root: true },
  { title: 'AI 课堂', desc: '进入课程后向本章 AI 提问', icon: 'chatbubble', color: '#6366f1', bg: '#eef2ff', url: '/pages/courses/index', root: true },
  { title: '消息通知', desc: '查看作业、考试和系统提醒', icon: 'notification', color: '#0ea5e9', bg: '#f0f9ff', url: '/pages/notifications/index', root: true },
  { title: '个人资料', desc: '维护姓名、手机号和账号', icon: 'person', color: '#10b981', bg: '#ecfdf5', url: '/pages/profile/index', root: true },
])

const recentCourses = computed(() => {
  if (isTeacher.value) return rows.value.slice(0, 3).map((item) => ({ id: item.id, name: item.name, meta: item.term || '我负责的课程' }))
  const output = []
  rows.value.forEach((room) => (room.courses || []).forEach((id, index) => output.push({ id, name: room.course_names?.[index] || `课程 ${id}`, meta: room.name })))
  return output.slice(0, 3)
})

const metrics = computed(() => {
  if (isTeacher.value) return { first: rows.value.length, second: '—' }
  const courseIds = new Set()
  rows.value.forEach((room) => (room.courses || []).forEach((id) => courseIds.add(id)))
  return { first: rows.value.length, second: courseIds.size }
})

function go(url, root = false) { root ? uni.reLaunch({ url }) : uni.navigateTo({ url }) }
function openCourse(course) { uni.navigateTo({ url: `/pages/course/chapters?course=${course.id}&name=${encodeURIComponent(course.name)}` }) }

async function load() {
  loading.value = true
  try {
    const [me, data, notices] = await Promise.all([
      getMe(),
      isTeacher.value ? listCourses() : listClasses(),
      listNotifications({ page_size: 50 }),
    ])
    user.value = me
    uni.setStorageSync('user', me)
    rows.value = data.results ?? data
    notifications.value = notices.results ?? notices
  } finally { loading.value = false; refreshing.value = false }
}
function refresh() { refreshing.value = true; load() }
onShow(load)
</script>

<style scoped lang="scss">
.page { min-height: 100vh; }
.scroll { height: calc(100vh - var(--app-safe-top) - 96rpx); }
.content { padding: 8rpx 24rpx 126rpx; }
.notify { position: relative; width: 62rpx; height: 62rpx; display: flex; align-items: center; justify-content: center; border-radius: 20rpx; background: #fff; box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, .055); }
.notify-dot { position: absolute; top: 12rpx; right: 12rpx; width: 13rpx; height: 13rpx; border: 3rpx solid #fff; border-radius: 50%; background: $danger; }
.profile-alert { display: flex; align-items: center; gap: 16rpx; margin-bottom: 22rpx; padding: 20rpx 22rpx; border: 1rpx solid #fde7bd; border-radius: 23rpx; background: #fffaf0; }
.alert-icon { width: 56rpx; height: 56rpx; display: flex; align-items: center; justify-content: center; border-radius: 17rpx; background: #fff3d6; }
.alert-copy { min-width: 0; flex: 1; }
.alert-title { color: #92400e; font-size: 23rpx; font-weight: 750; }
.alert-desc { margin-top: 5rpx; color: #b45309; font-size: 19rpx; }
.hero { position: relative; overflow: hidden; padding: 28rpx 26rpx 21rpx; border: 1rpx solid rgba(37, 99, 235, .1); border-radius: 29rpx; background: linear-gradient(140deg, #eef5ff, #fff 70%); box-shadow: $shadow-card; }
.hero-glow { position: absolute; top: -130rpx; right: -90rpx; width: 330rpx; height: 330rpx; border-radius: 50%; background: rgba(191, 219, 254, .42); }
.date-row { position: relative; display: flex; align-items: center; gap: 10rpx; color: $text-sub; font-size: 21rpx; font-weight: 600; }
.date-dot { width: 10rpx; height: 10rpx; border-radius: 50%; background: #3b82f6; box-shadow: 0 0 0 6rpx rgba(59, 130, 246, .1); }
.hero-main { position: relative; display: flex; align-items: flex-start; gap: 14rpx; margin-top: 16rpx; }
.hero-copy { min-width: 0; flex: 1; }
.greeting { color: $text-main; font-size: 35rpx; font-weight: 850; line-height: 1.25; }
.welcome { margin-top: 8rpx; color: $text-sub; font-size: 19rpx; line-height: 1.5; }
.role { flex-shrink: 0; padding: 8rpx 17rpx; border: 1rpx solid #bfdbfe; border-radius: 999rpx; background: rgba(239, 246, 255, .88); color: $brand; font-size: 20rpx; font-weight: 700; }
.stats { position: relative; display: flex; align-items: center; margin-top: 24rpx; padding-top: 19rpx; border-top: 1rpx solid rgba(148, 163, 184, .18); }
.stat { flex: 1; text-align: center; }
.stat-value { color: $text-main; font-size: 28rpx; font-weight: 850; }
.stat-label { margin-top: 4rpx; color: $text-light; font-size: 17rpx; }
.divider { width: 1rpx; height: 43rpx; background: #dfe6ef; }
.section-head { display: flex; align-items: flex-end; justify-content: space-between; margin: 34rpx 4rpx 17rpx; }
.section-title { color: $text-main; font-size: 27rpx; font-weight: 850; }
.section-subtitle { margin-top: 4rpx; color: $text-light; font-size: 18rpx; }
.more { color: $brand; font-size: 22rpx; font-weight: 700; }
.action-grid { display: flex; flex-wrap: wrap; gap: 14rpx; }
.action-card { width: calc(50% - 7rpx); min-height: 168rpx; padding: 20rpx; border: 1rpx solid rgba(37, 99, 235, .075); border-radius: 25rpx; background: #fff; box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, .04); }
.action-top { display: flex; justify-content: space-between; }
.action-icon { width: 62rpx; height: 62rpx; display: flex; align-items: center; justify-content: center; border-radius: 19rpx; }
.round-arrow { width: 38rpx; height: 38rpx; display: flex; align-items: center; justify-content: center; border: 1rpx solid $line; border-radius: 50%; }
.action-title { margin-top: 15rpx; color: $text-main; font-size: 23rpx; font-weight: 800; }
.action-desc { margin-top: 5rpx; display: -webkit-box; overflow: hidden; color: $text-light; font-size: 17rpx; line-height: 1.4; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.recent-head { margin-top: 36rpx; }
.course-list { overflow: hidden; padding: 0 24rpx; border: 1rpx solid rgba(37, 99, 235, .075); border-radius: 29rpx; background: #fff; }
.course-row { min-height: 116rpx; display: flex; align-items: center; gap: 18rpx; border-bottom: 1rpx solid $line; }
.course-row:last-child { border-bottom: 0; }
.course-mark { width: 64rpx; height: 64rpx; display: flex; align-items: center; justify-content: center; border-radius: 19rpx; background: $brand-soft; }
.course-copy { min-width: 0; flex: 1; }
.course-name { overflow: hidden; color: $text-main; font-size: 24rpx; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.course-meta { margin-top: 6rpx; color: $text-light; font-size: 19rpx; }
.loading { padding: 70rpx; color: $text-light; font-size: 23rpx; text-align: center; }
.tap { opacity: .6; transform: scale(.97); }
.card-tap { background: #f3f7ff; transform: scale(.97); }
</style>
