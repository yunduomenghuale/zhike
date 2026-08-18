<template>
  <view class="page">
    <view class="course-head">{{ courseName }}</view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">暂无已发布章节</view>
      <view
        v-for="row in rows"
        :key="row.node.id"
        class="chapter"
        :class="{ child: row.isChild }"
        @click="open(row.node)"
      >
        <view class="chapter-icon" :class="{ child: row.isChild }">
          {{ row.isChild ? '📄' : '📁' }}
        </view>
        <view class="chapter-main">
          <view class="chapter-title">{{ row.node.title }}</view>
          <text v-if="progressInfo(row.node.id).label" class="tag" :class="progressInfo(row.node.id).type">
            {{ progressInfo(row.node.id).label }}
          </text>
        </view>
        <button class="practice-btn" @click.stop="openPractice(row.node)">练习</button>
        <text class="arrow">›</text>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { listCatalogs, listWatchProgress } from '@/api/course.js'
import { chapterProgress } from '@/utils/progress.js'

const courseId = ref(null)
const courseName = ref('课程学习')
const tree = ref([])
const rows = ref([])
const progressMap = ref({})
const loading = ref(false)

// 学习进度仅学生有意义；教师视角的 watch-progress 是全班学生记录
const isStudent = uni.getStorageSync('user')?.role === 'student'

onLoad((q) => {
  courseId.value = Number(q.id) || null
  if (q.name) courseName.value = decodeURIComponent(q.name)
  uni.setNavigationBarTitle({ title: courseName.value })
  load()
})

function progressInfo(catalogId) {
  return chapterProgress(progressMap.value[catalogId])
}

async function load() {
  if (!courseId.value) return
  loading.value = true
  try {
    const [cats, progress] = await Promise.all([
      listCatalogs({ course: courseId.value, tree: 1 }),
      isStudent ? listWatchProgress({ course: courseId.value }) : Promise.resolve([]),
    ])
    tree.value = cats.results ?? cats
    const map = {}
    ;(progress.results ?? progress).forEach((p) => { map[p.catalog] = p })
    progressMap.value = map
    const flat = []
    for (const n of tree.value) {
      flat.push({ node: n, isChild: false })
      for (const c of n.children || []) flat.push({ node: c, isChild: true })
    }
    rows.value = flat
  } finally {
    loading.value = false
  }
}

function open(node) {
  uni.navigateTo({
    url: `/pages/course/lecture?catalog=${node.id}&title=${encodeURIComponent(node.title)}&course=${encodeURIComponent(courseName.value)}`,
  })
}

function openPractice(node) {
  uni.navigateTo({
    url: `/pages/course/practice?course=${courseId.value}&catalog=${node.id}&title=${encodeURIComponent(node.title)}`,
  })
}
</script>

<style scoped>
.page {
  padding: 28rpx;
}

.course-head {
  margin-bottom: 24rpx;
  font-size: 34rpx;
  font-weight: 800;
  color: #0f172a;
}

.tip {
  padding: 80rpx 0;
  text-align: center;
  font-size: 26rpx;
  color: #94a3b8;
}

.chapter {
  display: flex;
  align-items: center;
  gap: 20rpx;
  margin-bottom: 18rpx;
  padding: 26rpx 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.04);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.chapter.child {
  margin-left: 48rpx;
}

.chapter:active {
  transform: scale(0.98);
}

.chapter-icon {
  width: 64rpx;
  height: 64rpx;
  display: flex;
  flex: 0 0 64rpx;
  align-items: center;
  justify-content: center;
  border-radius: 16rpx;
  background: #eff6ff;
  font-size: 32rpx;
}

.chapter-icon.child {
  width: 56rpx;
  height: 56rpx;
  flex-basis: 56rpx;
  background: #f1f5f9;
  font-size: 28rpx;
}

.chapter-main {
  flex: 1;
  min-width: 0;
}

.chapter-title {
  overflow: hidden;
  font-size: 28rpx;
  font-weight: 600;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag {
  display: inline-flex;
  margin-top: 8rpx;
  padding: 2rpx 14rpx;
  border-radius: 999rpx;
  font-size: 20rpx;
  background: #f1f5f9;
  color: #94a3b8;
}

.tag.warning {
  background: #fff7ed;
  color: #d97706;
}

.tag.success {
  background: #ecfdf5;
  color: #10b981;
}

.practice-btn {
  flex-shrink: 0;
  height: 52rpx;
  line-height: 52rpx;
  padding: 0 24rpx;
  border-radius: 999rpx;
  background: #eff6ff;
  color: #2563eb;
  font-size: 22rpx;
  font-weight: 700;
}

.practice-btn::after {
  border: none;
}

.arrow {
  flex-shrink: 0;
  font-size: 38rpx;
  color: #cbd5e1;
}
</style>
