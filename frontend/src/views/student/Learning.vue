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
                  <div class="lecture-progress">
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
                <template v-if="dockTab === 'chat'">
                  <button class="dock-mini-btn" title="新会话" @click="newChatSession">
                    <el-icon :size="13"><Plus /></el-icon>
                  </button>
                  <button class="dock-mini-btn" title="历史会话" @click="chatHistoryOpen = !chatHistoryOpen">
                    <el-icon :size="13"><Clock /></el-icon>
                  </button>
                </template>
                <button class="dock-close" title="收起" @click="dockVisible = false">
                  <el-icon><Close /></el-icon>
                </button>
              </div>

              <div v-show="dockTab === 'chat'" class="dock-chat">
                <div v-if="chatHistoryOpen" class="chat-history-panel">
                  <button
                    v-for="s in chatSessions"
                    :key="s.id"
                    class="chat-history-item"
                    :class="{ active: s.id === chatSessionId }"
                    @click="switchChatSession(s.id)"
                  >
                    <span class="chat-history-q">{{ s.title || '新会话' }}</span>
                    <span class="chat-history-n">{{ s.record_count }} 条</span>
                  </button>
                  <div v-if="!chatSessions.length" class="chat-history-empty">暂无历史会话</div>
                </div>
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
                  <div v-for="(m, i) in chatMessages" :key="i" class="chat-row" :class="m.role" @click="onChatAreaClick">
                    <div class="chat-bubble" :class="{ bare: m.imageOnly }">
                      <span v-if="m.streaming && !m.content" class="chat-typing"><i></i><i></i><i></i></span>
                      <div v-else-if="m.role === 'assistant'" class="chat-text chat-md" v-html="renderMd(m.content + (m.streaming ? ' ▍' : ''))"></div>
                      <div v-else class="chat-text">
                        <img v-if="m.image" :src="m.image" class="q-image" alt="提问图片" />
                        <template v-if="!m.imageOnly">{{ m.content }}</template>
                      </div>
                      <!-- 参考来源须为独立 v-if：若插在 v-else-if 与 v-else 之间会抢走用户消息的 v-else 分支 -->
                      <div v-if="m.role === 'assistant' && m.historyDropped && !m.streaming" class="chat-note">对话较长，已省略部分早期内容</div>
                      <div v-if="m.role === 'assistant' && m.rewritten && !m.streaming" class="chat-note">已按上下文理解检索：{{ m.rewritten }}</div>
                      <CitedSources
                        v-if="m.role === 'assistant' && m.cited_chunks?.length && !m.streaming"
                        :cited="m.cited_chunks"
                        :highlight="flashNums"
                      />
                      <div v-if="m.role === 'assistant' && !m.streaming && m.content" class="chat-actions">
                        <QaFeedback :record-id="m.mid" v-model="m.feedback" />
                      </div>
                    </div>
                  </div>
                </div>
                <div class="chat-input">
                  <div v-if="chatImage && visionSupported" class="chat-image-preview">
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
                    <template v-if="visionSupported">
                      <input ref="chatFileRef" type="file" accept="image/*" hidden @change="onPickChatImage" />
                      <button class="chat-tool" title="提交图片提问" @click="chatFileRef?.click()">
                        <el-icon :size="15"><Picture /></el-icon>
                        图片
                      </button>
                    </template>
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

    <Teleport to="body">
      <div v-if="practiceVisible" class="full-lecture-page">
        <header class="full-lecture-header">
          <div class="full-lecture-title-wrap">
            <div class="full-lecture-icon">
              <el-icon><EditPen /></el-icon>
            </div>
            <div class="full-lecture-title-copy">
              <div class="full-lecture-title-line">
                <h1>章节练习</h1>
                <span class="full-lecture-kicker">{{ activeCourseName }}</span>
              </div>
              <p>{{ current?.title || '请选择章节' }}</p>
            </div>
          </div>
          <div class="full-lecture-actions">
            <div class="full-lecture-stats">
              <span><strong>{{ questions.length }}</strong> 道题</span>
              <span v-if="!submitted">已答 <strong>{{ answeredCount }}</strong></span>
              <el-tag v-if="submitted" type="success" effect="light" round>
                答对 {{ result.correct }}/{{ result.total }}
              </el-tag>
            </div>
            <el-button class="full-lecture-soft-btn" @click="closePractice">退出练习</el-button>
          </div>
        </header>

        <div class="practice-body">
          <div v-if="practiceLoading" class="practice-loading">
            <el-icon class="is-loading"><Loading /></el-icon> 正在加载题目...
          </div>
          <el-empty v-else-if="!questions.length" description="本章还没有已发布的练习题" />
          <template v-else>
            <el-card v-for="(q, i) in questions" :key="q.id" class="q-card practice-card" shadow="never">
              <div class="q-stem">
                <span class="q-idx">{{ i + 1 }}.</span>
                <el-tag size="small" effect="light">{{ q.qtype_display }}</el-tag>
                <span>{{ q.stem }}</span>
                <span class="practice-score">（{{ q.score }} 分）</span>
              </div>

              <el-radio-group v-if="q.qtype === 'single' || q.qtype === 'judge'" v-model="answers[q.id]" :disabled="submitted">
                <el-radio v-for="opt in q.options" :key="opt.key" :value="opt.key" class="opt">
                  <span class="opt-key">{{ opt.key }}.</span> {{ opt.text }}
                </el-radio>
              </el-radio-group>

              <el-checkbox-group v-else-if="q.qtype === 'multi'" v-model="answers[q.id]" :disabled="submitted">
                <el-checkbox v-for="opt in q.options" :key="opt.key" :value="opt.key" class="opt">
                  <span class="opt-key">{{ opt.key }}.</span> {{ opt.text }}
                </el-checkbox>
              </el-checkbox-group>

              <!-- 填空（多空题按空数量渲染输入框） -->
              <template v-else-if="q.qtype === 'blank'">
                <el-input
                  v-for="(_, blankIndex) in answers[q.id]"
                  :key="blankIndex"
                  v-model="answers[q.id][blankIndex]"
                  :placeholder="`第 ${blankIndex + 1} 空`"
                  :disabled="submitted"
                  class="blank-item"
                />
              </template>

              <el-input
                v-else
                v-model="answers[q.id]"
                type="textarea"
                :rows="4"
                placeholder="请作答"
                :disabled="submitted"
                resize="none"
              />

              <div v-if="submitted && feedback[q.id]" class="fb" :class="feedback[q.id].is_correct === null ? '' : feedback[q.id].is_correct ? 'ok' : (Number(feedback[q.id].score) > 0 ? 'part' : 'no')">
                <template v-if="feedback[q.id].is_correct === null">
                  <div>本题为简答题，请参考以下答案自行核对：</div>
                  <div class="fb-ana">参考答案：{{ fmt(feedback[q.id].correct_answer) }}</div>
                </template>
                <template v-else>
                  <div>{{ fbResultText(feedback[q.id]) }}</div>
                </template>
                <div v-if="feedback[q.id].analysis" class="fb-ana">解析：{{ feedback[q.id].analysis }}</div>
              </div>
            </el-card>

            <div class="practice-bar">
              <el-button v-if="!submitted" type="primary" size="large" :loading="submitting" @click="submitPractice">
                提交练习（{{ answeredCount }}/{{ questions.length }}）
              </el-button>
              <el-button v-else size="large" @click="resetPractice">重新作答</el-button>
            </div>
          </template>
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
                <el-tag
                  v-if="progressInfo(row.node.id)"
                  size="small"
                  :type="progressInfo(row.node.id).type"
                  effect="light"
                  round
                >{{ progressInfo(row.node.id).label }}</el-tag>
              </div>
            </div>
            <div class="node-actions">
              <div class="node-action-group">
                <el-button class="node-action-btn" :icon="VideoPlay" @click.stop="openChapter(row.node, '')">完整讲解</el-button>
                <el-button class="node-action-btn" :icon="Microphone" @click.stop="openChapter(row.node, 'script')">讲稿</el-button>
                <el-button class="node-action-btn" :icon="EditPen" @click.stop="openPracticePanel(row.node)">章节练习</el-button>
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
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Microphone, ArrowLeft, ArrowRight, CircleCheck, CircleClose, VideoPlay,
  Document, ChatDotRound, Folder, Close, MagicStick, Promotion, Picture, Loading,
  Right, VideoPause, EditPen, Plus, Clock,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { listClasses } from '@/api/classroom'
