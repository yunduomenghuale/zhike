<template>
  <view class="page">
    <AppHeader :title="courseName" back />
    <scroll-view class="scroll" scroll-y>
      <view class="content">
        <view class="course-summary">
          <view class="summary-icon"><uni-icons type="list" color="#2563eb" size="26" /></view>
          <view class="summary-copy"><view class="summary-label">课程章节</view><view class="summary-title">{{ courseName }}</view></view>
          <view class="summary-count">{{ rows.length }} 节</view>
        </view>

        <view class="hint"><uni-icons type="info" color="#64748b" size="17" /><text>进入章节后可查看讲解、向 AI 助教提问并阅读相关资料</text></view>
        <view v-if="loading" class="loading">正在加载章节…</view>
        <EmptyState v-else-if="!rows.length" icon="folder-add" title="暂无已发布章节" description="教师发布章节后会显示在这里" />

        <view v-else class="chapters">
          <view v-for="(row, index) in rows" :key="row.node.id" class="chapter" :class="{ child: row.child }" hover-class="chapter-tap" @click="open(row.node)">
            <view class="chapter-index">{{ String(index + 1).padStart(2, '0') }}</view>
            <view class="chapter-copy">
              <view class="chapter-type">{{ row.child ? '小节' : '章节' }}</view>
              <view class="chapter-title">{{ row.node.title }}</view>
              <view class="chapter-tools"><text>AI 助教</text><text>相关资料</text><text>章节讲解</text></view>
            </view>
            <view class="open"><uni-icons type="right" color="#2563eb" size="14" /></view>
          </view>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import { listCatalogs } from '@/api/courses.js'

const courseId = ref(null)
const courseName = ref('课程学习')
const rows = ref([])
const loading = ref(false)

onLoad((query) => {
  courseId.value = Number(query.course) || null
  if (query.name) courseName.value = decodeURIComponent(query.name)
  load()
})

async function load() {
  if (!courseId.value) return
  loading.value = true
  try {
    const data = await listCatalogs({ course: courseId.value, tree: 1 })
    const result = []
    ;(data.results ?? data).forEach((node) => {
      result.push({ node, child: false })
      ;(node.children || []).forEach((child) => result.push({ node: child, child: true }))
    })
    rows.value = result
  } finally { loading.value = false }
}

function open(node) {
  uni.navigateTo({ url: `/pages/course/lecture?course=${courseId.value}&catalog=${node.id}&title=${encodeURIComponent(node.title)}` })
}
</script>

<style scoped lang="scss">
.page { min-height: 100vh; }
.scroll { height: calc(100vh - var(--app-safe-top) - 92rpx); }
.content { padding: 26rpx 28rpx 55rpx; }
.course-summary { position: relative; overflow: hidden; display: flex; align-items: center; gap: 18rpx; padding: 27rpx; border: 1rpx solid rgba(37, 99, 235, .1); border-radius: 29rpx; background: linear-gradient(135deg, #edf5ff, #fff); box-shadow: $shadow-card; }
.summary-icon { width: 76rpx; height: 76rpx; display: flex; align-items: center; justify-content: center; border-radius: 23rpx; background: #fff; }
.summary-copy { min-width: 0; flex: 1; }
.summary-label { color: $brand; font-size: 19rpx; font-weight: 700; }
.summary-title { margin-top: 6rpx; overflow: hidden; color: $text-main; font-size: 28rpx; font-weight: 850; text-overflow: ellipsis; white-space: nowrap; }
.summary-count { color: $text-sub; font-size: 20rpx; }
.hint { display: flex; align-items: flex-start; gap: 12rpx; margin: 24rpx 2rpx 30rpx; padding: 20rpx 22rpx; border-radius: 21rpx; background: #eef2f7; color: $text-sub; font-size: 20rpx; line-height: 1.55; }
.chapters { position: relative; }
.chapter { display: flex; align-items: center; gap: 18rpx; margin-bottom: 18rpx; padding: 25rpx; border: 1rpx solid rgba(37, 99, 235, .075); border-radius: 27rpx; background: #fff; box-shadow: 0 8rpx 25rpx rgba(15, 23, 42, .04); }
.chapter.child { margin-left: 34rpx; }
.chapter-index { width: 60rpx; height: 60rpx; flex: 0 0 60rpx; border-radius: 19rpx; background: $brand-soft; color: $brand; font-size: 23rpx; font-weight: 800; line-height: 60rpx; text-align: center; }
.chapter.child .chapter-index { background: #f1f5f9; color: $text-sub; }
.chapter-copy { min-width: 0; flex: 1; }
.chapter-type { color: $text-light; font-size: 18rpx; }
.chapter-title { margin-top: 5rpx; overflow: hidden; color: $text-main; font-size: 25rpx; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.chapter-tools { display: flex; gap: 12rpx; margin-top: 10rpx; overflow: hidden; color: $text-light; font-size: 17rpx; white-space: nowrap; }
.open { width: 48rpx; height: 48rpx; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: $brand-soft; }
.chapter-tap { opacity: .68; transform: scale(.985); }
.loading { padding: 90rpx; color: $text-light; font-size: 23rpx; text-align: center; }
</style>
