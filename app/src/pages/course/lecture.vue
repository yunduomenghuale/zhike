<template>
  <view class="page">
    <view v-if="loading" class="tip">加载中…</view>
    <template v-else-if="pages.length">
      <!-- 课件区 -->
      <view class="stage" @click="preview">
        <image
          v-if="current?.image || current?.image_url"
          class="stage-image"
          :src="mediaURL(current.image || current.image_url)"
          mode="widthFix"
        />
        <view v-else class="stage-text">
          <view class="stage-title">{{ current?.title || `第 ${index + 1} 页` }}</view>
          <view class="stage-body">{{ current?.body || '本页暂无文本内容' }}</view>
        </view>
        <view class="stage-count">{{ index + 1 }} / {{ pages.length }}</view>
      </view>

      <!-- 控制条 -->
      <view class="controls">
        <button class="nav-btn" :disabled="index === 0" @click="goPrev">上一页</button>
        <button
          v-if="hasAnyAudio"
          class="play-btn"
          @click="toggleAudio"
        >
          {{ playing ? '⏸ 暂停' : '▶ 连播' }}
        </button>
        <text v-else class="no-audio">本章无配音</text>
        <button class="nav-btn" :disabled="index >= pages.length - 1" @click="goNext">下一页</button>
      </view>

      <!-- 播放进度 -->
      <view v-if="currentAudio" class="audio-bar">
        <text class="audio-time">{{ fmtTime(currentTime) }}</text>
        <view class="audio-track">
          <view class="audio-fill" :style="{ width: playPct + '%' }"></view>
        </view>
        <text class="audio-time">{{ fmtTime(duration) }}</text>
      </view>
      <view v-if="currentAudio" class="audio-hint">
        {{ playing ? '正在连播，配音结束自动翻页' : '点击「连播」从本页配音开始学习' }}
      </view>

      <!-- 讲解稿 -->
      <view v-if="currentScript?.script" class="script">
        <view class="script-label">讲解稿</view>
        <view class="script-text">{{ currentScript.script }}</view>
      </view>
    </template>
    <view v-else class="tip">本章节还没有可学习的课件</view>
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onHide, onLoad, onUnload } from '@dcloudio/uni-app'
import { listPpts, listVideos, listWatchProgress, reportVideoProgress } from '@/api/course.js'
import { mediaURL } from '@/config.js'

const catalogId = ref(null)
const title = ref('课件学习')
const pages = ref([])
const scripts = ref([])
const index = ref(0)
const loading = ref(false)

const current = computed(() => pages.value[index.value])
const currentScript = computed(() =>
  scripts.value.find((s) => s.page === current.value?.page),
)
const currentAudio = computed(() => {
  const url = currentScript.value?.audio_url
  return url ? mediaURL(url) : ''
})
const hasAnyAudio = computed(() => scripts.value.some((s) => s?.audio_url))

onLoad((q) => {
  catalogId.value = Number(q.catalog) || null
  if (q.title) title.value = decodeURIComponent(q.title)
  uni.setNavigationBarTitle({ title: title.value })
  load()
})

async function load() {
  if (!catalogId.value) return
  loading.value = true
  try {
    const [ppts, videos] = await Promise.all([
      listPpts({ catalog: catalogId.value }),
      listVideos({ catalog: catalogId.value }),
    ])
    const pptList = ppts.results ?? ppts
    const active = pptList.find((p) => p.is_active) || pptList[0]
    pages.value = active?.parsed_pages || []
    const videoList = videos.results ?? videos
    const video = videoList[0] || null
    scripts.value = video?.scripts || []
    videoId.value = video?.id || null
    await restoreProgress()
  } finally {
    loading.value = false
  }
}

// ---- 学习进度（与 web 端 Learning.vue 规则一致）----
// 进度上报接口仅学生可用（IsStudent），教师等角色浏览课件时不上报
const isStudent = uni.getStorageSync('user')?.role === 'student'
const videoId = ref(null)
const pageDurations = ref({}) // 页索引 -> 音频时长（秒）
const pageWatched = ref({}) // 页索引 -> 最大观看位置（秒）
let watchAccum = 0 // 距上次上报累计观看秒数
let lastTickTime = -1
let progressTimer = null
let resumePending = false
let resumePosition = 0