import { listCatalogs, listPpts, listVideos, listWatchProgress, reportVideoProgress } from '@/api/course'
import { chapterProgress } from '@/utils/learningProgress'
import { listQuestions, practiceSubmit } from '@/api/question'
import { listMaterials, getQaVisionCapability } from '@/api/knowledge'
import { renderQaAnswer } from '@/utils/markdown'
import CitedSources from '@/components/qa/CitedSources.vue'
import QaFeedback from '@/components/qa/QaFeedback.vue'
import { listQaSessions, listQaSessionRecords } from '@/api/knowledge'
import { blankAnswerText } from '@/utils/blank-answer'

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
  chatSessionId.value = null
  chatSessions.value = []
  stopPlayer()
  const data = await listCatalogs({ course: courseId.value, tree: 1 })
  tree.value = data.results ?? data
  loadWatchProgress()
}

// ---- 学习进度（断点续播 / 完成状态） ----
const progressMap = ref({}) // catalog_id -> 进度记录
const pageDurations = ref({}) // 当前章节每页音频时长（页索引 -> 秒）
const pageWatched = ref({}) // 当前章节每页已看时长（页索引 -> 秒，取最大观看位置）
const currentVideoId = ref(null)
let watchAccum = 0 // 距上次上报累计观看秒数
let lastTickTime = -1 // 上次 timeupdate 的播放位置
let progressTimer = null
let resumePending = false
let resumePosition = 0

