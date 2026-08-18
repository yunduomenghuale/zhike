<template>
  <view class="page">
    <view class="hero">
      <view>
        <view class="hello">{{ greeting }}，{{ displayName }}</view>
        <view class="sub">{{ today }} · 欢迎回到智课平台</view>
      </view>
      <text class="role">{{ user?.role_display || '同学' }}</text>
    </view>

    <view class="grid">
      <view v-for="f in features" :key="f.label" class="card" @click="open(f)">
        <view class="card-icon" :style="{ color: f.color, background: f.bg }">
          <text class="card-icon-text">{{ f.icon }}</text>
        </view>
        <view class="card-main">
          <view class="card-label">{{ f.label }}</view>
          <view class="card-desc">{{ f.desc }}</view>
        </view>
        <text class="card-arrow">›</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { getMe } from '@/api/auth.js'

const user = ref(uni.getStorageSync('user') || null)

const displayName = computed(() => user.value?.real_name || user.value?.username || '同学')

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

const studentFeatures = [
  { label: '我的课程', desc: '进入课程学习', icon: '📖', color: '#2563eb', bg: '#eff6ff', tab: '/pages/course/index' },
  { label: 'AI 助教', desc: '向知识库提问', icon: '💬', color: '#8b5cf6', bg: '#f5f3ff', url: '/pages/qa/index' },
  { label: '我的作业', desc: '提交课程作业', icon: '📝', color: '#0ea5e9', bg: '#f0f9ff', url: '/pages/homework/index' },
  { label: '我的考试', desc: '参加考试答题', icon: '📄', color: '#ef4444', bg: '#fef2f2', url: '/pages/exam/index' },
  { label: '错题本', desc: '复盘错题记录', icon: '📕', color: '#f59e0b', bg: '#fff7ed', url: '/pages/wrongbook/index' },
  { label: '消息通知', desc: '作业考试动态', icon: '🔔', color: '#10b981', bg: '#ecfdf5', url: '/pages/notify/index' },
  { label: '个人中心', desc: '维护账号资料', icon: '👤', color: '#64748b', bg: '#f1f5f9', tab: '/pages/profile/index' },
]

const teacherFeatures = [
  { label: '课程管理', desc: '维护课程与章节', icon: '📖', color: '#2563eb', bg: '#eff6ff', url: '/pages/teacher/courses' },
  { label: '班级管理', desc: '管理班级与学生', icon: '🏫', color: '#10b981', bg: '#ecfdf5', url: '/pages/teacher/classes' },
  { label: '题库', desc: '维护试题资源', icon: '✏️', color: '#f59e0b', bg: '#fff7ed', url: '/pages/teacher/questions' },
  { label: '作业管理', desc: '布置与批改作业', icon: '📝', color: '#0ea5e9', bg: '#f0f9ff', url: '/pages/teacher/homework' },
  { label: '考试管理', desc: '组卷发布与出分', icon: '📄', color: '#ef4444', bg: '#fef2f2', url: '/pages/teacher/exams' },
  { label: '学习统计', desc: '查看学习数据', icon: '📊', color: '#14b8a6', bg: '#f0fdfa', url: '/pages/teacher/stats' },
  { label: '问答记录', desc: '查看学生提问', icon: '💬', color: '#8b5cf6', bg: '#f5f3ff', url: '/pages/teacher/qa-records' },
  { label: 'AI 助教', desc: '向知识库提问', icon: '🤖', color: '#6366f1', bg: '#eef2ff', url: '/pages/qa/index' },
  { label: '个人中心', desc: '维护账号资料', icon: '👤', color: '#64748b', bg: '#f1f5f9', tab: '/pages/profile/index' },
]

// 工作台按角色分流：教师看到教学管理功能，学生看到学习功能
const features = computed(() =>
  user.value?.role === 'teacher' ? teacherFeatures : studentFeatures,
)

function open(f) {
  if (f.tab) {
    uni.switchTab({ url: f.tab })
    return
  }
  if (f.url) {
    uni.navigateTo({ url: f.url })
    return
  }
  uni.showToast({ title: 'App 端陆续上线，可先使用网页端', icon: 'none' })
}

onShow(async () => {
  try {
    const me = await getMe()
    user.value = me
    uni.setStorageSync('user', me)
  } catch {
    // 拉取失败沿用缓存
  }
})
</script>

<style scoped>
.page {
  padding: 28rpx;
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 28rpx;
  padding: 36rpx 32rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 8rpx rgba(15, 23, 42, 0.06);
}

.hello {
  font-size: 36rpx;
  font-weight: 800;
  color: #0f172a;
}

.sub {
  margin-top: 10rpx;
  font-size: 24rpx;
  color: #64748b;
}

.role {
  flex-shrink: 0;
  padding: 8rpx 22rpx;
  border-radius: 999rpx;
  background: #eff6ff;
  color: #2563eb;
  font-size: 24rpx;
  font-weight: 700;
}

.grid {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.card {
  display: flex;
  align-items: center;
  gap: 22rpx;
  padding: 30rpx 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.05);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.card:active {
  transform: scale(0.98);
}

.card-icon {
  width: 88rpx;
  height: 88rpx;
  display: flex;
  flex: 0 0 88rpx;
  align-items: center;
  justify-content: center;
  border-radius: 22rpx;
}

.card-icon-text {
  font-size: 40rpx;
}

.card-main {
  flex: 1;
  min-width: 0;
}

.card-label {
  font-size: 30rpx;
  font-weight: 700;
  color: #0f172a;
}

.card-desc {
  margin-top: 6rpx;
  font-size: 23rpx;
  color: #94a3b8;
}

.card-arrow {
  flex-shrink: 0;
  font-size: 40rpx;
  color: #cbd5e1;
}
</style>
