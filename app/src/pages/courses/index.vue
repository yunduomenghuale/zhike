<template>
  <view class="page">
    <AppHeader />
    <scroll-view class="scroll" scroll-y refresher-enabled :refresher-triggered="refreshing" @refresherrefresh="refresh">
      <view class="content">
        <view v-if="!isTeacher" class="join-card">
          <view class="join-copy"><view class="join-title">加入新班级</view><view class="join-desc">输入老师分享的邀请码</view></view>
          <view class="join-form">
            <input v-model.trim="inviteCode" class="join-input" placeholder="如：AB12CD34" placeholder-class="placeholder" :maxlength="12" confirm-type="done" @confirm="join" />
            <button class="join-button" :disabled="joining || !inviteCode" :loading="joining" @click="join">加入</button>
          </view>
        </view>

        <view class="list-head"><view class="list-title">{{ isTeacher ? '授课课程' : '已加入课程' }}</view><view class="count">{{ courses.length }}</view></view>
        <view v-if="loading" class="loading">正在加载课程…</view>
        <EmptyState v-else-if="!courses.length" icon="list" title="还没有课程" :description="isTeacher ? '请先在网页端创建课程' : '输入邀请码加入班级后开始学习'" />

        <view v-else class="course-list">
          <view v-for="(course, index) in courses" :key="`${course.id}-${index}`" class="course-card" hover-class="course-tap" @click="openCourse(course)">
            <view class="cover" :class="`cover-${index % 3}`">
              <view class="cover-shape"></view>
              <uni-icons type="list" color="#ffffff" size="28" />
            </view>
            <view class="course-body">
              <view class="course-top"><view class="course-name">{{ course.name }}</view><view class="status">{{ course.statusText }}</view></view>
              <view class="course-meta"><text>{{ course.meta }}</text><text class="dot">·</text><text>{{ course.term || '智课平台' }}</text></view>
              <view class="course-action"><text>查看章节</text><uni-icons type="right" color="#2563eb" size="13" /></view>
            </view>
          </view>
        </view>
      </view>
    </scroll-view>
    <BottomNav active="courses" />
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import BottomNav from '@/components/BottomNav.vue'
import EmptyState from '@/components/EmptyState.vue'
import { joinClass, listClasses, listCourses } from '@/api/courses.js'

const user = ref(uni.getStorageSync('user') || {})
const isTeacher = computed(() => user.value.role === 'teacher')
const rawRows = ref([])
const inviteCode = ref('')
const loading = ref(false)
const joining = ref(false)
const refreshing = ref(false)

const courses = computed(() => {
  if (isTeacher.value) return rawRows.value.map((item) => ({ id: item.id, name: item.name, meta: item.intro || '教师课程', term: item.term, statusText: item.status_display || '进行中' }))
  const result = []
  rawRows.value.forEach((room) => {
    const ids = room.courses?.length ? room.courses : [room.course]
    ids.filter(Boolean).forEach((id, index) => result.push({ id, name: room.course_names?.[index] || room.course_name || `课程 ${id}`, meta: room.name, statusText: room.status === 'open' ? '开课中' : '已结课' }))
  })
  return result
})

async function load() {
  loading.value = true
  try {
    const data = isTeacher.value ? await listCourses() : await listClasses()
    rawRows.value = data.results ?? data
  } finally { loading.value = false; refreshing.value = false }
}

async function join() {
  if (!inviteCode.value || joining.value) return
  if (!user.value.real_name?.trim() || !user.value.phone?.trim()) {
    uni.showModal({ title: '请先完善资料', content: '填写姓名和手机号后才能加入班级。', confirmText: '去填写', success: ({ confirm }) => confirm && uni.navigateTo({ url: '/pages/profile/edit' }) })
    return
  }
  joining.value = true
  try {
    await joinClass(inviteCode.value)
    inviteCode.value = ''
    uni.showToast({ title: '加入成功', icon: 'success' })
    load()
  } finally { joining.value = false }
}

function openCourse(course) { uni.navigateTo({ url: `/pages/course/chapters?course=${course.id}&name=${encodeURIComponent(course.name)}` }) }
function refresh() { refreshing.value = true; load() }
onShow(load)
</script>

<style scoped lang="scss">
.page { min-height: 100vh; }
.scroll { height: calc(100vh - var(--app-safe-top) - 96rpx); }
.content { padding: 24rpx 24rpx 126rpx; }
.join-card { margin-bottom: 38rpx; padding: 27rpx; border: 1rpx solid rgba(37, 99, 235, .1); border-radius: 29rpx; background: linear-gradient(135deg, #edf5ff, #fff); box-shadow: $shadow-card; }
.join-title { color: $text-main; font-size: 25rpx; font-weight: 800; }
.join-desc { margin-top: 5rpx; color: $text-light; font-size: 20rpx; }
.join-form { display: flex; gap: 14rpx; margin-top: 22rpx; }
.join-input { min-width: 0; height: 82rpx; flex: 1; padding: 0 22rpx; border: 1rpx solid #dbe7f7; border-radius: 20rpx; background: #fff; color: $text-main; font-size: 25rpx; text-transform: uppercase; }
.placeholder { color: #a7b0bf; }
.join-button { width: 128rpx; height: 82rpx; line-height: 82rpx; border-radius: 20rpx; background: $brand; color: #fff; font-size: 24rpx; font-weight: 700; }
.join-button[disabled] { background: #bfdbfe; color: #fff; }
.list-head { display: flex; align-items: center; gap: 10rpx; margin: 0 4rpx 18rpx; }
.list-title { color: $text-main; font-size: 26rpx; font-weight: 850; }
.count { min-width: 37rpx; height: 37rpx; padding: 0 10rpx; border-radius: 999rpx; background: $brand-soft; color: $brand; font-size: 19rpx; font-weight: 700; line-height: 37rpx; text-align: center; }
.course-card { overflow: hidden; margin-bottom: 22rpx; border: 1rpx solid rgba(37, 99, 235, .075); border-radius: 30rpx; background: #fff; box-shadow: 0 10rpx 30rpx rgba(15, 23, 42, .045); }
.cover { position: relative; height: 130rpx; display: flex; align-items: center; padding: 0 30rpx; background: linear-gradient(135deg, #1d4ed8, #60a5fa); }
.cover-1 { background: linear-gradient(135deg, #4338ca, #818cf8); }
.cover-2 { background: linear-gradient(135deg, #0369a1, #38bdf8); }
.cover-shape { position: absolute; top: -90rpx; right: -30rpx; width: 260rpx; height: 260rpx; border: 1rpx solid rgba(255, 255, 255, .24); border-radius: 50%; }
.course-body { padding: 24rpx 27rpx 25rpx; }
.course-top { display: flex; align-items: flex-start; gap: 16rpx; }
.course-name { min-width: 0; flex: 1; overflow: hidden; color: $text-main; font-size: 28rpx; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.status { flex-shrink: 0; padding: 5rpx 13rpx; border-radius: 999rpx; background: #ecfdf5; color: #059669; font-size: 18rpx; font-weight: 700; }
.course-meta { display: flex; align-items: center; gap: 8rpx; margin-top: 10rpx; overflow: hidden; color: $text-light; font-size: 20rpx; white-space: nowrap; }
.dot { color: #cbd5e1; }
.course-action { display: flex; align-items: center; gap: 6rpx; margin-top: 21rpx; color: $brand; font-size: 21rpx; font-weight: 700; }
.course-tap { opacity: .72; transform: scale(.985); }
.loading { padding: 72rpx 20rpx; color: $text-light; font-size: 21rpx; text-align: center; }
</style>
