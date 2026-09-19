<template>
  <div class="viewer-page">
    <header class="viewer-bar">
      <button type="button" class="vh-btn" @click="goBack">
        <el-icon><ArrowLeft /></el-icon>
        <span>返回课程</span>
      </button>
      <div class="vh-title" :title="title">{{ title }}</div>
      <div class="vh-actions">
        <el-tag v-if="kindLabel" size="small" effect="dark" :type="kind === 'mindmap' ? 'primary' : 'success'" class="vh-tag">
          {{ kindLabel }}
        </el-tag>
        <button type="button" class="vh-btn" @click="openInNewTab">
          <el-icon><FullScreen /></el-icon>
          <span>新窗口打开</span>
        </button>
      </div>
    </header>

    <div class="viewer-stage">
      <iframe
        v-if="src && type === 'html'"
        :src="src"
        class="viewer-frame"
        allow="fullscreen"
      />
      <video
        v-else-if="src && type === 'video'"
        :src="src"
        class="viewer-video"
        controls
        autoplay
        playsinline
      />
      <el-empty v-else description="资源地址无效" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, FullScreen } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const title = ref(route.query.title || '资源查看')
const type = ref(route.query.type === 'video' ? 'video' : 'html')
const kind = ref(route.query.kind || '')
const backName = ref(route.query.back || 'student-course-resources')
const backId = ref(route.params.id || null)

const src = computed(() => {
  const raw = route.query.src || ''
  // 只允许站内相对路径，防外链滥用
  return raw.startsWith('/') ? raw : ''
})

const kindLabel = computed(() =>
  kind.value === 'mindmap' ? '思维导图' : kind.value === 'demo' ? '交互演示' : kind.value === 'video' ? '视频' : '',
)

function goBack() {
  if (backId.value) router.push({ name: backName.value, params: { id: backId.value } })
  else router.back()
}

function openInNewTab() {
  if (src.value) window.open(src.value, '_blank')
}

onMounted(() => {
  document.title = `${title.value} - 智课平台`
})
</script>

<style scoped>
.viewer-page {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  background: #0b1220;
  color: #e2e8f0;
}

.viewer-bar {
  flex: 0 0 auto;
  height: 52px;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 18px;
  background: #0f172a;
  border-bottom: 1px solid #1e293b;
}

.vh-title {
  flex: 1;
  min-width: 0;
  font-size: 15px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vh-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.vh-tag {
  border: 0;
}

.vh-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 14px;
  border: 1px solid #334155;
  border-radius: 8px;
  background: transparent;
  color: #cbd5e1;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s;
  white-space: nowrap;
}

.vh-btn:hover {
  border-color: #38bdf8;
  color: #38bdf8;
}

.viewer-stage {
  flex: 1;
  min-height: 0;
  display: flex;
}

.viewer-frame {
  flex: 1;
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
}

.viewer-video {
  flex: 1;
  width: 100%;
  height: 100%;
  background: #000;
}
</style>
