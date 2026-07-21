<template>
  <div class="page-container">
    <Teleport to="body">
      <div v-if="lectureVisible" class="full-lecture-page">
        <header class="full-lecture-header">
          <div class="full-lecture-title-wrap">
            <div class="full-lecture-icon">
              <el-icon><Document /></el-icon>
            </div>
            <div class="full-lecture-title-copy">
              <div class="full-lecture-title-line">
                <h1>完整讲解</h1>
                <span class="full-lecture-kicker">{{ activeCourseName }}</span>
              </div>
              <p>{{ current?.title || '请选择章节' }}</p>
            </div>
          </div>
          <div class="full-lecture-actions">
            <div class="full-lecture-stats">
              <span><strong>{{ pages.length }}</strong> 页课件</span>
              <span><strong>{{ audioPageCount }}</strong> 页配音</span>
              <el-tag :type="audioPageCount ? 'success' : 'info'" effect="light" round>
                {{ audioPageCount ? '可连续播放' : '暂无配音' }}
              </el-tag>
            </div>
            <el-button
              class="full-lecture-soft-btn"
              :class="{ 'is-active': dockVisible && dockTab !== 'script' }"
              :icon="ChatDotRound"
              @click="toggleDock"
            >AI 助教</el-button>
            <el-button
              class="full-lecture-soft-btn"
              :class="{ 'is-active': dockVisible && dockTab === 'script' }"
              :icon="Document"
              @click="toggleScriptDock"
            >讲解稿</el-button>
            <el-button class="full-lecture-soft-btn" @click="closeLecture">退出讲解</el-button>
          </div>
        </header>

        <div class="full-lecture-body">
          <main class="full-lecture-main">
            <section v-if="pages.length" class="full-lecture-stage-card">
              <div class="full-lecture-stage">
                <div class="ppt-stage-count">{{ playerPageIndex + 1 }} / {{ pages.length }}</div>
                <transition name="page-swap" mode="out-in">
                  <img
                    v-if="currentPlayerPage?.image || currentPlayerPage?.image_url"
                    :key="playerPageIndex"
                    class="full-lecture-image"
                    :src="currentPlayerPage.image || currentPlayerPage.image_url"
                    :alt="currentPlayerPage?.title || `第 ${playerPageIndex + 1} 页`"
                  />
                  <div v-else :key="'text-' + playerPageIndex" class="ppt-stage-text">
                    <div class="ppt-stage-title">{{ currentPlayerPage?.title || `第 ${playerPageIndex + 1} 页` }}</div>
                    <div class="ppt-stage-body">{{ currentPlayerPage?.body || '本页暂无文本内容' }}</div>
                  </div>
                </transition>
              </div>

              <div class="full-lecture-control-panel">
                <audio
                  v-if="currentPlayerScript?.audio_url"
                  ref="playerAudioRef"
                  :key="currentPlayerPage?.page"
                  :src="currentPlayerScript.audio_url"
                  :autoplay="playerAutoPlay"
                  style="display: none"
                  @ended="onPlayerAudioEnded"
                  @play="onPlayerPlay"
                  @pause="onPlayerAudioPause"
                  @timeupdate="onPlayerTimeUpdate"
                  @loadedmetadata="onPlayerLoadedMeta"
                />
                <el-button class="lecture-nav-btn" :icon="ArrowLeft" :disabled="playerPageIndex === 0" @click="prevPlayerPage">上一页</el-button>
                <button class="lecture-play-btn" :disabled="!hasAudio" @click="togglePlayer">
                  <el-icon><VideoPause v-if="playerAutoPlay" /><VideoPlay v-else /></el-icon>
                </button>
                <template v-if="currentPlayerScript?.audio_url">
                  <span class="lecture-time">{{ fmtTime(playerCurrent) }}</span>
                  <div class="lecture-progress" @click="seekPlayer">
                    <div class="lecture-progress-fill" :style="{ width: playerProgress + '%' }"></div>
                  </div>
                  <span class="lecture-time">{{ fmtTime(playerDuration) }}</span>
                </template>
                <span v-else class="lecture-no-audio">当前页暂无配音，播放会自动跳到下一页有配音的内容</span>
                <el-button class="lecture-nav-btn" :disabled="playerPageIndex >= pages.length - 1" @click="nextPlayerPage">
                  下一页<el-icon class="el-icon--right"><ArrowRight /></el-icon>
                </el-button>
              </div>
            </section>
            <div v-else class="full-lecture-empty">
              <el-empty description="当前章节还没有可播放的课件" />
            </div>
          </main>

          <transition name="dock-slide">
            <aside v-if="dockVisible" class="full-lecture-dock">
              <div class="dock-tabs">
                <button class="dock-tab" :class="{ active: dockTab === 'chat' }" @click="dockTab = 'chat'">
                  <el-icon><ChatDotRound /></el-icon> AI 问答
                </button>
                <button class="dock-tab" :class="{ active: dockTab === 'materials' }" @click="switchDockTab('materials')">
                  <el-icon><Folder /></el-icon> 相关资料
                </button>
                <button class="dock-tab" :class="{ active: dockTab === 'script' }" @click="switchDockTab('script')">
                  <el-icon><Document /></el-icon> 讲解稿
                </button>
                <button class="dock-close" title="收起" @click="dockVisible = false">
                  <el-icon><Close /></el-icon>
                </button>
              </div>

              <div v-show="dockTab === 'chat'" class="dock-chat">
                <div ref="chatScrollRef" class="chat-messages">
                  <div v-if="!chatMessages.length" class="chat-empty">
                    <div class="chat-empty-hero">
                      <span class="chat-empty-glow"></span>
                      <div class="chat-empty-icon"><el-icon><MagicStick /></el-icon></div>
                    </div>
                    <p class="chat-empty-title">课程 AI 助教</p>
                    <p class="chat-empty-desc">结合当前课程资料、章节内容和知识库回答问题，适合梳理重点、解释概念和生成复习思路。</p>
                    <div class="chat-suggests">
                      <button v-for="q in chatSuggests" :key="q" class="chat-suggest" @click="askChat(q)">{{ q }}</button>
                    </div>
                  </div>
                  <div v-for="(m, i) in chatMessages" :key="i" class="chat-row" :class="m.role">
                    <div class="chat-bubble" :class="{ bare: m.imageOnly }">
                      <span v-if="m.streaming && !m.content" class="chat-typing"><i></i><i></i><i></i></span>
                      <div v-else-if="m.role === 'assistant'" class="chat-text chat-md" v-html="renderMd(m.content + (m.streaming ? ' ▍' : ''))"></div>
                      <div v-else class="chat-text">
                        <img v-if="m.image" :src="m.image" class="q-image" alt="提问图片" />
                        <template v-if="!m.imageOnly">{{ m.content }}</template>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="chat-input">
                  <div v-if="chatImage" class="chat-image-preview">
                    <img :src="chatImage" alt="待发送图片" />
                    <button class="preview-remove" title="移除图片" @click="chatImage = ''">
                      <el-icon :size="11"><Close /></el-icon>
                    </button>
                  </div>
                  <textarea
                    ref="chatTextareaRef"
                    v-model="chatInput"
                    class="chat-textarea"
                    rows="1"
                    placeholder="向 AI 助教提问…（Enter 发送）"
                    @input="autoGrowInput"
                    @keydown.enter.exact.prevent="askChat()"
                  ></textarea>
                  <div class="chat-input-bar">
                    <input ref="chatFileRef" type="file" accept="image/*" hidden @change="onPickChatImage" />
                    <button class="chat-tool" title="提交图片提问" @click="chatFileRef?.click()">
                      <el-icon :size="15"><Picture /></el-icon>
                      图片
                    </button>
                    <button class="chat-send" title="发送" :disabled="chatLoading || (!chatInput.trim() && !chatImage)" @click="askChat()">
                      <el-icon><Promotion /></el-icon>
                    </button>
                  </div>
                </div>
              </div>

              <div v-show="dockTab === 'materials'" class="dock-materials">
                <div v-if="materialsLoading" class="dock-loading">
                  <el-icon class="is-loading"><Loading /></el-icon> 正在加载资料...
                </div>
                <template v-else>
                  <div v-if="!materials.length" class="dock-empty">
                    <el-empty description="本课程还没有可查看的资料" :image-size="90" />
                  </div>
                  <a v-for="m in materials" :key="m.id" class="material-item" :href="fileUrl(m.file)" target="_blank" rel="noopener">
                    <span class="material-icon"><el-icon><Document /></el-icon></span>
                    <span class="material-copy">
                      <span class="material-name">{{ m.file_name }}</span>
                      <span class="material-meta">{{ (m.file_type || '文件').toUpperCase() }} · {{ m.chunk_count || 0 }} 片段 · {{ m.parse_status_display || '已解析' }}</span>
                    </span>
                    <el-icon class="material-open"><Right /></el-icon>
                  </a>
                </template>
              </div>

              <div v-show="dockTab === 'script'" class="dock-scripts">
                <div class="dock-script-summary">
                  <div>
                    <strong>逐页讲解稿</strong>
                    <span>跟随当前 PPT 页面同步显示</span>
                  </div>
                  <span class="dock-script-progress">{{ pages.length ? playerPageIndex + 1 : 0 }} / {{ scripts.length }}</span>
                </div>
                <div v-if="scripts.length" ref="scriptDockListRef" class="dock-script-list">
                  <button
                    v-for="item in scripts"
                    :key="item.page"
                    type="button"
                    class="dock-script-item"
                    :class="{ active: currentPlayerPage?.page === item.page }"
                    :data-script-page="item.page"
                    @click="selectScriptPage(item)"
                  >
                    <span class="dock-script-item-head">
                      <span>第 {{ item.page }} 页</span>
                      <span class="dock-script-audio" :class="{ ready: item.audio_url }">{{ item.audio_url ? '已配音' : '未配音' }}</span>
                    </span>
                    <span class="dock-script-text">{{ item.script || '本页暂无讲解稿' }}</span>
                  </button>
                </div>
                <div v-else class="dock-empty">
                  <el-empty description="当前章节还没有讲解稿" :image-size="90" />
                </div>
              </div>
            </aside>
          </transition>
        </div>
      </div>
    </Teleport>

    <div class="page-header">
      <div>
        <div class="page-title">课程学习</div>
        <div class="page-subtitle">按章节学习课件与讲解，并完成章节练习</div>
      </div>
      <el-select
        v-if="!fixedCourseId"
        v-model="courseId"
        placeholder="选择课程"
        class="student-filter-select"
        style="width: 240px"
        @change="loadTree"
      >
        <el-option v-for="c in filteredCourses" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
    </div>

    <el-empty v-if="!courseId" description="请先选择课程（需先加入班级）" />

    <div v-else class="learn-shell">
      <!-- 章节目录（整宽平铺，与教师端同款行样式） -->
      <div class="chapter-rows animate-list">
        <div
          v-for="row in chapterRows"
          :key="row.node.id"
          class="tree-node"
          :class="{ 'is-child': row.isChild, active: current?.id === row.node.id }"
          @click="openChapter(row.node, '')"
        >
            <div class="node-main">
              <div class="node-left">
                <span class="node-icon-wrap">
                  <el-icon class="node-icon"><Folder v-if="!row.isChild" /><Document v-else /></el-icon>
                </span>
                <span class="node-title">{{ row.node.title }}</span>
              </div>
            </div>
            <div class="node-actions">
              <div class="node-action-group">
                <el-button class="node-action-btn" :icon="VideoPlay" @click.stop="openChapter(row.node, '')">完整讲解</el-button>
                <el-button class="node-action-btn" :icon="Microphone" @click.stop="openChapter(row.node, 'script')">讲稿</el-button>
                <el-button class="node-action-btn" :icon="ChatDotRound" @click.stop="openChapter(row.node, 'chat')">AI 问答</el-button>
              </div>
            </div>
          </div>
          <el-empty v-if="!chapterRows.length" :description="tree.length ? '没有匹配的章节' : '暂无已发布章节'" :image-size="60" />
        </div>

    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Microphone, ArrowLeft, ArrowRight, CircleCheck, CircleClose, VideoPlay,
  Document, ChatDotRound, Folder, Close, MagicStick, Promotion, Picture, Loading,
  Right, VideoPause,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { listClasses } from '@/api/classroom'
