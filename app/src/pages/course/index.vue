<template>
  <view class="page">
    <!-- 邀请码加入（仅学生） -->
    <view v-if="isStudent" class="join-bar">
      <input
        v-model="code"
        class="join-input"
        placeholder="输入邀请码加入课程"
        placeholder-class="ph"
        @confirm="join"
      />
      <button class="join-btn" :disabled="joining" :loading="joining" @click="join">加入</button>
    </view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!courseCards.length" class="tip">
        {{ isStudent ? '还没有加入任何班级，用邀请码加入吧' : '暂无关联课程' }}
      </view>
      <view
        v-for="c in courseCards"
        :key="`${c.classId}-${c.id}`"
        class="course-card"
        @click="openCourse(c)"
      >
        <view class="course-icon">📖</view>
        <view class="course-main">
          <view class="course-name">{{ c.courseName }}</view>
          <view class="course-meta">
            <text class="chip">{{ c.className }}</text>
            <text class="status" :class="c.status === 'open' ? 'open' : ''">
              {{ c.status === 'open' ? '开课中' : '已结课' }}
            </text>
          </view>
          <view v-if="courseProgress[c.id] != null" class="progress-row">
            <view class="progress-track">
              <view class="progress-fill" :style="{ width: courseProgress[c.id] + '%' }"></view>
            </view>
            <text class="progress-text">{{ courseProgress[c.id] }}%</text>
          </view>
        </view>
        <text class="arrow">›</text>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listClasses, joinClass } from '@/api/classroom.js'
import { listCatalogs, listWatchProgress } from '@/api/course.js'
import { chapterProgress } from '@/utils/progress.js'

const classes = ref([])
const courseCards = ref([])
const courseProgress = ref({})
const loading = ref(false)
const code = ref('')
const joining = ref(false)

// 邀请码加班仅学生可用（后端 join 接口为 IsStudent）
const isStudent = uni.getStorageSync('user')?.role === 'student'

async function loadProgress(ids) {
  const result = {}
  await Promise.all(ids.map(async (cid) => {
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
      rows.forEach((p) => { sum += chapterProgress(p).pct ?? 0 })
      result[cid] = Math.round(sum / chapters)
    } catch {
      result[cid] = null
    }
  }))
  courseProgress.value = result
}

async function load() {
  loading.value = true
  try {
    const data = await listClasses()
    classes.value = data.results ?? data
    const cards = []
    classes.value.forEach((item) => {
      const ids = item.courses?.length ? item.courses : [item.course]
      ids.filter(Boolean).forEach((id, index) => {
        cards.push({
          id: Number(id),
          classId: item.id,
          className: item.name,
          courseName: item.course_names?.[index] || item.course_name || `课程 ${id}`,
          status: item.status,
        })
      })
    })
    courseCards.value = cards
    const ids = [...new Set(cards.map((c) => c.id))]
    // 进度仅学生有意义；教师视角的 watch-progress 是全班学生记录，算出来是脏数据
    if (ids.length && isStudent) loadProgress(ids)
  } finally {
    loading.value = false
  }
}

async function join() {
  const c = code.value.trim()
  if (!c) {
    uni.showToast({ title: '请输入邀请码', icon: 'none' })
    return
  }
  joining.value = true
  try {
    await joinClass(c)
    uni.showToast({ title: '加入成功', icon: 'success' })
    code.value = ''
    load()
  } finally {
    joining.value = false
  }
}

function openCourse(c) {
  uni.navigateTo({
    url: `/pages/course/chapters?id=${c.id}&name=${encodeURIComponent(c.courseName)}`,
  })
}

onShow(load)
</script>

<style scoped>
.page {
  padding: 28rpx;
}

.join-bar {
  display: flex;
  gap: 16rpx;
  margin-bottom: 28rpx;
}

.join-input {
  flex: 1;
  height: 84rpx;
  padding: 0 26rpx;
  border-radius: 20rpx;
  background: #f1f5f9;
  border: 1rpx solid transparent;
  font-size: 26rpx;
  box-sizing: border-box;
}

.ph {
  color: #94a3b8;
}

.join-btn {
  width: 150rpx;
  height: 84rpx;
  line-height: 84rpx;
  border-radius: 20rpx;
  background: #2563eb;
  color: #ffffff;
  font-size: 26rpx;
  font-weight: 600;
}

.join-btn::after {
  border: none;
}

.tip {
  padding: 80rpx 0;
  text-align: center;
  font-size: 26rpx;
  color: #94a3b8;
}

.course-card {
  display: flex;
  align-items: center;
  gap: 22rpx;
  margin-bottom: 20rpx;
  padding: 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.05);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.course-card:active {
  transform: scale(0.98);
}

.course-icon {
  width: 84rpx;
  height: 84rpx;
  display: flex;
  flex: 0 0 84rpx;
  align-items: center;
  justify-content: center;
  border-radius: 20rpx;
  background: #eff6ff;
  font-size: 40rpx;
}

.course-main {
  flex: 1;
  min-width: 0;
}

.course-name {
  overflow: hidden;
  font-size: 30rpx;
  font-weight: 700;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-meta {
  display: flex;
  align-items: center;
  gap: 14rpx;
  margin-top: 10rpx;
}

.chip {
  padding: 4rpx 16rpx;
  border-radius: 999rpx;
  background: #f1f5f9;
  color: #64748b;
  font-size: 22rpx;
}

.status {
  padding: 4rpx 16rpx;
  border-radius: 999rpx;
  background: #f1f5f9;
  color: #94a3b8;
  font-size: 22rpx;
}

.status.open {
  background: #ecfdf5;
  color: #10b981;
}

.progress-row {
  display: flex;
  align-items: center;
  gap: 14rpx;
  margin-top: 14rpx;
}

.progress-track {
  flex: 1;
  height: 10rpx;
  overflow: hidden;
  border-radius: 999rpx;
  background: #f1f5f9;
}

.progress-fill {
  height: 100%;
  border-radius: 999rpx;
  background: #2563eb;
}

.progress-text {
  font-size: 22rpx;
  font-weight: 600;
  color: #64748b;
}

.arrow {
  flex-shrink: 0;
  font-size: 40rpx;
  color: #cbd5e1;
}
</style>
