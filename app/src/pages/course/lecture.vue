<template>
  <view class="page">
    <AppHeader :title="title" back />
    <view class="tabs">
      <view v-for="item in tabs" :key="item.key" class="tab" :class="{ active: activeTab === item.key }" @click="switchTab(item.key)">
        <uni-icons :type="item.icon" :color="activeTab === item.key ? '#2563eb' : '#94a3b8'" size="17" />
        <text>{{ item.label }}</text>
      </view>
    </view>

    <scroll-view class="scroll" scroll-y :scroll-into-view="chatAnchor" scroll-with-animation>
      <view class="content">
        <view v-if="activeTab === 'lecture'">
          <view v-if="loading" class="loading">正在加载讲解…</view>
          <EmptyState v-else-if="!pages.length" icon="videocam" title="本章暂无课件" description="教师上传并发布课件后可开始学习" />
          <template v-else>
            <view class="stage" @click="previewCurrent">
              <image v-if="currentPage?.image || currentPage?.image_url" class="slide-image" :src="mediaUrl(currentPage.image || currentPage.image_url)" mode="widthFix" />
              <view v-else class="slide-text"><view class="slide-title">{{ currentPage?.title || `第 ${pageIndex + 1} 页` }}</view><view class="slide-body">{{ currentPage?.body || '本页暂无文本内容' }}</view></view>
              <view class="page-count">{{ pageIndex + 1 }} / {{ pages.length }}</view>
            </view>
            <view class="page-controls">
              <button class="control" :disabled="pageIndex === 0" @click="pageIndex--"><uni-icons type="left" color="currentColor" size="15" />上一页</button>
              <view class="progress"><view class="progress-fill" :style="{ width: `${((pageIndex + 1) / pages.length) * 100}%` }"></view></view>
              <button class="control" :disabled="pageIndex >= pages.length - 1" @click="pageIndex++">下一页<uni-icons type="right" color="currentColor" size="15" /></button>
            </view>
            <view v-if="currentScript?.script" class="script-card">
              <view class="script-head"><view class="script-icon"><uni-icons type="compose" color="#2563eb" size="18" /></view><view><view class="script-title">讲解稿</view><view class="script-subtitle">第 {{ pageIndex + 1 }} 页配套讲解</view></view></view>
              <view class="script-text">{{ currentScript.script }}</view>
            </view>
          </template>
        </view>

        <view v-else-if="activeTab === 'ai'">
          <view class="intro ai-intro">
            <view class="intro-icon ai-icon"><uni-icons type="chatbubble" color="#6366f1" size="24" /></view>
            <view class="intro-copy"><view class="intro-title">本章 AI 助教</view><view class="intro-desc">基于本章课件、讲解稿和课程知识库回答</view></view>
          </view>
          <view v-if="!messages.length" class="suggestions">
            <view class="suggest-label">试试这样问</view>
            <view v-for="question in suggests" :key="question" class="suggest" hover-class="tap" @click="ask(question)"><text>{{ question }}</text><uni-icons type="right" color="#94a3b8" size="13" /></view>
          </view>
          <view v-else class="messages">
            <view v-for="(message, index) in messages" :key="index" class="message" :class="message.role">
              <view class="bubble">
                <view class="message-text">{{ message.content }}</view>
                <view v-if="message.cited?.length" class="sources"><view class="sources-title">参考来源</view><view v-for="(source, sourceIndex) in message.cited" :key="sourceIndex" class="source">{{ source.material_name || '课程资料' }}{{ source.page ? ` · P${source.page}` : '' }}</view></view>
              </view>
            </view>
            <view v-if="asking" class="message assistant"><view class="bubble thinking">正在检索本章资料…</view></view>
            <view id="chat-bottom" class="anchor"></view>
          </view>
        </view>

        <view v-else>
          <view class="intro">
            <view class="intro-icon material-icon"><uni-icons type="folder-add" color="#2563eb" size="24" /></view>
            <view class="intro-copy"><view class="intro-title">相关资料</view><view class="intro-desc">教师上传的课程文档与知识库资料</view></view>
          </view>
          <view v-if="materialsLoading" class="loading">正在加载资料…</view>
          <EmptyState v-else-if="!materials.length" icon="folder-add" title="暂无相关资料" description="老师上传后会显示在这里" />
          <view v-else class="material-list">
            <view v-for="material in materials" :key="material.id" class="material-row" hover-class="tap" @click="openMaterial(material)">
              <view class="file-icon"><uni-icons type="paperclip" color="#2563eb" size="20" /></view>
              <view class="file-copy"><view class="file-name">{{ material.file_name }}</view><view class="file-meta">{{ (material.file_type || '文件').toUpperCase() }} · {{ material.chunk_count || 0 }} 个知识片段</view></view>
              <view class="file-status" :class="material.parse_status">{{ material.parse_status_display || '已上传' }}</view>
              <uni-icons type="right" color="#cbd5e1" size="14" />
            </view>
          </view>
        </view>
      </view>
    </scroll-view>

    <view v-if="activeTab === 'ai'" class="input-shell">
      <view class="input-bar">
        <input v-model="questionInput" class="question-input" placeholder="就本章内容提问…" placeholder-class="placeholder" confirm-type="send" :disabled="asking" @confirm="ask()" />
        <button class="send" :disabled="asking || !questionInput.trim()" :loading="asking" @click="ask()"><uni-icons type="paperplane" color="#fff" size="20" /></button>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import AppHeader from '@/components/AppHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import { listPpts, listVideos } from '@/api/courses.js'