import { listCatalogs, listPpts, listVideos } from '@/api/course'
import { listQuestions, practiceSubmit } from '@/api/question'
import { listMaterials } from '@/api/knowledge'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

const courses = ref([])
const courseId = ref(null)
const tree = ref([])
const current = ref(null)
const tab = ref('learn')
const route = useRoute()
const fixedCourseId = computed(() => Number(route.params.id) || null)
const keyword = computed(() => String(route.query.search || '').trim().toLowerCase())
const filteredCourses = computed(() => {
  if (!keyword.value) return courses.value
  return courses.value.filter((c) => String(c.name || '').toLowerCase().includes(keyword.value))
})
const activeCourseName = computed(() => {
  const course = courses.value.find((item) => Number(item.id) === Number(courseId.value))
  return course?.name || '当前课程'
})
const visibleTree = computed(() => {
  if (!keyword.value) return tree.value
  const matchNode = (node) => String(node.title || '').toLowerCase().includes(keyword.value)
  const walk = (nodes) => nodes
    .map((node) => {
      const children = walk(node.children || [])
      if (matchNode(node) || children.length) return { ...node, children }
      return null
    })
    .filter(Boolean)
  return walk(tree.value)
})

// 章节行（父章 + 子节拍平，便于整宽列表渲染）
const chapterRows = computed(() => {
  const rows = []
  for (const n of visibleTree.value) {
    rows.push({ node: n, isChild: false })
    for (const c of n.children || []) rows.push({ node: c, isChild: true })
  }
  return rows
})

