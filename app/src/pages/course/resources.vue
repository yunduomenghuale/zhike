<template>
  <view class="page">
    <view class="course-head">{{ courseName }}</view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!items.length" class="tip">教师暂未发布课程资源</view>

      <template v-for="item in items" :key="`${item.type}-${item.id}`">
        <!-- 思维导图/交互演示：H5 内打开，小程序/ App 用 web-view -->
        <view v-if="item.kind !== 'document'" class="card" @click="openResource(item)">
          <view class="res-icon">{{ item.kind === 'mindmap' ? '🗺️' : '🎬' }}</view>
          <view class="card-main">
            <view class="card-title">{{ item.title }}</view>
            <view class="card-meta">
              <text class="chip" :class="item.kind === 'mindmap' ? 'mind-chip' : 'demo-chip'">
                {{ item.kind_display }}
              </text>
            </view>
          </view>
          <text class="arrow">›</text>
        </view>

        <!-- 文档：签名后打开（PDF 预览，doc/docx 下载） -->
        <view v-else class="card" @click="openDocument(item)">
          <view class="res-icon">📄</view>
          <view class="card-main">
            <view class="card-title">{{ item.title }}</view>
            <view class="card-meta">
              <text class="chip doc-chip">文档</text>
              <text v-if="item.file_name" class="meta-text">{{ item.file_name }}</text>
              <text v-if="item.file_size" class="meta-text">{{ fmtSize(item.file_size) }}</text>
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
import { listCourseResources, signCourseResource } from '@/api/course.js'
import { BASE_URL } from '@/config.js'

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
    const res = await listCourseResources({ course: courseId.value })
    items.value = res.results ?? res ?? []
  } finally {
    loading.value = false
  }
}

function openUrl(url, title) {
  // #ifdef H5
  window.open(url, '_blank')
  // #endif
  // #ifndef H5
  uni.navigateTo({ url: `/pages/course/resource-viewer?url=${encodeURIComponent(url)}&title=${encodeURIComponent(title)}` })
  // #endif
}

async function openResource(item) {
  // 预置页：先签发唯一签名 URL（未发布/非在读课程后端拒签）
  try {
    const signed = await signCourseResource(item.id)
    openUrl(`${BASE_URL}${signed.url}`, item.title)
  } catch (e) {
    uni.showToast({ title: '资源打开失败', icon: 'none' })
  }
}

async function openDocument(item) {
  // 文档：签发 file 地址（PDF 内联预览，doc/docx 附件下载）
  try {
    const signed = await signCourseResource(item.id)
    openUrl(`${BASE_URL}${signed.url}`, item.title)
  } catch (e) {
    uni.showToast({ title: '文档打开失败', icon: 'none' })
  }
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

.doc-chip {
  background: #fff7ed;
  color: #ea580c;
}

.res-icon {
  font-size: 44rpx;
}

.arrow {
  color: #cbd5e1;
  font-size: 32rpx;
}
</style>
