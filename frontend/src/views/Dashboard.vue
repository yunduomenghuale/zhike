<template>
  <div class="page-container dashboard">
    <section class="workspace-helix" aria-label="工作台功能入口">
      <div
        ref="helixWrap"
        class="helix_wrap"
        @mouseleave="handleLeave"
        @wheel.prevent="handleWheel"
        @pointerdown="handlePointerDown"
        @pointermove="handlePointerMove"
        @pointerup="handlePointerUp"
        @pointercancel="handlePointerUp"
      >
        <div class="helix_collection">
          <div class="helix_list">
            <div
              v-for="(item, index) in helixCards"
              :key="item.key"
              class="helix_item"
              :style="getHelixStyle(item, index)"
            >
              <button
                class="helix_card"
                type="button"
                @pointerdown.stop
                @click.stop="goTo(item.path)"
              >
                <span class="helix_icon" :style="{ color: item.color, background: item.bg }">
                  <el-icon><component :is="item.icon" /></el-icon>
                </span>
                <span class="helix_text">
                  <span class="helix_title">{{ item.label }}</span>
                  <span class="helix_desc">{{ item.desc }}</span>
                </span>
              </button>
            </div>
          </div>
        </div>
        <div class="helix_vignette"></div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/store/user'
import {
  HomeFilled, Reading, School, Collection, EditPen, Notebook,
  Document, TrendCharts, VideoPlay, ChatDotRound, UserFilled, DataAnalysis, Setting,
} from '@element-plus/icons-vue'

const router = useRouter()
const userStore = useUserStore()
const isStudent = computed(() => userStore.profile?.role === 'student')
const isAdmin = computed(() => userStore.profile?.role === 'admin')

const orbitOffset = ref(0)
const paused = ref(false)
const helixWrap = ref(null)
const stageWidth = ref(1280)
const stageHeight = ref(820)
const repeatCount = 2
const helices = 2
const rotationAngle = 42 * Math.PI / 180
const cardGap = computed(() => Math.min(116, Math.max(96, stageHeight.value * 0.108)))
const orbitDepth = computed(() => Math.min(530, Math.max(310, stageWidth.value * 0.37)))
const minScale = 0.62
const backFade = 0.76
const backBlur = 0.32
let frameId = 0
let lastFrame = 0
let velocity = -0.16
let isDragging = false
let lastPointerY = 0
let resizeObserver = null

const teacherFeatures = [
  { label: '工作台', desc: '总览教学事项', path: '/dashboard', icon: HomeFilled, color: '#2563eb', bg: '#eff6ff' },
  { label: '课程管理', desc: '维护课程与目录', path: '/teacher/courses', icon: Reading, color: '#2563eb', bg: '#eff6ff' },
  { label: '班级管理', desc: '管理班级与学生', path: '/teacher/classes', icon: School, color: '#10b981', bg: '#ecfdf5' },
  { label: '知识库', desc: '上传资料与问答', path: '/teacher/knowledge', icon: Collection, color: '#8b5cf6', bg: '#f5f3ff' },
  { label: '题库', desc: '维护试题资源', path: '/teacher/questions', icon: EditPen, color: '#f59e0b', bg: '#fff7ed' },
  { label: '作业管理', desc: '布置与批改作业', path: '/teacher/homework', icon: Notebook, color: '#0ea5e9', bg: '#f0f9ff' },
  { label: '考试', desc: '组卷与发布考试', path: '/teacher/exams', icon: Document, color: '#ef4444', bg: '#fef2f2' },
  { label: '学习统计', desc: '查看学习数据', path: '/teacher/analytics', icon: TrendCharts, color: '#14b8a6', bg: '#ecfeff' },
]

const studentFeatures = [
  { label: '工作台', desc: '查看学习入口', path: '/dashboard', icon: HomeFilled, color: '#2563eb', bg: '#eff6ff' },
  { label: '我的班级', desc: '查看所在班级', path: '/student/my-classes', icon: School, color: '#10b981', bg: '#ecfdf5' },
  { label: '课程学习', desc: '进入课程内容', path: '/student/learning', icon: VideoPlay, color: '#2563eb', bg: '#eff6ff' },
  { label: '知识库提问', desc: '向知识库提问', path: '/student/qa', icon: ChatDotRound, color: '#8b5cf6', bg: '#f5f3ff' },
  { label: '我的作业', desc: '提交课程作业', path: '/student/homework', icon: Notebook, color: '#0ea5e9', bg: '#f0f9ff' },
  { label: '我的考试', desc: '参加考试答题', path: '/student/exams', icon: Document, color: '#ef4444', bg: '#fef2f2' },
  { label: '错题本', desc: '复盘错题记录', path: '/student/wrong', icon: Collection, color: '#f59e0b', bg: '#fff7ed' },
]