function progressOf(catalogId) {
  return progressMap.value[catalogId] || null
}

// 章节徽章：已完成 / 进度 N%（按页统计，未播放的页不计入）/ 学习中
function progressInfo(catalogId) {
  const p = progressOf(catalogId)
  if (!p) return null
  return chapterProgress(p)
}

async function loadWatchProgress() {
  try {
    const data = await listWatchProgress({ course: courseId.value })
    const rows = data.results ?? data
    const map = {}
    rows.forEach((p) => { map[p.catalog] = p })
    progressMap.value = map
  } catch {
    progressMap.value = {}
  }
}

async function flushProgress(completed = false) {
  if (!currentVideoId.value || !lectureVisible.value) {
    watchAccum = 0
    return
  }
  const delta = Math.round(watchAccum)
  watchAccum = 0
  const payload = {
    last_page: playerPageIndex.value,
    last_position: Math.round(playerCurrent.value * 10) / 10,
    duration_delta: delta,
    completed,
    page_count: pages.value.length,
  }
  if (Object.keys(pageDurations.value).length) {
    payload.page_durations = pageDurations.value
  }
  if (Object.keys(pageWatched.value).length) {
    payload.page_watched = pageWatched.value
  }
  try {
    const saved = await reportVideoProgress(currentVideoId.value, payload)
    if (saved && current.value) {
      progressMap.value = { ...progressMap.value, [current.value.id]: saved }
    }
  } catch {
    // 进度上报失败不打断学习
  }
}

function startProgressTimer() {
  stopProgressTimer()
  progressTimer = setInterval(() => {
    if (playerAutoPlay.value) flushProgress()
  }, 10000)
}

function stopProgressTimer() {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
}

// 章节动作：'' 完整讲解 / 'script' 讲稿 / 'chat' AI 问答
// ---- 章节 AI 问答会话管理 ----
async function loadChapterSessions(node) {
  const catalogId = node.id
  chatMessages.value = []
  chatSessionId.value = null
  let list = []
  try {
    const data = await listQaSessions({ course: courseId.value, catalog: catalogId })
    list = data.results ?? data
  } catch {
    list = []
  }
  // 竞态守卫：拉取期间用户已切到其他章节，放弃恢复
  if (current.value?.id !== catalogId) return
  chatSessions.value = list
  // 期间用户已在当前章节开聊（新会话首轮），不覆盖
  if (list.length && !chatMessages.value.length) {
    await switchChatSession(list[0].id)
  }
}

async function switchChatSession(id) {
  chatSessionId.value = id
  chatHistoryOpen.value = false
  try {
    const rows = await listQaSessionRecords(id)
    const list = rows.results ?? rows
    chatMessages.value = list.flatMap((r) => ([
      { role: 'user', content: r.question },
      {
        role: 'assistant',
        content: r.answer,
        cited_chunks: r.cited_chunks,
        mid: r.id,
        feedback: r.feedback || 0,
        rewritten: r.rewritten_question || '',
      },
    ]))
  } catch {
    chatMessages.value = []
  }
  scrollChatToBottom()
}

function newChatSession() {
  chatSessionId.value = null
  chatMessages.value = []
  chatHistoryOpen.value = false
}