/** 断点续播：读取该视频的历史进度，恢复页码与页内位置 */
async function restoreProgress() {
  if (!isStudent || !videoId.value || !pages.value.length) return
  try {
    const data = await listWatchProgress({ video: videoId.value })
    const saved = (data.results ?? data)[0]
    if (!saved) return
    pageDurations.value = { ...(saved.page_durations || {}) }
    pageWatched.value = { ...(saved.page_watched || {}) }
    if (saved.status !== 'completed') {
      index.value = Math.min(saved.last_page || 0, pages.value.length - 1)
      resumePosition = Number(saved.last_position) || 0
      resumePending = resumePosition > 0
      if (saved.last_page) {
        uni.showToast({ title: `已从第 ${index.value + 1} 页继续学习`, icon: 'none' })
      }
    }
  } catch {
    // 进度读取失败不影响学习
  }
}

async function flushProgress(completed = false) {
  if (!videoId.value || !isStudent) {
    watchAccum = 0
    return
  }
  const delta = Math.round(watchAccum)
  watchAccum = 0
  const payload = {
    last_page: index.value,
    last_position: Math.round(currentTime.value * 10) / 10,
    duration_delta: delta,
    completed,
    page_count: pages.value.length,
  }
  if (Object.keys(pageDurations.value).length) payload.page_durations = pageDurations.value
  if (Object.keys(pageWatched.value).length) payload.page_watched = pageWatched.value
  try {
    await reportVideoProgress(videoId.value, payload)
  } catch {
    // 进度上报失败不打断学习
  }
}

function startProgressTimer() {
  stopProgressTimer()
  if (!isStudent) return
  progressTimer = setInterval(() => {
    if (playing.value) flushProgress()
  }, 10000)
}

function stopProgressTimer() {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
}

function fmtTime(sec) {
  const value = Number.isFinite(sec) ? Math.floor(sec) : 0
  const min = Math.floor(value / 60)
  const second = String(value % 60).padStart(2, '0')
  return `${min}:${second}`
}

function preview() {
  const url = current.value?.image || current.value?.image_url
  if (!url) return
  uni.previewImage({
    current: mediaURL(url),
    urls: pages.value.filter((p) => p.image || p.image_url).map((p) => mediaURL(p.image || p.image_url)),
  })
}

// ---- 配音连播 ----
let audioCtx = null
const playing = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const playPct = computed(() =>
  duration.value > 0 ? Math.min(100, Math.max(0, (currentTime.value / duration.value) * 100)) : 0,
)

/** 从 from 之后找下一页有配音的页 */
function findNextAudioPage(from) {
  for (let i = from + 1; i < pages.value.length; i += 1) {
    const page = pages.value[i]?.page
    if (scripts.value.some((s) => s.page === page && s.audio_url)) return i
  }
  return -1
}

function destroyAudio() {
  if (audioCtx) {
    audioCtx.stop()
    audioCtx.destroy()
    audioCtx = null
  }
  playing.value = false
}

/** 播放指定页的配音（连播主入口） */
function playPage(i) {
  const page = pages.value[i]
  const script = scripts.value.find((s) => s.page === page?.page)
  if (!script?.audio_url) return
  destroyAudio()
  currentTime.value = 0
  duration.value = 0
  lastTickTime = -1

  audioCtx = uni.createInnerAudioContext()
  audioCtx.src = mediaURL(script.audio_url)

  audioCtx.onCanplay(() => {
    const d = audioCtx.duration
    if (d > 0 && Number.isFinite(d)) {
      duration.value = d
      pageDurations.value = { ...pageDurations.value, [i]: Math.round(d * 10) / 10 }
    }
    // 断点续播：恢复页内播放位置
    if (resumePending && i === index.value) {
      resumePending = false
      if (resumePosition > 0 && resumePosition < (d || Infinity)) {
        audioCtx.seek(resumePosition)
        currentTime.value = resumePosition
        lastTickTime = resumePosition
      }
    }
  })

  audioCtx.onTimeUpdate(() => {
    const now = audioCtx.currentTime || 0
    // 正常播放累加学习时长；拖动/跳转产生的跳变不计入
    if (lastTickTime >= 0) {
      const delta = now - lastTickTime
      if (delta > 0 && delta <= 2) watchAccum += delta
    }
    lastTickTime = now
    currentTime.value = now
    // 每页已看时长取最大观看位置，未播放的页不计入
    if (now > (pageWatched.value[i] || 0)) {
      pageWatched.value = { ...pageWatched.value, [i]: Math.round(now * 10) / 10 }
    }
  })

  audioCtx.onPlay(() => { playing.value = true })
  audioCtx.onPause(() => { playing.value = false })

  audioCtx.onEnded(async () => {
    playing.value = false
    await flushProgress()
    const next = findNextAudioPage(i)
    if (next >= 0) {
      // 连播：自动翻到下一页有配音的页继续播放
      index.value = next
      playPage(next)
    } else {
      // 整章连播结束，标记完成
      await flushProgress(true)
      uni.showToast({ title: '本章讲解已学习完成', icon: 'success' })
    }
  })

  audioCtx.onError(() => {
    playing.value = false
    uni.showToast({ title: '配音播放失败', icon: 'none' })
  })

  audioCtx.play()
}