async function loadCourses() {
  const data = await listClasses()
  const rows = data.results ?? data
  const map = new Map()
  rows.forEach((row) => {
    const ids = row.courses?.length ? row.courses : [row.course]
    ids.filter(Boolean).forEach((id, index) => {
      map.set(id, { id, name: row.course_names?.[index] || row.course_name || `课程 ${id}` })
    })
  })
  courses.value = [...map.values()]
  if (fixedCourseId.value) {
    courseId.value = fixedCourseId.value
    loadTree()
  } else if (courses.value.length) {
    courseId.value = courses.value[0].id
    loadTree()
  }
}

async function loadTree() {
  current.value = null
  materialsLoaded = false
  materials.value = []
  chatMessages.value = []
  stopPlayer()
  const data = await listCatalogs({ course: courseId.value, tree: 1 })
  tree.value = data.results ?? data
}

// 章节动作：'' 完整讲解 / 'script' 讲稿 / 'chat' AI 问答
async function openChapter(node, action = '') {
  stopPlayer()
  dockVisible.value = false
  if (current.value?.id !== node.id) {
    current.value = node
    tab.value = 'learn'
    pageIdx.value = 0
    pages.value = []
    scripts.value = []
    loadPractice()
  }
  if (!pages.value.length && !learnLoading.value) await loadLearn()
  if (pages.value.length) {
    openLecture(action)
  } else {
    ElMessage.info('本章还没有课件，敬请期待')
  }
}

// ---- 课件学习 ----
const learnLoading = ref(false)
const pages = ref([])
const scripts = ref([])
const pageIdx = ref(0)
const continuousPlay = ref(false)
const audioRef = ref(null)
const hasAudio = computed(() => scripts.value.some((s) => s.audio_url))
const audioPageCount = computed(() => scripts.value.filter((s) => s.audio_url).length)
function scriptOf(page) {
  return scripts.value.find((s) => s.page === page.page)?.script || ''
}
function audioOf(page) {
  return scripts.value.find((s) => s.page === page.page)?.audio_url || ''
}
async function loadLearn() {
  learnLoading.value = true
  pages.value = []
  scripts.value = []
  pageIdx.value = 0
  try {
    const ppt = await listPpts({ catalog: current.value.id })
    const pptList = ppt.results ?? ppt
    const active = pptList.find((p) => p.is_active) || pptList[0]
    pages.value = active?.parsed_pages || []
    const vid = await listVideos({ catalog: current.value.id })
    const vids = vid.results ?? vid
    scripts.value = vids[0]?.scripts || []
  } finally {
    learnLoading.value = false
  }
}