async function openChapter(node, action = '') {
  stopPlayer()
  dockVisible.value = false
  if (current.value?.id !== node.id) {
    current.value = node
    tab.value = 'learn'
    pageIdx.value = 0
    pages.value = []
    scripts.value = []
    pageDurations.value = {}
    pageWatched.value = {}
    // 切章节：后台拉该章最近问答会话续聊（不阻塞课件加载）
    loadChapterSessions(node)
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
  currentVideoId.value = null
  try {
    const ppt = await listPpts({ catalog: current.value.id })
    const pptList = ppt.results ?? ppt
    const active = pptList.find((p) => p.is_active) || pptList[0]
    pages.value = active?.parsed_pages || []
    const vid = await listVideos({ catalog: current.value.id })
    const vids = vid.results ?? vid
    scripts.value = vids[0]?.scripts || []
    currentVideoId.value = vids[0]?.id || null
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
// AI 问答会话：chatSessionId 为当前 QASession（null = 新会话，首次提问由后端创建）；
// 会话与章节绑定——切章节时拉该章最近会话续聊，跨章节串话从机制上消除
const chatSessionId = ref(null)
const chatSessions = ref([])
const chatHistoryOpen = ref(false)

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
// 问答图片上传入口：按对话模型的视觉能力显示（平台级配置，挂载时查一次）；
// 拉取失败默认 false——没有入口优于用户发送图片后被接口拒绝
const visionSupported = ref(false)
watch(visionSupported, (on) => { if (!on) chatImage.value = '' })
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
  // 断点续播：恢复到上次学习的页码与页内位置；每页时长/已看数据做种子
  const saved = progressOf(current.value.id)
  if (saved) {
    pageDurations.value = { ...(saved.page_durations || {}) }
    pageWatched.value = { ...(saved.page_watched || {}) }
  }
  if (saved && saved.status !== 'completed') {
    playerPageIndex.value = Math.min(saved.last_page || 0, Math.max(pages.value.length - 1, 0))
    resumePosition = saved.last_position || 0
    resumePending = resumePosition > 0
    pageIdx.value = playerPageIndex.value
  } else {
    playerPageIndex.value = pageIdx.value || 0
  }
  lectureVisible.value = true
  startProgressTimer()
  if (tabName) {
    dockTab.value = tabName
    dockVisible.value = true
    if (tabName === 'materials') ensureMaterials()
    if (tabName === 'script') scrollCurrentScriptIntoView()
  }
}

function closeLecture() {
  flushProgress()
  stopProgressTimer()
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
  flushProgress()
  stopPlayer()
  playerPageIndex.value -= 1
}

function nextPlayerPage() {
  if (playerPageIndex.value >= pages.value.length - 1) return
  flushProgress()
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
  lastTickTime = -1
}

function onPlayerPlay() {
  playerAutoPlay.value = true
}

function onPlayerAudioPause() {
  playerAutoPlay.value = false
}

function onPlayerTimeUpdate(e) {
  const now = e.target?.currentTime || 0
  // 正常播放累加学习时长；拖动进度条产生的跳变不计入
  if (lastTickTime >= 0) {
    const delta = now - lastTickTime
    if (delta > 0 && delta <= 2) watchAccum += delta
  }
  lastTickTime = now
  playerCurrent.value = now
  // 每页已看时长取最大观看位置，未播放的页不计入
  const idx = playerPageIndex.value
  if (now > (pageWatched.value[idx] || 0)) {
    pageWatched.value = { ...pageWatched.value, [idx]: Math.round(now * 10) / 10 }
  }
}

function onPlayerLoadedMeta(e) {
  const d = e.target?.duration || 0
  playerDuration.value = d
  playerCurrent.value = 0
  lastTickTime = -1
  // 记录每页音频时长，上报后用于计算章节总时长
  if (d > 0 && Number.isFinite(d)) {
    pageDurations.value = { ...pageDurations.value, [playerPageIndex.value]: Math.round(d * 10) / 10 }
  }
  // 断点续播：恢复到上次页内播放位置
  if (resumePending && e.target && resumePosition < (playerDuration.value || Infinity)) {
    e.target.currentTime = resumePosition
    playerCurrent.value = resumePosition
    lastTickTime = resumePosition
  }
  resumePending = false
}

function onPlayerAudioEnded() {
  flushProgress()
  const next = findNextAudioPage(playerPageIndex.value)
  if (next >= 0) {
    playerPageIndex.value = next
    nextTick(() => playerAudioRef.value?.play?.())
  } else {
    // 整章连播结束，标记完成
    flushProgress(true)
    stopPlayer()
    ElMessage.success('本章讲解已学习完成')
  }
}

function selectScriptPage(item) {
  const index = pages.value.findIndex((page) => page.page === item.page)
  if (index < 0) return
  flushProgress()
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
  const idx = chatMessages.value.push({ role: 'assistant', content: '', streaming: true, mid: null, feedback: 0 }) - 1
  scrollChatToBottom()
  // 参考来源缓冲：meta 事件先于/穿插 delta 到达，正文结束后统一挂到消息上
  let pendingCited = []
  let pendingRewritten = ''
  let droppedLevel = 0
  let doneRecordId = null
  try {
    const token = localStorage.getItem('access_token')
    const resp = await fetch('/api/qa-records/ask-stream/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        course: courseId.value,
        catalog: current.value?.id,
        question: text,
        ...(chatSessionId.value ? { session_id: chatSessionId.value } : {}),
        ...(img ? { image: img } : {}),
      }),
    })
    if (!resp.ok || !resp.body) throw new Error('bad response')

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    // 渲染节流：delta 先进缓冲，60ms 批量落一次 DOM，避免逐 token 全量 markdown 重渲染
    let pendingText = ''
    let flushTimer = null
    const flushAnswer = () => {
      flushTimer = null
      if (!pendingText) return
      chatMessages.value[idx].content += pendingText
      pendingText = ''
      scrollChatIfNearBottom()
    }
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
        if (evt.type === 'meta') {
          pendingCited = evt.cited || []
          pendingRewritten = evt.rewritten_question || ''
          adoptChatSessionId(evt.session_id, text)
        } else if (evt.type === 'history_dropped') {
          // 上下文超限已分级降级：记录级别，正文结束后提示
          droppedLevel = evt.level || 4
        } else if (evt.type === 'delta') {
          pendingText += evt.text || ''
          if (!flushTimer) flushTimer = setTimeout(flushAnswer, 60)
        } else if (evt.type === 'done') {
          doneRecordId = evt.record_id || null
        } else if (evt.type === 'error') {
          pendingText += `\n[出错] ${evt.message || '生成失败'}`
        }
      })
    }
    if (flushTimer) clearTimeout(flushTimer)
    flushAnswer()
  } catch {
    chatMessages.value[idx].content = chatMessages.value[idx].content || '抱歉，AI 助教暂时没有响应，请稍后再试。'
  } finally {
    chatMessages.value[idx].streaming = false
    chatMessages.value[idx].mid = doneRecordId
    // 参考来源在正文输出完（或出错收尾）后才挂到消息上，避免流式期间闪烁
    chatMessages.value[idx].cited_chunks = pendingCited
    chatMessages.value[idx].rewritten = pendingRewritten
    chatMessages.value[idx].historyDropped = droppedLevel
    chatLoading.value = false
    scrollChatToBottom()
  }
}