function toggleAudio() {
  if (playing.value) {
    audioCtx?.pause()
    playing.value = false
    flushProgress()
    return
  }
  // 当前页音频已加载且处于暂停状态：直接续播，不从头开始
  if (audioCtx && currentAudio.value) {
    audioCtx.play()
    return
  }
  // 从当前页开始连播；当前页无配音则跳到下一页有配音的页
  let target = index.value
  if (!currentAudio.value) {
    const next = findNextAudioPage(index.value - 1)
    if (next < 0) return
    target = next
    index.value = next
  }
  playPage(target)
}

function goPrev() {
  if (index.value <= 0) return
  flushProgress()
  destroyAudio()
  currentTime.value = 0
  duration.value = 0
  resumePending = false
  index.value -= 1
}

function goNext() {
  if (index.value >= pages.value.length - 1) return
  flushProgress()
  destroyAudio()
  currentTime.value = 0
  duration.value = 0
  resumePending = false
  index.value += 1
}

startProgressTimer()

onHide(() => {
  // 退到后台/切页面时暂停并保存进度
  if (playing.value) audioCtx?.pause()
  flushProgress()
})

onUnload(() => {
  flushProgress()
  stopProgressTimer()
  destroyAudio()
})
</script>

<style scoped>
.page {
  padding: 28rpx;
}

.tip {
  padding: 120rpx 0;
  text-align: center;
  font-size: 26rpx;
  color: #94a3b8;
}

.stage {
  position: relative;
  overflow: hidden;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 8rpx rgba(15, 23, 42, 0.06);
}

.stage-image {
  display: block;
  width: 100%;
}

.stage-text {
  padding: 60rpx 40rpx;
}

.stage-title {
  margin-bottom: 24rpx;
  font-size: 34rpx;
  font-weight: 800;
  text-align: center;
  color: #0f172a;
}

.stage-body {
  font-size: 27rpx;
  line-height: 1.9;
  color: #475569;
  white-space: pre-wrap;
}

.stage-count {
  position: absolute;
  top: 20rpx;
  right: 24rpx;
  padding: 6rpx 18rpx;
  border-radius: 999rpx;
  background: rgba(255, 255, 255, 0.85);
  font-size: 22rpx;
  font-weight: 700;
  color: #64748b;
}

.controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18rpx;
  margin: 24rpx 0 16rpx;
}

.nav-btn {
  flex: 1;
  height: 80rpx;
  line-height: 80rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #e2e8f0;
  color: #334155;
  font-size: 26rpx;
}

.nav-btn::after {
  border: none;
}

.nav-btn[disabled] {
  color: #cbd5e1;
  background: #f8fafc;
}

.play-btn {
  flex: 1.2;
  height: 80rpx;
  line-height: 80rpx;
  border-radius: 20rpx;
  background: #2563eb;
  color: #ffffff;
  font-size: 26rpx;
  font-weight: 600;
}

.play-btn::after {
  border: none;
}

.no-audio {
  flex: 1.2;
  text-align: center;
  font-size: 22rpx;
  color: #94a3b8;
}

.audio-bar {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.audio-track {
  flex: 1;
  height: 8rpx;
  overflow: hidden;
  border-radius: 999rpx;
  background: #e2e8f0;
}

.audio-fill {
  height: 100%;
  border-radius: 999rpx;
  background: #2563eb;
}

.audio-time {
  width: 72rpx;
  font-size: 20rpx;
  text-align: center;
  color: #94a3b8;
}

.audio-hint {
  margin: 10rpx 0 8rpx;
  font-size: 20rpx;
  text-align: center;
  color: #94a3b8;
}

.script {
  margin-top: 16rpx;
  padding: 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
}

.script-label {
  margin-bottom: 14rpx;
  font-size: 24rpx;
  font-weight: 700;
  color: #2563eb;
}

.script-text {
  font-size: 26rpx;
  line-height: 1.85;
  color: #475569;
}
</style>
