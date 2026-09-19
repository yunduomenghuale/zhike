<template>
  <view class="page">
    <view class="course-head">{{ courseName }}</view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!items.length" class="tip">教师暂未发布课程资源</view>

      <template v-for="item in items" :key="`${item.type}-${item.id}`">
        <!-- 数字人视频：内嵌播放 -->
        <view v-if="item.type === 'video'" class="card">
          <video
            class="video"
            :src="mediaURL(item.file_url)"
            controls
            object-fit="contain"
            :poster="''"
          />
          <view class="card-main">
            <view class="card-title">{{ item.title }}</view>
            <view class="card-meta">
              <text class="chip video-chip">视频</text>
              <text v-if="item.catalog_title" class="meta-text">{{ item.catalog_title }}</text>
              <text class="meta-text">{{ fmtSize(item.file_size) }}</text>
            </view>
          </view>
        </view>

        <!-- 思维导图/交互演示：H5 内打开，小程序/ App 用 web-view -->
        <view class="card" @click="openResource(item)">
          <view class="res-icon">{{ item.kind === 'mindmap' ? '🗺️' : '🎬' }}</view>
          <view class="card-main">
            <view class="card-title">{{ item.title }}</view>
            <view class="card-meta">
              <text class="chip" :class="item.kind === 'mindmap' ? 'mind-chip' : 'demo-chip'">
                {{ item.kind_display }}
              </text>
              <text v-if="item.catalog_title" class="meta-text">{{ item.catalog_title }}</text>
            </view>
          </view>
          <text class="arrow">›</text>
        </view>
      </template>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { listCourseResources, listCourseVideos } from '@/api/course.js'
import { mediaURL, BASE_URL } from '@/config.js'

const courseId = ref(null)
const courseName = ref('课程资源')
const items = ref([])
const loading = ref(false)

onLoad((q) => {
  courseId.value = Number(q.id) || null
  if (q.name) courseName.value = decodeURIComponent(q.name)
  uni.setNavigationBarTitle({ title: courseName.value })
  load()
})

async function load() {
  if (!courseId.value) return
  loading.value = true
  try {
    const [resRes, vidRes] = await Promise.all([
      listCourseResources({ course: courseId.value }),
      listCourseVideos({ course: courseId.value }),
    ])
    const resources = (resRes.results ?? resRes ?? []).map((r) => ({ ...r, type: 'resource' }))
    const videos = (vidRes.results ?? vidRes ?? []).map((v) => ({ ...v, type: 'video' }))
    items.value = [...resources, ...videos]
  } finally {
    loading.value = false
  }
}

function openResource(item) {
  // 资源静态页挂在生产 nginx /resources/ 子路径（与 /api 同域）
  const url = `${BASE_URL}${item.url}`
  // #ifdef H5
  window.open(url, '_blank')
  // #endif
  // #ifndef H5
  uni.navigateTo({ url: `/pages/course/resource-viewer?url=${encodeURIComponent(url)}&title=${encodeURIComponent(item.title)}` })
  // #endif
}

function fmtSize(bytes) {
  if (!bytes) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = Number(bytes)
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i += 1
  }
  return `${n.toFixed(1)} ${units[i]}`
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
  padding: 100rpx 0;
  text-align: center;
  font-size: 26rpx;
  color: #94a3b8;
}

.card {
  display: flex;
  align-items: center;
  gap: 20rpx;
  margin-bottom: 18rpx;
  padding: 26rpx 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.04);
}

.card:active {
  transform: scale(0.98);
}

.video {
  width: 100%;
  height: 380rpx;
  border-radius: 14rpx;
  background: #000;
}

.card-main {
  flex: 1;
  min-width: 0;
}

.card-title {
  font-size: 28rpx;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 10rpx;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 14rpx;
  font-size: 22rpx;
  color: #94a3b8;
}

.chip {
  padding: 2rpx 14rpx;
  border-radius: 8rpx;
}

.mind-chip {
  background: #eff6ff;
  color: #2563eb;
}

.demo-chip {
  background: #ecfdf5;
  color: #10b981;
}

.video-chip {
  background: #f5f3ff;
  color: #8b5cf6;
}

.res-icon {
  font-size: 44rpx;
}

.arrow {
  color: #cbd5e1;
  font-size: 32rpx;
}
</style>