const adminFeatures = [
  { label: '管理概览', desc: '查看平台运行数据', path: '/admin/overview', icon: DataAnalysis, color: '#2563eb', bg: '#eff6ff' },
  { label: '用户管理', desc: '维护教师与学生账号', path: '/admin/users', icon: UserFilled, color: '#8b5cf6', bg: '#f5f3ff' },
  { label: '教学监管', desc: '监管课程与班级状态', path: '/admin/teaching', icon: Reading, color: '#10b981', bg: '#ecfdf5' },
  { label: '大模型配置', desc: '配置模型并测试连接', path: '/admin/ai-settings', icon: Setting, color: '#0ea5e9', bg: '#f0f9ff' },
  { label: '个人中心', desc: '维护管理员账号资料', path: '/profile', icon: HomeFilled, color: '#f59e0b', bg: '#fff7ed' },
]

const baseCards = computed(() => {
  if (isAdmin.value) return adminFeatures
  return isStudent.value ? studentFeatures : teacherFeatures
})
const cardsPerHelix = computed(() => baseCards.value.length * repeatCount)

const helixCards = computed(() => {
  const cards = []
  for (let helix = 0; helix < helices; helix += 1) {
    for (let copy = 0; copy < repeatCount; copy += 1) {
      baseCards.value.forEach((item, baseIndex) => {
        cards.push({
          ...item,
          key: `${helix}-${copy}-${item.path}`,
          helix,
          order: copy * baseCards.value.length + baseIndex,
        })
      })
    }
  }
  return cards
})

function wrapAround(value, size) {
  return ((value % size) + size) % size
}

function centeredPosition(order) {
  const count = cardsPerHelix.value || 1
  return wrapAround(order - orbitOffset.value + count / 2, count) - count / 2
}

function getHelixStyle(item) {
  const relative = centeredPosition(item.order)
  const phase = item.helix * Math.PI
  const angle = relative * rotationAngle + phase
  const cos = Math.cos(angle)
  const sin = Math.sin(angle)
  const backAmount = (1 - cos) / 2
  const verticalFade = Math.max(0, 1 - Math.abs(relative) / (cardsPerHelix.value * 0.43))
  const frontAmount = (cos + 1) / 2

  const x = sin * orbitDepth.value
  const z = (cos - 1) * orbitDepth.value
  const y = relative * cardGap.value
  const scale = minScale + frontAmount * 0.28
  const opacity = Math.max(0.12, verticalFade * (1 - backAmount * backFade))
  const blur = Math.pow(backAmount, 2) * backBlur
  const recede = Math.min(0.82, backAmount * 0.7 + (1 - verticalFade) * 0.32)
  const contentOpacity = frontAmount > 0.5 && verticalFade > 0.38 ? 1 : 0
  const clickable = frontAmount > 0.24 && verticalFade > 0.24
  const zIndex = Math.round((frontAmount * 1000) + (verticalFade * 100))

  return {
    transform: [
      'translate(-50%, -50%)',
      `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, ${z.toFixed(1)}px)`,
      `rotateY(${(angle * 180 / Math.PI).toFixed(1)}deg)`,
      `scale(${scale.toFixed(3)})`,
    ].join(' '),
    opacity: opacity.toFixed(3),
    filter: `blur(${blur.toFixed(3)}em)`,
    zIndex,
    pointerEvents: clickable ? 'auto' : 'none',
    '--recede': recede.toFixed(3),
    '--content-opacity': contentOpacity,
  }
}

function goTo(path) {
  if (!path) return
  router.push(path)
}

function handleWheel(event) {
  velocity += event.deltaY * 0.0025
}

function handlePointerDown(event) {
  isDragging = true
  paused.value = true
  lastPointerY = event.clientY
  event.currentTarget.setPointerCapture?.(event.pointerId)
}

function handlePointerMove(event) {
  if (!isDragging) return
  const delta = event.clientY - lastPointerY
  lastPointerY = event.clientY
  velocity += delta * 0.018
}

function handlePointerUp(event) {
  isDragging = false
  paused.value = false
  event.currentTarget.releasePointerCapture?.(event.pointerId)
}

function handleLeave() {
  paused.value = false
  isDragging = false
}

function tick(now) {
  if (!lastFrame) lastFrame = now
  const delta = now - lastFrame
  lastFrame = now
  const count = cardsPerHelix.value || 1
  const autoVelocity = paused.value ? 0 : -0.16
  const easing = Math.min(1, delta / 900)

  velocity += (autoVelocity - velocity) * easing
  orbitOffset.value = wrapAround(orbitOffset.value + velocity * delta / 1000, count)
  frameId = window.requestAnimationFrame(tick)
}

onMounted(() => {
  const updateStageSize = () => {
    if (!helixWrap.value) return
    const rect = helixWrap.value.getBoundingClientRect()
    stageWidth.value = rect.width
    stageHeight.value = rect.height
  }

  updateStageSize()
  resizeObserver = new ResizeObserver(updateStageSize)
  resizeObserver.observe(helixWrap.value)

  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
  frameId = window.requestAnimationFrame(tick)
})

onBeforeUnmount(() => {
  if (frameId) window.cancelAnimationFrame(frameId)
  resizeObserver?.disconnect()
})
</script>

<style scoped>
.dashboard {
  --workspace-bg: #f6f9fd;
  width: 100%;
  height: 100%;
  min-height: 0;
  padding: 0;
  position: relative;
  overflow: hidden;
  background: var(--workspace-bg);
  color: #0f172a;
}