// 新会话首次提问：meta 带回后端创建的 session_id，认领为当前会话并插入历史列表
function adoptChatSessionId(sessionId, firstQuestion) {
  if (!sessionId || chatSessionId.value === sessionId) return
  const isNew = chatSessionId.value === null
  chatSessionId.value = sessionId
  if (isNew) {
    chatSessions.value = [
      {
        id: sessionId,
        title: firstQuestion.slice(0, 30),
        record_count: 0,
        last_message_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      ...chatSessions.value,
    ]
  }
}

function scrollChatToBottom() {
  nextTick(() => {
    const el = chatScrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

// 流式期间仅在用户本来就接近底部时跟随滚动，避免打断上翻阅读
function scrollChatIfNearBottom() {
  const el = chatScrollRef.value
  if (!el) return
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 120) scrollChatToBottom()
}

const renderMd = renderQaAnswer

// 回答中 [N] 引用上标的点击处理：滚动到本消息参考来源并闪烁高亮对应编号
const flashNums = ref(new Set())
let flashTimer = null
function onChatAreaClick(e) {
  const sup = e.target.closest('.cite-sup')
  if (!sup) return
  const n = Number(sup.dataset.cite)
  if (!n) return
  const sourcesEl = sup.closest('.chat-row')?.querySelector('.cited-sources')
  flashNums.value = new Set([n])
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = setTimeout(() => { flashNums.value = new Set() }, 1600)
  sourcesEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
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
const practiceVisible = ref(false)
const practiceLoading = ref(false)
const questions = ref([])
const answers = reactive({})
const feedback = reactive({})
const submitted = ref(false)
const submitting = ref(false)
const result = reactive({ total: 0, correct: 0 })

async function openPracticePanel(node) {
  if (current.value?.id !== node.id) {
    current.value = node
  }
  practiceVisible.value = true
  await loadPractice()
}

function closePractice() {
  practiceVisible.value = false
}

async function loadPractice() {
  practiceLoading.value = true
  resetState()
  try {
    const data = await listQuestions({ course: courseId.value, catalog: current.value.id, status: 'published' })
    questions.value = data.results ?? data
    questions.value.forEach((q) => {
      answers[q.id] = q.qtype === 'multi' ? [] : q.qtype === 'blank' ? new Array(Math.max(1, q.blank_count || 1)).fill('') : ''
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
    answers[q.id] = q.qtype === 'multi' ? [] : q.qtype === 'blank' ? new Array(Math.max(1, q.blank_count || 1)).fill('') : ''
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
  if (a.blanks) return blankAnswerText(a)
  if (a.text) return a.text
  return '-'
}
// 练习结果文案：全对/部分空命中（按空赋分）/全错
function fbResultText(fb) {
  if (fb.is_correct) return '回答正确'
  if (Number(fb.score) > 0) return `部分正确，正确答案：${fmt(fb.correct_answer)}`
  return `回答错误，正确答案：${fmt(fb.correct_answer)}`
}
const answeredCount = computed(() => {
  return questions.value.filter((q) => {
    const v = answers[q.id]
    if (q.qtype === 'multi') return Array.isArray(v) && v.length > 0
    if (q.qtype === 'blank') return Array.isArray(v) && v.some((x) => String(x).trim())
    return String(v ?? '').trim() !== ''
  }).length
})
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

// 视觉能力拉取：挂载时查一次；标签页切回时重查——
// 管理端改「支持图片」开关后，已打开的学习页不会自动响应，
// 用户切回本标签即拿到新值（图片入口随之显隐）
async function loadVisionCapability() {
  try {
    const res = await getQaVisionCapability()
    visionSupported.value = Boolean(res?.supports_vision)
  } catch { /* 拉取失败：保持隐藏 */ }
}
function onVisibilityChange() {
  if (document.visibilityState === 'visible') loadVisionCapability()
}

onMounted(async () => {
  await loadCourses()
  await loadVisionCapability()
  document.addEventListener('visibilitychange', onVisibilityChange)
})
onUnmounted(() => {
  stopProgressTimer()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
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
.blank-item {
  max-width: 420px;
  margin-bottom: 10px;
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
.fb.part {
  background: #fdf6ec;
  color: #e6a23c;
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

.practice-body {
  min-height: 0;
  overflow-y: auto;
  padding: 26px clamp(20px, 12vw, 240px) 60px;
}

.practice-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 80px 0;
  color: #64748b;
}

.practice-card {
  border-radius: 16px;
}

.practice-score {
  color: #94a3b8;
  font-size: 13px;
}

.practice-bar {
  justify-content: center;
  padding: 18px 0 10px;
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
  cursor: default;
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
  gap: 8px;
}
/* margin-left:auto 让发送按钮永远贴右：vision 开启时图片按钮贴左、发送贴右；
   vision 关闭后 chat-tool 消失，发送按钮仍靠右（space-between 单子元素会落左） */
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
  /* margin-left:auto 让发送按钮永远贴右（vision 关闭后 chat-tool 消失也不会落左） */
  margin-left: auto;
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

.chat-note {
  margin-top: 6px;
  color: #94a3b8;
  font-size: 11.5px;
  line-height: 1.5;
}

.chat-md :deep(.cite-sup) {
  color: #2563eb;
  font-weight: 600;
  cursor: pointer;
  padding: 0 1px;
}

.chat-md :deep(.cite-sup):hover {
  text-decoration: underline;
}

.dock-mini-btn {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s ease;
}

.dock-mini-btn:hover {
  background: var(--gray-100, #f1f5f9);
  color: #2563eb;
}

.chat-history-panel {
  max-height: 180px;
  overflow-y: auto;
  border-bottom: 1px solid #e2e8f0;
  padding: 6px;
}

.chat-history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 7px 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}

.chat-history-item:hover {
  background: var(--gray-100, #f1f5f9);
}

.chat-history-item.active {
  background: var(--primary-50, #eff6ff);
}

.chat-history-q {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #334155;
  font-size: 12px;
}

.chat-history-n {
  flex-shrink: 0;
  color: #94a3b8;
  font-size: 11px;
}

.chat-history-empty {
  padding: 14px 0;
  color: #94a3b8;
  font-size: 12px;
  text-align: center;
}

.chat-actions {
  margin-top: 6px;
  display: flex;
  justify-content: flex-end;
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