function toggleContinuous() {
  continuousPlay.value = !continuousPlay.value
  if (!continuousPlay.value) {
    audioRef.value?.pause?.()
    return
  }
  if (!audioOf(pages.value[pageIdx.value])) {
    const next = findNextAudioPage(pageIdx.value - 1)
    if (next >= 0) pageIdx.value = next
  }
  setTimeout(() => audioRef.value?.play?.(), 0)
}

function onAudioEnded() {
  if (!continuousPlay.value) return
  const next = findNextAudioPage(pageIdx.value)
  if (next >= 0) {
    pageIdx.value = next
  } else {
    continuousPlay.value = false
  }
}

function findNextAudioPage(startIndex) {
  for (let i = startIndex + 1; i < pages.value.length; i += 1) {
    if (audioOf(pages.value[i])) return i
  }
  return -1
}

// ---- 完整讲解：播放器 + AI 助教 Dock ----
const lectureVisible = ref(false)
const playerPageIndex = ref(0)
const playerAutoPlay = ref(false)
const playerCurrent = ref(0)
const playerDuration = ref(0)
const playerAudioRef = ref(null)
const dockVisible = ref(false)
const dockTab = ref('chat')
const chatMessages = ref([])
const chatInput = ref('')
const chatImage = ref('')
const chatFileRef = ref(null)
const chatSessionId = crypto.randomUUID()

function onPickChatImage(e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) return ElMessage.warning('请选择图片文件')
  if (file.size > 6 * 1024 * 1024) return ElMessage.warning('图片不能超过 6MB')
  const reader = new FileReader()
  reader.onload = () => {
    const img = new Image()
    img.onload = () => {
      const max = 1024
      let { width, height } = img
      if (Math.max(width, height) > max) {
        const scale = max / Math.max(width, height)
        width = Math.round(width * scale)
        height = Math.round(height * scale)
      }
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      canvas.getContext('2d').drawImage(img, 0, 0, width, height)
      // PNG 保留原格式（避免透明背景转 JPEG 变黑），其余统一 JPEG 压缩
      chatImage.value = file.type === 'image/png'
        ? canvas.toDataURL('image/png')
        : canvas.toDataURL('image/jpeg', 0.85)
    }
    img.src = reader.result
  }
  reader.readAsDataURL(file)
}
const chatLoading = ref(false)
const chatScrollRef = ref(null)
const chatTextareaRef = ref(null)
const scriptDockListRef = ref(null)
const chatSuggests = ['这一章的重点是什么？', '用简单的话解释当前知识点', '帮我生成 3 道复习题']
const materials = ref([])
const materialsLoading = ref(false)
let materialsLoaded = false

const currentPlayerPage = computed(() => pages.value[playerPageIndex.value] || null)
const currentPlayerScript = computed(() => {
  const page = currentPlayerPage.value?.page
  return scripts.value.find((item) => item.page === page) || null
})
const playerProgress = computed(() => {
  if (!playerDuration.value) return 0
  return Math.min(100, Math.max(0, (playerCurrent.value / playerDuration.value) * 100))
})

async function openLecture(tabName = '') {
  if (!current.value) {
    ElMessage.warning('请先选择章节')
    return
  }
  if (!pages.value.length && !learnLoading.value) await loadLearn()
  stopPlayer()
  playerPageIndex.value = pageIdx.value || 0
  lectureVisible.value = true
  if (tabName) {
    dockTab.value = tabName
    dockVisible.value = true
    if (tabName === 'materials') ensureMaterials()
    if (tabName === 'script') scrollCurrentScriptIntoView()
  }
}

function closeLecture() {
  stopPlayer()
  lectureVisible.value = false
}

function toggleDock() {
  if (dockVisible.value && dockTab.value !== 'script') {
    dockVisible.value = false
    return
  }
  dockTab.value = 'chat'
  dockVisible.value = true
}

function toggleScriptDock() {
  if (dockVisible.value && dockTab.value === 'script') {
    dockVisible.value = false
    return
  }
  dockTab.value = 'script'
  dockVisible.value = true
  scrollCurrentScriptIntoView()
}

function switchDockTab(tabName) {
  dockTab.value = tabName
  if (tabName === 'materials') ensureMaterials()
  if (tabName === 'script') scrollCurrentScriptIntoView()
}

function prevPlayerPage() {
  if (playerPageIndex.value <= 0) return
  stopPlayer()
  playerPageIndex.value -= 1
}

function nextPlayerPage() {
  if (playerPageIndex.value >= pages.value.length - 1) return
  stopPlayer()
  playerPageIndex.value += 1
}

function togglePlayer() {
  if (!hasAudio.value) return
  if (!currentPlayerScript.value?.audio_url) {
    const next = findNextAudioPage(playerPageIndex.value - 1)
    if (next >= 0) playerPageIndex.value = next
  }
  nextTick(() => {
    const audio = playerAudioRef.value
    if (!audio) return
    if (audio.paused) {
      playerAutoPlay.value = true
      audio.play?.().catch(() => {
        playerAutoPlay.value = false
      })
    } else {
      playerAutoPlay.value = false
      audio.pause?.()
    }
  })
}

function stopPlayer() {
  playerAutoPlay.value = false
  playerAudioRef.value?.pause?.()
  playerCurrent.value = 0
  playerDuration.value = 0
}

function onPlayerPlay() {
  playerAutoPlay.value = true
}

function onPlayerAudioPause() {
  playerAutoPlay.value = false
}

function onPlayerTimeUpdate(e) {
  playerCurrent.value = e.target?.currentTime || 0
}

function onPlayerLoadedMeta(e) {
  playerDuration.value = e.target?.duration || 0
  playerCurrent.value = 0
}