.dashboard::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: min(64vw, 920px);
  background: linear-gradient(116deg, rgba(255, 255, 255, 0.56) 0%, rgba(239, 246, 255, 0.34) 36%, transparent 60%);
  filter: blur(18px);
  opacity: 0.9;
  pointer-events: none;
}

.dashboard::after {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(to bottom, var(--workspace-bg) 0%, transparent 18%, transparent 78%, var(--workspace-bg) 100%),
    linear-gradient(to right, var(--workspace-bg) 0%, transparent 18%, transparent 82%, var(--workspace-bg) 100%);
  opacity: 0.62;
  pointer-events: none;
}

.workspace-helix {
  --helix-bg: var(--workspace-bg);
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  background: transparent;
  z-index: 1;
}

.helix_wrap {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: clip;
  cursor: grab;
  user-select: none;
}

.helix_wrap:active {
  cursor: grabbing;
}

.helix_collection,
.helix_list {
  position: absolute;
  inset: 0;
}

.helix_list {
  perspective: 76em;
  perspective-origin: 50% 48%;
  transform-style: preserve-3d;
}

.helix_item {
  position: absolute;
  top: 50%;
  left: 50%;
  transform-style: preserve-3d;
  will-change: transform, filter, opacity;
}

.helix_card {
  position: relative;
  width: clamp(15.75rem, 20vw, 18.75rem);
  aspect-ratio: 3 / 2;
  padding: 1.25em 1.35em 1.25em 1.2em;
  display: flex;
  align-items: center;
  gap: 0.95em;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.54);
  border-radius: 0.9em;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(246, 249, 253, 0.94));
  box-shadow:
    0 2.9em 5.6em rgba(37, 99, 235, 0.13),
    0 1.4em 3em rgba(15, 23, 42, 0.08),
    inset 0 1px 1px rgba(255, 255, 255, 0.98),
    inset 0 -1px 2px rgba(37, 99, 235, 0.08),
    0 0 0 1px rgba(37, 99, 235, 0.1) inset;
  color: #0f172a;
  cursor: pointer;
  text-align: left;
  transform-style: preserve-3d;
  backface-visibility: hidden;
  backdrop-filter: blur(18px) saturate(1.12);
}

.helix_card::after {
  content: "";
  position: absolute;
  inset: 0;
  z-index: 4;
  background: var(--helix-bg);
  opacity: var(--recede, 0);
  pointer-events: none;
}

.helix_card::before {
  content: "";
  position: absolute;
  inset: 0.08em;
  z-index: 1;
  border-radius: 0.78em;
  background:
    linear-gradient(110deg, rgba(255, 255, 255, 0.82), transparent 38%),
    linear-gradient(to bottom, rgba(255, 255, 255, 0.45), transparent 42%);
  opacity: 0.56;
  pointer-events: none;
}

.helix_icon,
.helix_text {
  position: relative;
  z-index: 2;
}

.helix_card:hover {
  border-color: rgba(96, 165, 250, 0.82);
  box-shadow:
    0 3.1em 6.4em rgba(37, 99, 235, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.94);
}

.helix_icon,
.helix_text,
.helix_icon {
  width: 4.8em;
  height: 4.8em;
  flex: 0 0 4.8em;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 1.05em;
  font-size: 1.55em;
}

.helix_text {
  flex: 1;
  min-width: 0;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 0.5em;
}

.helix_title {
  overflow: hidden;
  color: #0f172a;
  font-size: 1.38em;
  font-weight: 800;
  line-height: 1.18;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.helix_desc {
  overflow: hidden;
  color: #64748b;
  font-size: 0.86em;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.helix_vignette {
  position: absolute;
  inset: 0;
  z-index: 30;
  pointer-events: none;
  background:
    linear-gradient(to bottom, var(--helix-bg) 0%, rgba(246, 249, 253, 0.54) 14%, transparent 25%, transparent 72%, rgba(246, 249, 253, 0.64) 86%, var(--helix-bg) 100%),
    linear-gradient(to right, var(--helix-bg) 0%, rgba(246, 249, 253, 0.62) 9%, transparent 24%, transparent 76%, rgba(246, 249, 253, 0.72) 91%, var(--helix-bg) 100%);
  opacity: 0.88;
}

@media (max-width: 1100px) {
  .workspace-helix {
    min-height: auto;
  }

  .helix_wrap {
    height: auto;
    min-height: auto;
    overflow: visible;
    cursor: default;
  }

  .helix_collection,
  .helix_list {
    position: relative;
  }

  .helix_list {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px;
    perspective: none;
  }

  .helix_item {
    position: relative;
    top: auto;
    left: auto;
    transform: none !important;
    opacity: 1 !important;
    filter: none !important;
    pointer-events: auto !important;
  }

  .helix_item:nth-child(n + 8) {
    display: none;
  }

  .helix_card {
    width: 100%;
    min-height: 126px;
  }

  .helix_icon,
  .helix_text,
  .helix_text {
    opacity: 1;
  }

  .helix_vignette {
    display: none;
  }
}
</style>
