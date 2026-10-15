<template>
  <div class="page-audio">
    <button
      class="page-audio-btn"
      type="button"
      :aria-label="playing ? '暂停' : '播放'"
      @click="toggle"
    >
      <el-icon><VideoPause v-if="playing" /><VideoPlay v-else /></el-icon>
    </button>
    <span class="page-audio-time">{{ fmt(current) }}</span>
    <div class="page-audio-track" @click="seek">
      <div class="page-audio-fill" :style="{ width: progress + '%' }"></div>
    </div>
    <span class="page-audio-time">{{ fmt(duration) }}</span>
    <audio
      ref="audioRef"
      :src="src"
      preload="metadata"
      class="page-audio-el"
      @timeupdate="onTime"
      @loadedmetadata="onMeta"
      @ended="onEnd"
      @play="onPlay"
      @pause="playing = false"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { VideoPause, VideoPlay } from '@element-plus/icons-vue'

// 讲解稿逐页音频的自定义播放器：原生 controls 在 Chrome 下会把「缓冲区间」显示成
// 类似已播放的进度（未播放就有一段进度条），且轨道深色导致播放进度难以辨认；
// 这里自绘进度条——浅色轨道 + 高对比填充，初始进度恒为 0。
const props = defineProps({ src: { type: String, required: true } })
const emit = defineEmits(['play'])

const audioRef = ref(null)
const playing = ref(false)
const current = ref(0)
const duration = ref(0)
const progress = computed(() => (duration.value ? (current.value / duration.value) * 100 : 0))

// 同一页面可能有多个分页播放器：一个开始播放时暂停其余（通过页面级事件互斥）
const myId = Math.random().toString(36).slice(2)
function onPeerPlay(e) {
  if (e.detail !== myId && playing.value) audioRef.value?.pause()
}

function fmt(sec) {
  if (!Number.isFinite(sec) || sec <= 0) return '0:00'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}
function toggle() {
  const a = audioRef.value
  if (!a) return
  if (playing.value) a.pause()
  else a.play()
}
function onPlay() {
  playing.value = true
  window.dispatchEvent(new CustomEvent('page-audio-play', { detail: myId }))
  emit('play')
}
function onTime() {
  current.value = audioRef.value?.currentTime || 0
}
function onMeta() {
  duration.value = audioRef.value?.duration || 0
}
function onEnd() {
  playing.value = false
  current.value = 0
}
function seek(e) {
  const a = audioRef.value
  if (!a || !duration.value) return
  const rect = e.currentTarget.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
  a.currentTime = ratio * duration.value
  current.value = a.currentTime
}

// 重新配音后音频地址变化：重置播放状态，进度归零
watch(
  () => props.src,
  () => {
    playing.value = false
    current.value = 0
    duration.value = 0
  },
)

onMounted(() => window.addEventListener('page-audio-play', onPeerPlay))
onBeforeUnmount(() => window.removeEventListener('page-audio-play', onPeerPlay))
</script>

<style scoped>
.page-audio {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding: 7px 12px;
  background: #f8fafc;
  border: 1px solid #e5edf8;
  border-radius: 10px;
}
.page-audio-btn {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: none;
  background: #2563eb;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s ease;
}
.page-audio-btn:hover {
  background: #1d4ed8;
}
.page-audio-time {
  flex: 0 0 auto;
  min-width: 38px;
  text-align: center;
  font-size: 12px;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}
.page-audio-track {
  flex: 1;
  height: 6px;
  border-radius: 999px;
  background: #e2e8f0;
  cursor: pointer;
  position: relative;
  transition: height 0.15s ease;
}
.page-audio-track:hover {
  height: 9px;
}
.page-audio-fill {
  height: 100%;
  border-radius: 999px;
  background: #2563eb;
  position: relative;
  transition: width 0.1s linear;
}
.page-audio-fill::after {
  content: "";
  position: absolute;
  right: -5px;
  top: 50%;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #2563eb;
  box-shadow: 0 1px 4px rgba(37, 99, 235, 0.35);
  transform: translateY(-50%);
  opacity: 0;
  transition: opacity 0.15s ease;
}
.page-audio-track:hover .page-audio-fill::after {
  opacity: 1;
}
.page-audio-el {
  display: none;
}
</style>