function onPlayerAudioEnded() {
  const next = findNextAudioPage(playerPageIndex.value)
  if (next >= 0) {
    playerPageIndex.value = next
    nextTick(() => playerAudioRef.value?.play?.())
  } else {
    stopPlayer()
  }
}

function seekPlayer(e) {
  const audio = playerAudioRef.value
  if (!audio || !playerDuration.value) return
  const rect = e.currentTarget.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
  audio.currentTime = ratio * playerDuration.value
}

function selectScriptPage(item) {
  const index = pages.value.findIndex((page) => page.page === item.page)
  if (index < 0) return
  stopPlayer()
  playerPageIndex.value = index
}

function scrollCurrentScriptIntoView() {
  nextTick(() => {
    const page = currentPlayerPage.value?.page
    if (page == null) return
    scriptDockListRef.value
      ?.querySelector(`[data-script-page="${page}"]`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}

async function ensureMaterials(force = false) {
  if (materialsLoaded && !force) return
  materialsLoading.value = true
  try {
    const data = await listMaterials({ course: courseId.value })
    materials.value = Array.isArray(data?.results) ? data.results : Array.isArray(data) ? data : []
    materialsLoaded = true
  } catch {
    materials.value = []
  } finally {
    materialsLoading.value = false
  }
}

function autoGrowInput() {
  const el = chatTextareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 118)}px`
  el.style.overflowY = el.scrollHeight > 118 ? 'auto' : 'hidden'
}

async function askChat(preset) {
  const q = (preset ?? chatInput.value).trim()
  const img = chatImage.value
  if ((!q && !img) || chatLoading.value) return
  const text = q || '请描述并解读这张图片'
  chatMessages.value.push({ role: 'user', content: text, image: img, imageOnly: !q })
  chatInput.value = ''
  chatImage.value = ''
  nextTick(autoGrowInput)
  chatLoading.value = true
  const idx = chatMessages.value.push({ role: 'assistant', content: '', streaming: true }) - 1
  scrollChatToBottom()
  try {
    const token = localStorage.getItem('access_token')
    const resp = await fetch('/api/qa-records/ask-stream/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ course: courseId.value, catalog: current.value?.id, question: text, session: chatSessionId, ...(img ? { image: img } : {}) }),
    })
    if (!resp.ok || !resp.body) throw new Error('bad response')

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      frames.forEach((frame) => {
        const line = frame.trim()
        if (!line.startsWith('data:')) return
        const jsonStr = line.slice(5).trim()
        if (!jsonStr) return
        let evt
        try { evt = JSON.parse(jsonStr) } catch { return }
        if (evt.type === 'delta') {
          chatMessages.value[idx].content += evt.text || ''
          scrollChatToBottom()
        } else if (evt.type === 'error') {
          chatMessages.value[idx].content += `\n[出错] ${evt.message || '生成失败'}`
        }
      })
    }
  } catch {
    chatMessages.value[idx].content = chatMessages.value[idx].content || '抱歉，AI 助教暂时没有响应，请稍后再试。'
  } finally {
    chatMessages.value[idx].streaming = false
    chatLoading.value = false
    scrollChatToBottom()
  }
}

function scrollChatToBottom() {
  nextTick(() => {
    const el = chatScrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function renderMd(text) {
  return md.render(text || '')
}

function fileUrl(file) {
  return file || '#'
}

function fmtTime(sec) {
  const value = Number.isFinite(sec) ? Math.floor(sec) : 0
  const min = Math.floor(value / 60)
  const second = String(value % 60).padStart(2, '0')
  return `${min}:${second}`
}

watch(playerPageIndex, () => {
  if (dockVisible.value && dockTab.value === 'script') scrollCurrentScriptIntoView()
})

// ---- 章节练习 ----
const practiceLoading = ref(false)
const questions = ref([])
const answers = reactive({})
const feedback = reactive({})
const submitted = ref(false)
const submitting = ref(false)
const result = reactive({ total: 0, correct: 0 })

async function loadPractice() {
  practiceLoading.value = true
  resetState()
  try {
    const data = await listQuestions({ course: courseId.value, catalog: current.value.id, status: 'published' })
    questions.value = data.results ?? data
    questions.value.forEach((q) => {
      answers[q.id] = q.qtype === 'multi' ? [] : q.qtype === 'blank' ? [''] : ''
    })
  } finally {
    practiceLoading.value = false
  }
}
function resetState() {
  Object.keys(answers).forEach((k) => delete answers[k])
  Object.keys(feedback).forEach((k) => delete feedback[k])
  submitted.value = false
}
function resetPractice() {
  questions.value.forEach((q) => {
    answers[q.id] = q.qtype === 'multi' ? [] : q.qtype === 'blank' ? [''] : ''
  })
  Object.keys(feedback).forEach((k) => delete feedback[k])
  submitted.value = false
}
function buildAns(q) {
  const v = answers[q.id]
  if (q.qtype === 'multi') return { keys: v }
  if (q.qtype === 'blank') return { blanks: v }
  if (q.qtype === 'short') return { text: v }
  return { key: v }
}
function fmt(a) {
  if (!a) return '-'
  if (a.key) return a.key
  if (a.keys) return a.keys.join(', ')
  if (a.blanks) return a.blanks.join(' / ')
  return '-'
}
async function submitPractice() {
  const payload = {}
  questions.value.forEach((q) => { payload[q.id] = buildAns(q) })
  submitting.value = true
  try {
    const res = await practiceSubmit({ answers: payload })
    res.results.forEach((r) => { feedback[r.question_id] = r })
    result.total = res.total
    result.correct = res.correct
    submitted.value = true
    ElMessage.success(`提交完成，答对 ${res.correct}/${res.total}`)
  } finally {
    submitting.value = false
  }
}

watch(fixedCourseId, (id) => {
  if (!id) return
  courseId.value = id
  loadTree()
})

onMounted(loadCourses)
</script>

<style scoped>
.learn-shell {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.chapter-rows {
  display: grid;
  gap: 10px;
}

/* 章节行（与教师端「章节与课件」同款） */
.tree-node {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 20px;
  min-width: 0;
  padding: 13px 18px;
  border: 1px solid var(--gray-100);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.tree-node:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.2);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1);
}

.tree-node.active {
  border-color: #3b82f6;
  background: linear-gradient(135deg, #eff6ff, #ffffff 65%);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.14);
}

.tree-node.is-child {
  margin-left: 34px;
}

.node-main {
  display: flex;
  align-items: center;
  gap: 18px;
  min-width: 0;
}

.node-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 0 1 auto;
}

.node-icon-wrap {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  transition: transform 0.18s ease;
}

.tree-node:hover .node-icon-wrap {
  transform: scale(1.04);
}

.tree-node.is-child .node-icon-wrap {
  width: 30px;
  height: 30px;
  background: var(--el-fill-color-light);
}

.node-icon {
  font-size: 17px;
}

.node-title {
  max-width: 420px;
  font-size: 15px;
  font-weight: 650;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-node.active .node-title {
  color: #1d4ed8;
}

.node-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

.node-action-group {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 10px;
  background: #f8fafc;
}

.node-action-btn {
  height: 30px;
  padding: 0 9px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--el-color-primary);
  font-weight: 600;
}

.node-action-btn:hover {
  background: #fff;
  color: var(--el-color-primary);
  box-shadow: var(--shadow-xs);
}

.learning-panel {
  min-width: 0;
  min-height: 0;
  padding: 22px;
  border: 1px solid #e5eaf3;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 16px 38px rgba(37, 99, 235, 0.06);
  overflow: auto;
}

.select-empty {
  min-height: 420px;
  display: grid;
  place-items: center;
}

.content-head {
  min-height: 48px;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid #e5eaf3;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.chapter-label {
  color: #2563eb;
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 4px;
}

.chapter-name {
  color: #0f172a;
  font-weight: 850;
  font-size: 18px;
}

.slide {
  background: #f4f7fc;
  border: 1px solid #dbe7f7;
  border-radius: 20px;
  padding: 24px;
  min-height: 420px;
  display: grid;
  place-items: center;
}

.slide-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  margin-bottom: 16px;
  text-align: center;
}
.slide-body {
  white-space: pre-wrap;
  line-height: 1.9;
  color: var(--el-text-color-regular);
}
.slide-image {
  display: block;
  width: 100%;
  max-height: 620px;
  object-fit: contain;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
}

.lecture-summary {
  margin-top: 16px;
  padding: 14px 16px;
  border: 1px solid #e5eaf3;
  border-radius: 18px;
  background: linear-gradient(135deg, #f8fbff, #ffffff);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
  display: flex;
  align-items: center;
  gap: 14px;
}

.lecture-summary-icon {
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 14px;
  color: #2563eb;
  background: #eff6ff;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.18);
}

.lecture-summary-copy {
  flex: 1;
  min-width: 0;
}

.lecture-summary-title {
  font-size: 15px;
  font-weight: 850;
  color: #0f172a;
}

.lecture-summary-subtitle {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
}

.lecture-summary-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.script {
  margin-top: 16px;
  background: #f8fbff;
  border: 1px solid #e5eaf3;
  border-radius: 18px;
  padding: 16px 18px;
}
.script-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 13px;
  color: var(--el-color-primary);
  margin-bottom: 6px;
}

.script-label span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.script-audio {
  width: 100%;
  height: 38px;
  margin-bottom: 10px;
}
.script-text {
  line-height: 1.8;
  color: var(--el-text-color-regular);
}
.slide-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  margin-top: 18px;
}
.page-ind {
  color: var(--el-text-color-secondary);
}
.q-card {
  margin-bottom: 14px;
  border: 1px solid #e5eaf3;
  border-radius: 16px;
}
.q-stem {
  margin-bottom: 12px;
}
.q-idx {
  font-weight: 700;
  margin-right: 6px;
}
.opt {
  display: block;
  margin: 6px 0;
}
.fb {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 14px;
}
.fb.ok {
  background: #f0f9eb;
  color: #67c23a;
}
.fb.no {
  background: #fef0f0;
  color: #f56c6c;
}
.fb-ana {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.practice-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 8px;
}

.full-lecture-page,
.full-lecture-page * {
  box-sizing: border-box;
}

.full-lecture-page {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: grid;
  grid-template-rows: 76px minmax(0, 1fr);
  background:
    linear-gradient(180deg, rgba(248, 251, 255, 0.98), rgba(239, 246, 255, 0.96)),
    #f6f9ff;
  color: #0f172a;
}

.full-lecture-header {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 28px;
  border-bottom: 1px solid rgba(37, 99, 235, 0.1);
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(14px);
}

.full-lecture-title-wrap,
.full-lecture-title-line,
.full-lecture-actions,
.full-lecture-stats {
  display: flex;
  align-items: center;
  min-width: 0;
}

.full-lecture-title-wrap {
  gap: 10px;
}

.full-lecture-icon {
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 11px;
  color: #2563eb;
  background: #eff6ff;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.22);
}

.full-lecture-title-copy {
  min-width: 0;
}

.full-lecture-title-line {
  gap: 10px;
}

.full-lecture-title-copy h1 {
  margin: 0;
  font-size: 21px;
  line-height: 1.2;
  color: #0f172a;
  white-space: nowrap;
}

.full-lecture-title-copy p {
  max-width: 56vw;
  margin: 4px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #64748b;
  font-size: 13px;
}

.full-lecture-kicker {
  max-width: 34vw;
  overflow: hidden;
  padding: 3px 9px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #64748b;
  background: #f8fbff;
  font-size: 12px;
  font-weight: 750;
}

.full-lecture-actions {
  justify-content: flex-end;
  gap: 8px;
}

.full-lecture-stats {
  gap: 8px;
  padding: 6px 10px;
  border: 1px solid rgba(37, 99, 235, 0.08);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.78);
  color: #64748b;
  font-size: 12px;
}

.full-lecture-stats strong {
  color: #2563eb;
  font-size: 16px;
}

.full-lecture-soft-btn {
  height: 36px;
  padding: 0 15px;
  border-radius: 999px;
  border-color: rgba(37, 99, 235, 0.12);
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.08);
  font-weight: 750;
}

.full-lecture-soft-btn.is-active {
  color: #2563eb;
  border-color: rgba(37, 99, 235, 0.4);
  background: linear-gradient(180deg, #eff6ff, #dbeafe);
}

.full-lecture-body {
  min-width: 0;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

.full-lecture-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  padding: 22px 28px 26px;
}

.full-lecture-stage-card {
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  border: 1px solid rgba(37, 99, 235, 0.1);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 24px 60px rgba(37, 99, 235, 0.1);
  overflow: hidden;
}

.full-lecture-stage {
  position: relative;
  min-height: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: linear-gradient(145deg, #f8fbff, #eef4ff);
}

/* 翻页过渡：切页时淡入侧滑 */
.page-swap-enter-active,
.page-swap-leave-active {
  transition: opacity 0.24s ease, transform 0.24s ease;
}

.page-swap-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.page-swap-leave-to {
  opacity: 0;
  transform: translateX(-20px);
}

.ppt-stage-text {
  text-align: center;
}

.ppt-stage-count {
  position: absolute;
  top: 18px;
  right: 20px;
  z-index: 1;
  padding: 5px 10px;
  border-radius: 999px;
  color: #64748b;
  background: rgba(255, 255, 255, 0.82);
  font-size: 13px;
  font-weight: 750;
}

.full-lecture-image {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 0;
  object-fit: contain;
  border-radius: 16px;
  background: #fff;
}

.full-lecture-control-panel {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 13px 20px;
  border-top: 1px solid rgba(37, 99, 235, 0.08);
  background: rgba(255, 255, 255, 0.92);
}

.lecture-nav-btn {
  height: 36px;
  border-radius: 999px;
}

.lecture-play-btn {
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 50%;
  color: #fff;
  background: linear-gradient(135deg, #60a5fa, #2563eb);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.32);
  cursor: pointer;
}

.lecture-play-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.lecture-time {
  width: 42px;
  color: #64748b;
  font-size: 13px;
  font-weight: 750;
  text-align: center;
}

.lecture-progress {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: #dbe7f7;
  cursor: pointer;
  overflow: hidden;
}

.lecture-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #60a5fa, #2563eb);
}

.lecture-no-audio {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #94a3b8;
  font-size: 13px;
}

.full-lecture-dock {
  flex: 0 0 clamp(420px, 32vw, 540px);
  width: clamp(420px, 32vw, 540px);
  min-height: 0;
  margin: 22px 22px 26px 0;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 22px;
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 28px 70px rgba(37, 99, 235, 0.14);
  backdrop-filter: blur(18px);
  overflow: hidden;
}

.dock-slide-enter-active,
.dock-slide-leave-active {
  transition: transform 0.26s ease, opacity 0.22s ease;
}

.dock-slide-enter-from,
.dock-slide-leave-to {
  transform: translateX(22px);
  opacity: 0;
}

.dock-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px;
  border-bottom: 1px solid rgba(37, 99, 235, 0.08);
}

.dock-tab {
  height: 34px;
  padding: 0 14px;
  border: 0;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  color: #64748b;
  font-size: 13px;
  font-weight: 750;
  cursor: pointer;
}

.dock-tab.active {
  color: #fff;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.28);
}

.dock-close {
  margin-left: auto;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #64748b;
  background: rgba(148, 163, 184, 0.14);
  cursor: pointer;
}

.dock-chat,
.dock-scripts {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.chat-messages,
.dock-materials,
.dock-script-list,
.chapter-rows,
.learning-panel {
  scrollbar-width: none;
}

.chat-messages::-webkit-scrollbar,
.dock-materials::-webkit-scrollbar,
.dock-script-list::-webkit-scrollbar,
.chapter-rows::-webkit-scrollbar,
.learning-panel::-webkit-scrollbar {
  display: none;
}

.chat-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.chat-empty {
  margin: auto 0;
  text-align: center;
  padding: 12px 8px;
}

.chat-empty-hero {
  position: relative;
  width: 72px;
  height: 72px;
  margin: 4px auto 14px;
  display: grid;
  place-items: center;
}

.chat-empty-glow {
  position: absolute;
  inset: -6px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.42), rgba(59, 130, 246, 0) 70%);
  filter: blur(6px);
  animation: chat-glow-pulse 2.8s ease-in-out infinite;
}

@keyframes chat-glow-pulse {
  0%, 100% { transform: scale(0.9); opacity: 0.65; }
  50% { transform: scale(1.12); opacity: 1; }
}

.chat-empty-icon {
  position: relative;
  width: 58px;
  height: 58px;
  display: grid;
  place-items: center;
  border-radius: 19px;
  color: #fff;
  font-size: 28px;
  background: linear-gradient(140deg, #60a5fa, #2563eb);
  box-shadow: 0 16px 32px rgba(37, 99, 235, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.5);
  animation: chat-icon-float 3.4s ease-in-out infinite;
}

@keyframes chat-icon-float {
  0%, 100% { transform: translateY(0) rotate(-2deg); }
  50% { transform: translateY(-6px) rotate(2deg); }
}

.chat-empty-title {
  margin: 0;
  color: #0f172a;
  font-size: 17px;
  font-weight: 850;
}

.chat-empty-desc {
  max-width: 320px;
  margin: 8px auto 18px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.7;
}

.chat-suggests {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.chat-suggest {
  padding: 8px 12px;
  border: 1px solid rgba(37, 99, 235, 0.14);
  border-radius: 999px;
  background: #fff;
  color: #2563eb;
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
}

.chat-row {
  display: flex;
  align-items: flex-start;
}

.chat-row.user {
  justify-content: flex-end;
}

.chat-bubble {
  max-width: 100%;
  padding: 2px 0;
  color: #334155;
  font-size: 13.5px;
  line-height: 1.75;
}

.chat-row.user .chat-bubble {
  max-width: 86%;
  padding: 9px 14px;
  border-radius: 16px;
  border-bottom-right-radius: 6px;
  background: #f1f3f5;
  color: #334155;
}

.chat-row.user .chat-bubble.bare {
  padding: 0;
  background: transparent;
}

.chat-typing i {
  display: inline-block;
  width: 5px;
  height: 5px;
  margin: 0 2px;
  border-radius: 50%;
  background: #60a5fa;
}

.chat-input {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 10px;
  padding: 8px 8px 6px;
  border: 1px solid #dbe5f2;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.08);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.chat-input:focus-within {
  border-color: var(--primary-500, #3b82f6);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.1), 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.chat-textarea {
  flex: 1;
  min-height: 34px;
  max-height: 118px;
  resize: none;
  padding: 4px 6px;
  border: 0;
  outline: none;
  background: transparent;
  color: #0f172a;
  font-size: 13.5px;
  line-height: 1.5;
  scrollbar-width: none;
}

.chat-textarea::-webkit-scrollbar {
  display: none;
}

.chat-input-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.chat-tool {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border: 1px solid rgba(96, 165, 250, 0.35);
  border-radius: 999px;
  background: rgba(248, 251, 255, 0.9);
  color: #2563eb;
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.chat-tool:hover {
  border-color: #3b82f6;
  background: #eff6ff;
}

.chat-image-preview {
  position: relative;
  width: 64px;
  margin-bottom: 6px;
}

.chat-image-preview img {
  width: 64px;
  height: 64px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  object-fit: cover;
}

.preview-remove {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: #475569;
  color: #fff;
  cursor: pointer;
}

.preview-remove:hover {
  background: #ef4444;
}

.q-image {
  display: block;
  max-width: 220px;
  max-height: 150px;
  margin-bottom: 6px;
  border-radius: 10px;
}

.chat-send {
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 50%;
  color: #fff;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.25);
  cursor: pointer;
}

.chat-send:disabled {
  cursor: not-allowed;
  opacity: 0.45;
  box-shadow: none;
}

.dock-materials {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dock-loading,
.dock-empty {
  margin: auto;
  color: #64748b;
}

.material-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px;
  border: 1px solid rgba(37, 99, 235, 0.1);
  border-radius: 16px;
  color: inherit;
  background: #fff;
  text-decoration: none;
}

.material-icon {
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 13px;
  color: #2563eb;
  background: #eff6ff;
}

.material-copy {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.material-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #0f172a;
  font-weight: 800;
}

.material-meta {
  color: #94a3b8;
  font-size: 12px;
}

.material-open {
  color: #94a3b8;
}

.dock-script-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px;
}

.dock-script-summary > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.dock-script-summary strong {
  color: #0f172a;
  font-size: 16px;
}

.dock-script-summary span {
  color: #94a3b8;
  font-size: 12px;
}

.dock-script-progress {
  padding: 7px 10px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 999px;
  color: #2563eb !important;
  background: #eff6ff;
  font-weight: 800;
}

.dock-script-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dock-script-item {
  width: 100%;
  padding: 13px 14px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 14px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.dock-script-item.active {
  border-color: rgba(37, 99, 235, 0.4);
  background: linear-gradient(145deg, #eff6ff, #ffffff);
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.1);
}

.dock-script-item-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 850;
}

.dock-script-audio {
  padding: 3px 8px;
  border-radius: 999px;
  color: #64748b;
  background: #f1f5f9;
  font-size: 12px;
}

.dock-script-audio.ready {
  color: #16a34a;
  background: #ecfdf3;
}

.dock-script-text {
  display: -webkit-box;
  overflow: hidden;
  margin-top: 8px;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  color: #64748b;
  font-size: 13px;
  line-height: 1.65;
}

.dock-script-item.active .dock-script-text {
  display: block;
  overflow: visible;
  color: #334155;
}

.full-lecture-empty {
  height: 100%;
  display: grid;
  place-items: center;
}

.chat-md :deep(p) {
  margin: 0 0 8px;
}

.chat-md :deep(p:last-child) {
  margin-bottom: 0;
}

@media (max-width: 1024px) {
  .learn-shell {
    min-height: 0;
  }

  .tree-node {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }

  .node-actions {
    justify-content: flex-start;
  }

  .tree-node.is-child {
    margin-left: 16px;
  }

  .content-head {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