import { askQuestion, listMaterials } from '@/api/knowledge.js'
import { mediaUrl } from '@/config.js'

const tabs = [
  { key: 'lecture', label: '章节讲解', icon: 'videocam' },
  { key: 'ai', label: 'AI 助教', icon: 'chatbubble' },
  { key: 'materials', label: '相关资料', icon: 'folder-add' },
]
const activeTab = ref('lecture')
const courseId = ref(null)
const catalogId = ref(null)
const title = ref('章节学习')
const pages = ref([])
const scripts = ref([])
const pageIndex = ref(0)
const loading = ref(false)
const materials = ref([])
const materialsLoading = ref(false)
const materialsLoaded = ref(false)
const messages = ref([])
const questionInput = ref('')
const asking = ref(false)
const chatAnchor = ref('')
const session = `app-chapter-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
const suggests = ['这一章的重点是什么？', '帮我总结本章核心概念', '这部分可以举个例子吗？']
const currentPage = computed(() => pages.value[pageIndex.value])
const currentScript = computed(() => scripts.value.find((item) => item.page === currentPage.value?.page))

onLoad((query) => {
  courseId.value = Number(query.course) || null
  catalogId.value = Number(query.catalog) || null
  if (query.title) title.value = decodeURIComponent(query.title)
  loadLecture()
})

async function loadLecture() {
  if (!catalogId.value) return
  loading.value = true
  try {
    const [pptData, videoData] = await Promise.all([listPpts({ catalog: catalogId.value }), listVideos({ catalog: catalogId.value })])
    const ppts = pptData.results ?? pptData
    const ppt = ppts.find((item) => item.is_active) || ppts[0]
    pages.value = ppt?.parsed_pages || []
    scripts.value = (videoData.results ?? videoData)[0]?.scripts || []
  } finally { loading.value = false }
}

function switchTab(key) {
  activeTab.value = key
  if (key === 'materials') loadMaterials()
}

async function loadMaterials() {
  if (materialsLoaded.value || !courseId.value) return
  materialsLoading.value = true
  try {
    const data = await listMaterials({ course: courseId.value })
    materials.value = data.results ?? data
    materialsLoaded.value = true
  } finally { materialsLoading.value = false }
}

async function ask(preset) {
  const question = String(preset ?? questionInput.value).trim()
  if (!question || asking.value) return
  questionInput.value = ''
  messages.value.push({ role: 'user', content: question })
  asking.value = true
  scrollBottom()
  try {
    const record = await askQuestion({ course: courseId.value, catalog: catalogId.value, question, session })
    messages.value.push({ role: 'assistant', content: record.answer || '（暂无回答）', cited: record.cited_chunks || [] })
  } catch {
    messages.value.push({ role: 'assistant', content: 'AI 助教暂时没有响应，请稍后再试。' })
  } finally { asking.value = false; scrollBottom() }
}

function scrollBottom() { nextTick(() => { chatAnchor.value = ''; nextTick(() => { chatAnchor.value = 'chat-bottom' }) }) }
function previewCurrent() {
  const images = pages.value.map((item) => item.image || item.image_url).filter(Boolean).map(mediaUrl)
  if (!images.length) return
  uni.previewImage({ current: mediaUrl(currentPage.value.image || currentPage.value.image_url), urls: images })
}

function openMaterial(material) {
  if (!material.file) return uni.showToast({ title: '该资料暂无文件', icon: 'none' })
  uni.showLoading({ title: '正在打开' })
  uni.downloadFile({
    url: mediaUrl(material.file),
    success: ({ statusCode, tempFilePath }) => {
      if (statusCode !== 200) return uni.showToast({ title: '资料下载失败', icon: 'none' })
      uni.openDocument({ filePath: tempFilePath, showMenu: true, fail: () => uni.showToast({ title: '无法打开该文件', icon: 'none' }) })
    },
    fail: () => uni.showToast({ title: '资料下载失败', icon: 'none' }),
    complete: () => uni.hideLoading(),
  })
}
</script>

<style scoped lang="scss">
.page { min-height: 100vh; }
.tabs { position: relative; z-index: 8; display: flex; gap: 6rpx; margin: 14rpx 28rpx 0; padding: 8rpx; border: 1rpx solid $line; border-radius: 23rpx; background: #eef2f7; }
.tab { min-width: 0; height: 70rpx; flex: 1; display: flex; align-items: center; justify-content: center; gap: 8rpx; border-radius: 18rpx; color: $text-sub; font-size: 21rpx; font-weight: 650; }
.tab.active { background: #fff; color: $brand; font-weight: 750; box-shadow: 0 6rpx 18rpx rgba(15, 23, 42, .07); }
.scroll { height: calc(100vh - var(--app-safe-top) - 200rpx); }
.content { padding: 26rpx 28rpx 48rpx; }
.stage { position: relative; overflow: hidden; min-height: 360rpx; border: 1rpx solid $line; border-radius: 27rpx; background: #fff; box-shadow: $shadow-card; }
.slide-image { display: block; width: 100%; }
.slide-text { padding: 62rpx 36rpx; }
.slide-title { color: $text-main; font-size: 32rpx; font-weight: 850; text-align: center; }
.slide-body { margin-top: 22rpx; color: $text-sub; font-size: 25rpx; line-height: 1.75; white-space: pre-wrap; }
.page-count { position: absolute; top: 18rpx; right: 20rpx; padding: 6rpx 15rpx; border-radius: 999rpx; background: rgba(15, 23, 42, .72); color: #fff; font-size: 19rpx; }
.page-controls { display: flex; align-items: center; gap: 16rpx; margin: 20rpx 0; }
.control { height: 70rpx; display: flex; align-items: center; justify-content: center; gap: 5rpx; padding: 0 20rpx; border: 1rpx solid $line; border-radius: 19rpx; background: #fff; color: $text-main; font-size: 21rpx; }
.control[disabled] { color: #cbd5e1; background: #f8fafc; }
.progress { min-width: 80rpx; height: 8rpx; flex: 1; overflow: hidden; border-radius: 999rpx; background: #e2e8f0; }
.progress-fill { height: 100%; border-radius: inherit; background: $brand; }
.script-card { margin-top: 22rpx; padding: 27rpx; border: 1rpx solid $line; border-radius: 27rpx; background: #fff; }
.script-head { display: flex; align-items: center; gap: 14rpx; }
.script-icon { width: 58rpx; height: 58rpx; display: flex; align-items: center; justify-content: center; border-radius: 17rpx; background: $brand-soft; }
.script-title { color: $text-main; font-size: 24rpx; font-weight: 800; }
.script-subtitle { margin-top: 3rpx; color: $text-light; font-size: 18rpx; }
.script-text { margin-top: 20rpx; color: $text-sub; font-size: 25rpx; line-height: 1.8; white-space: pre-wrap; }
.intro { display: flex; align-items: center; gap: 19rpx; padding: 26rpx; border: 1rpx solid rgba(37, 99, 235, .08); border-radius: 27rpx; background: #fff; box-shadow: 0 8rpx 25rpx rgba(15, 23, 42, .04); }
.ai-intro { background: linear-gradient(135deg, #f4f1ff, #fff 75%); }
.intro-icon { width: 74rpx; height: 74rpx; display: flex; align-items: center; justify-content: center; border-radius: 22rpx; }
.ai-icon { background: #ede9fe; }
.material-icon { background: $brand-soft; }
.intro-copy { min-width: 0; flex: 1; }
.intro-title { color: $text-main; font-size: 27rpx; font-weight: 850; }
.intro-desc { margin-top: 6rpx; color: $text-sub; font-size: 20rpx; line-height: 1.5; }
.suggestions { margin-top: 30rpx; }
.suggest-label { margin: 0 5rpx 14rpx; color: $text-light; font-size: 20rpx; font-weight: 650; }
.suggest { min-height: 84rpx; display: flex; align-items: center; justify-content: space-between; gap: 15rpx; margin-bottom: 13rpx; padding: 0 23rpx; border: 1rpx solid $line; border-radius: 21rpx; background: #fff; color: #334155; font-size: 23rpx; }
.messages { margin-top: 28rpx; padding-bottom: 100rpx; }
.message { display: flex; margin-bottom: 19rpx; }
.message.user { justify-content: flex-end; }
.bubble { max-width: 85%; padding: 20rpx 23rpx; border: 1rpx solid $line; border-radius: 22rpx 22rpx 22rpx 7rpx; background: #fff; }
.message.user .bubble { border: 0; border-radius: 22rpx 22rpx 7rpx 22rpx; background: $brand; }
.message-text { color: #334155; font-size: 24rpx; line-height: 1.72; white-space: pre-wrap; word-break: break-word; }
.message.user .message-text { color: #fff; }
.thinking { color: $text-light; font-size: 22rpx; }
.sources { margin-top: 14rpx; padding-top: 12rpx; border-top: 1rpx solid $line; }
.sources-title { color: $brand; font-size: 19rpx; font-weight: 750; }
.source { margin-top: 6rpx; color: $text-sub; font-size: 19rpx; }
.anchor { height: 8rpx; }
.input-shell { position: fixed; z-index: 20; left: 0; right: 0; bottom: 0; padding: 13rpx 28rpx calc(13rpx + env(safe-area-inset-bottom)); border-top: 1rpx solid $line; background: rgba(246, 248, 252, .97); }
.input-bar { display: flex; gap: 13rpx; }
.question-input { min-width: 0; height: 84rpx; flex: 1; padding: 0 23rpx; border: 1rpx solid #dbe3ee; border-radius: 22rpx; background: #fff; color: $text-main; font-size: 24rpx; }
.placeholder { color: $text-light; }
.send { width: 84rpx; height: 84rpx; display: flex; align-items: center; justify-content: center; border-radius: 22rpx; background: $brand; }
.send[disabled] { background: #bfdbfe; }
.material-list { overflow: hidden; margin-top: 24rpx; padding: 0 23rpx; border: 1rpx solid $line; border-radius: 27rpx; background: #fff; }
.material-row { min-height: 120rpx; display: flex; align-items: center; gap: 16rpx; border-bottom: 1rpx solid $line; }
.material-row:last-child { border-bottom: 0; }
.file-icon { width: 62rpx; height: 62rpx; display: flex; align-items: center; justify-content: center; border-radius: 19rpx; background: $brand-soft; }
.file-copy { min-width: 0; flex: 1; }
.file-name { overflow: hidden; color: $text-main; font-size: 23rpx; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.file-meta { margin-top: 6rpx; color: $text-light; font-size: 18rpx; }
.file-status { flex-shrink: 0; padding: 4rpx 10rpx; border-radius: 999rpx; background: #f1f5f9; color: $text-sub; font-size: 17rpx; }
.file-status.done { background: #ecfdf5; color: #059669; }
.loading { padding: 95rpx 20rpx; color: $text-light; font-size: 23rpx; text-align: center; }
.tap { opacity: .62; transform: scale(.98); }
</style>
