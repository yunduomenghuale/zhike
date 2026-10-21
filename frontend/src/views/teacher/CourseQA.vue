<template>
  <div class="qa-page">
    <div class="qa-shell">
      <div class="qa-topbar">
        <div class="qa-title-wrap">
          <span class="qa-title-icon">
            <el-icon :size="16"><ChatDotRound /></el-icon>
          </span>
          <div class="qa-title">AI 问答</div>
          <span class="qa-badge">知识库 RAG</span>
        </div>
        <div class="topbar-actions">
          <button class="action-btn primary" @click="newChat">
            <el-icon :size="14"><Plus /></el-icon>
            新建会话
          </button>
          <button class="action-btn ghost" @click="historyOpen = !historyOpen">
            <el-icon :size="14"><Clock /></el-icon>
            历史记录
          </button>
        </div>
      </div>

      <div v-if="historyOpen" class="history-mask" @click="historyOpen = false"></div>
      <div v-show="historyOpen" class="history-panel">
        <div class="side-search">
          <el-input
            v-model="keyword"
            size="small"
            clearable
            placeholder="搜索历史会话…"
            :prefix-icon="Search"
          />
        </div>
        <div class="side-list">
          <div
            v-for="s in sessionItems"
            :key="s.id"
            class="side-item"
            :class="{ active: s.id === viewSessionKey }"
            @click="switchSession(s.id)"
          >
            <span class="side-item-q">{{ s.title || '新会话' }}</span>
            <span class="side-item-time">{{ s.record_count }} 条对话 · {{ fmtSideTime(s.last_message_at || s.updated_at) }}</span>
            <button class="side-item-del" title="删除会话" @click="removeSession(s, $event)">
              <el-icon :size="12"><Close /></el-icon>
            </button>
          </div>
          <div v-if="!sessionItems.length" class="side-empty">
            {{ keyword ? '没有匹配的会话' : '暂无历史会话' }}
          </div>
        </div>
      </div>

      <div ref="listRef" class="chat-list">
        <div v-if="!messages.length" class="chat-empty">
          <div class="chat-empty-hero">
            <span class="chat-empty-glow"></span>
            <div class="chat-empty-icon">
              <el-icon><MagicStick /></el-icon>
            </div>
          </div>
          <div class="empty-text">还没有提问</div>
          <div class="empty-tip">基于课程资料即时解答，可以试试：</div>
          <div class="empty-suggestions">
            <button v-for="s in suggestions" :key="s" class="suggestion-chip" @click="ask(s)">{{ s }}</button>
          </div>
        </div>

        <div v-for="(m, i) in messages" :key="i" class="qa-item" @click="onAnswerAreaClick">
          <div class="message question">
            <div class="message-content">
              <div class="bubble question-bubble" :class="{ bare: m.imageOnly }">
                <img v-if="m.image" :src="m.image" class="q-image" alt="提问图片" />
                <span v-if="!m.imageOnly">{{ m.question }}</span>
              </div>
            </div>
          </div>

          <div class="message answer">
            <div class="message-content">
              <div class="answer-plain">
                <div v-if="m.answer" class="answer-md" v-html="renderMd(m.answer + (m.streaming ? ' ▍' : ''))"></div>
                <div v-else class="answer-thinking">
                  <el-icon class="is-loading" :size="15"><Loading /></el-icon> 正在检索课程资料…
                </div>
                <div v-if="m.historyDropped" class="qa-note">对话较长，已省略部分早期内容</div>
                <div v-if="m.rewritten && !m.streaming" class="qa-note">已按上下文理解检索：{{ m.rewritten }}</div>
                <CitedSources v-if="m.cited_chunks?.length" :cited="m.cited_chunks" :highlight="flashNums" />
                <div v-if="!m.streaming && m.answer" class="qa-actions">
                  <QaFeedback :record-id="m.mid" v-model="m.feedback" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="input-dock">
        <div v-if="imageData" class="dock-image-preview">
          <img :src="imageData" alt="待发送图片" />
          <button class="preview-remove" title="移除图片" @click="imageData = ''">
            <el-icon :size="11"><Close /></el-icon>
          </button>
        </div>
        <el-input
          v-model="question"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 5 }"
          resize="none"
          class="dock-textarea"
          placeholder="发消息，向课程 AI 提问…（Enter 发送，Shift+Enter 换行）"
          @keydown.enter.exact.prevent="ask()"
        />
        <div class="dock-toolbar">
          <div class="dock-chips">
            <input ref="fileInputRef" type="file" accept="image/*" hidden @change="onPickImage" />
            <button class="dock-chip tool-chip" title="提交图片提问" @click="fileInputRef?.click()">
              <el-icon :size="15"><Picture /></el-icon>
              图片
            </button>
          </div>
          <el-button
            type="primary"
            circle
            :loading="asking"
            :icon="Promotion"
            class="dock-send"
            title="发送"
            @click="ask()"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Promotion, MagicStick, Loading, Search, Clock, Picture, Close, Plus,
} from '@element-plus/icons-vue'
import { renderQaAnswer } from '@/utils/markdown'
import CitedSources from '@/components/qa/CitedSources.vue'
import QaFeedback from '@/components/qa/QaFeedback.vue'
import { listQaSessions, listQaSessionRecords, deleteQaSession } from '@/api/knowledge'

const renderMd = renderQaAnswer

// 回答中 [N] 引用上标的点击处理：滚动到本消息参考来源并闪烁高亮对应编号
const flashNums = ref(new Set())
let flashTimer = null
function onAnswerAreaClick(e) {
  const sup = e.target.closest('.cite-sup')
  if (!sup) return
  const n = Number(sup.dataset.cite)
  if (!n) return
  const sourcesEl = sup.closest('.qa-item')?.querySelector('.cited-sources')
  flashNums.value = new Set([n])
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = setTimeout(() => { flashNums.value = new Set() }, 1600)
  sourcesEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

const route = useRoute()
const courseId = Number(route.params.id)

const messages = ref([])
const question = ref('')
const asking = ref(false)
const listRef = ref(null)
const keyword = ref('')
const historyOpen = ref(false)
const imageData = ref('')
const fileInputRef = ref(null)

// 会话制：sessions 来自 QASession API（后端持久化，含历史回填会话）；
// currentSessionId 为当前会话（null = 新会话，首次提问时由后端创建）
const sessions = ref([])
const currentSessionId = ref(null)
const viewSessionKey = ref(null)

const sessionItems = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  let list = sessions.value
  if (kw) list = list.filter((s) => (s.title || '').toLowerCase().includes(kw))
  return list
})

function newChat() {
  currentSessionId.value = null
  viewSessionKey.value = null
  messages.value = []
  historyOpen.value = false
}

async function switchSession(id) {
  historyOpen.value = false
  viewSessionKey.value = id
  currentSessionId.value = id
  try {
    const rows = await listQaSessionRecords(id)
    messages.value = (rows.results ?? rows).map((r) => ({
      mid: r.id,
      question: r.question,
      answer: r.answer,
      cited_chunks: r.cited_chunks,
      feedback: r.feedback || 0,
      rewritten: r.rewritten_question || '',
      created_at: r.created_at,
    }))
  } catch {
    messages.value = []
  }
  scrollToBottom()
}

async function removeSession(s, e) {
  e.stopPropagation()
  try {
    await deleteQaSession(s.id)
  } catch {
    return ElMessage.error('删除会话失败')
  }
  sessions.value = sessions.value.filter((x) => x.id !== s.id)
  if (currentSessionId.value === s.id) newChat()
}

function onPickImage(e) {
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
      imageData.value = file.type === 'image/png'
        ? canvas.toDataURL('image/png')
        : canvas.toDataURL('image/jpeg', 0.85)
    }
    img.src = reader.result
  }
  reader.readAsDataURL(file)
}

const suggestions = [
  '这门课程主要讲哪些内容？',
  '帮我总结一下课程资料里的重点知识',
  '初学者应该先掌握哪些基础概念？',
]

function fmtSideTime(t) {
  if (!t) return ''
  const d = new Date(t)
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  const startOf = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate())
  const days = Math.round((startOf(now) - startOf(d)) / 86400000)
  if (days <= 0) return `今天 ${hm}`
  if (days === 1) return `昨天 ${hm}`
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}

function scrollToBottom() {
  nextTick(() => {
    if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
  })
}

// 流式期间仅在用户本来就接近底部时跟随滚动，避免打断上翻阅读
function scrollIfNearBottom() {
  const el = listRef.value
  if (!el) return
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 120) scrollToBottom()
}

async function loadSessions() {
  try {
    // catalog 空串 = 只看课程级会话（章节面板内的提问与这里的会话互不混入）
    const data = await listQaSessions({ course: courseId, catalog: '' })
    sessions.value = data.results ?? data
  } catch {
    sessions.value = []
  }
}

async function ask(preset) {
  const q = (preset ?? question.value).trim()
  const img = imageData.value
  if ((!q && !img) || asking.value) return
  const text = q || '请描述并解读这张图片'
  asking.value = true
  question.value = ''
  imageData.value = ''
  const msg = {
    mid: null, // done 事件带回 record_id 后填充（反馈按钮依赖）
    question: text,
    image: img,
    imageOnly: !q,
    answer: '',
    cited_chunks: [],
    feedback: 0,
    created_at: new Date().toISOString(),
    streaming: true,
  }
  messages.value.push(msg)
  scrollToBottom()
  // 必须经响应式数组写入才触发渲染（改原始对象绕过代理 = 假流式）
  const msgIndex = messages.value.length - 1
  const patchMsg = (patch) => {
    messages.value[msgIndex] = { ...messages.value[msgIndex], ...patch }
  }
  // 参考来源先存不显示：正文流式输出完后（finally）再一次性展示
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
        course: courseId,
        question: text,
        ...(currentSessionId.value ? { session_id: currentSessionId.value } : {}),
        ...(img ? { image: img } : {}),
      }),
    })
    if (!resp.ok || !resp.body) throw new Error('bad response')

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    // 渲染节流：delta 先进缓冲，60ms 批量落一次 DOM，避免逐 token 全量重渲染
    let pendingText = ''
    let flushTimer = null
    const flushAnswer = () => {
      flushTimer = null
      if (!pendingText) return
      const next = messages.value[msgIndex].answer + pendingText
      pendingText = ''
      patchMsg({ answer: next })
      scrollIfNearBottom()
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
          adoptSessionId(evt.session_id, text)
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
    if (!messages.value[msgIndex].answer) {
      patchMsg({ answer: '抱歉，AI 助教暂时没有响应，请稍后再试。' })
    }
  } catch {
    if (!messages.value[msgIndex].answer) {
      patchMsg({ answer: '抱歉，AI 助教暂时没有响应，请稍后再试。' })
    }
  } finally {
    // 正文已输出完（或出错收尾），此时才展示参考来源并移除流式光标
    patchMsg({ mid: doneRecordId, cited_chunks: pendingCited, streaming: false, rewritten: pendingRewritten, historyDropped: droppedLevel })
    asking.value = false
    scrollToBottom()
  }
}

// 新会话首次提问：meta 带回后端创建的 session_id，认领为当前会话并插入历史面板
function adoptSessionId(sessionId, firstQuestion) {
  if (!sessionId || currentSessionId.value === sessionId) return
  const isNew = currentSessionId.value === null
  currentSessionId.value = sessionId
  viewSessionKey.value = sessionId
  if (isNew) {
    sessions.value = [
      {
        id: sessionId,
        title: firstQuestion.slice(0, 30),
        record_count: 0,
        last_message_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      ...sessions.value,
    ]
  }
}

onMounted(loadSessions)
</script>

<style scoped>
.qa-page {
  height: 100%;
  min-height: 560px;
  display: flex;
  flex-direction: column;
}

.qa-shell {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 14px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s ease;
}

.action-btn.primary {
  border: 0;
  color: #fff;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.28);
}

.action-btn.primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 9px 20px rgba(37, 99, 235, 0.36);
}

.action-btn.primary:active {
  transform: translateY(0) scale(0.97);
}

.action-btn.ghost {
  border: 1px solid rgba(219, 229, 242, 0.9);
  color: var(--gray-600);
  background: rgba(255, 255, 255, 0.85);
}

.action-btn.ghost:hover {
  border-color: rgba(96, 165, 250, 0.6);
  color: var(--primary-600);
  background: var(--primary-50);
  transform: translateY(-1px);
}

.action-btn.ghost:active {
  transform: translateY(0) scale(0.97);
}

/* 历史记录浮动面板 */
.history-mask {
  position: absolute;
  inset: 0;
  z-index: 9;
}

.history-panel {
  position: absolute;
  top: 58px;
  right: 16px;
  z-index: 10;
  display: flex;
  flex-direction: column;
  width: 320px;
  max-width: calc(100% - 32px);
  max-height: 62%;
  border: 1px solid var(--gray-200);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.18);
  overflow: hidden;
}

.side-search {
  display: flex;
  justify-content: center;
  padding: 12px 12px 8px;
}

/* 默认居中略窄，聚焦时向两侧平滑展开（与顶栏课程搜索一致） */
.side-search :deep(.el-input) {
  width: 86%;
  transition: width 0.28s ease;
}

.side-search:focus-within :deep(.el-input) {
  width: 100%;
}

.side-search :deep(.el-input__wrapper),
.side-search :deep(.el-input__wrapper:hover),
.side-search :deep(.el-input__wrapper.is-focus) {
  border-radius: 999px;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(239, 246, 255, 0.82));
  box-shadow:
    0 10px 22px rgba(37, 99, 235, 0.09),
    0 4px 10px rgba(15, 23, 42, 0.05),
    inset 0 1px 1px rgba(255, 255, 255, 0.98),
    inset 0 -1px 2px rgba(37, 99, 235, 0.08),
    0 0 0 1px rgba(37, 99, 235, 0.14) inset;
}

.side-search :deep(.el-input__inner) {
  color: var(--gray-900);
}

.side-search :deep(.el-input__inner::placeholder) {
  color: var(--gray-400);
}

.side-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  gap: 4px;
  align-content: start;
  padding: 0 8px 10px;
}

.side-item {
  position: relative;
  display: grid;
  gap: 4px;
  padding: 9px 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}

.side-item-del {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 18px;
  height: 18px;
  display: none;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--gray-400);
  cursor: pointer;
}

.side-item:hover .side-item-del {
  display: grid;
}

.side-item-del:hover {
  background: rgba(239, 68, 68, 0.12);
  color: var(--danger);
}

.side-item:hover {
  background: var(--gray-100);
}

.side-item-q {
  overflow: hidden;
  display: -webkit-box;
  color: var(--gray-700);
  font-size: 12.5px;
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.side-item-time {
  color: var(--gray-400);
  font-size: 11px;
}

.side-empty {
  padding: 26px 10px;
  color: var(--gray-400);
  font-size: 12px;
  text-align: center;
}

.side-item.active {
  background: var(--primary-50);
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.35);
}


.qa-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 20px 14px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.82);
}

.qa-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.qa-title-icon {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  color: #fff;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
}

.qa-title {
  color: var(--gray-900);
  font-size: 15px;
  font-weight: 700;
}

.qa-badge {
  padding: 2px 9px;
  border: 1px solid rgba(96, 165, 250, 0.3);
  border-radius: 999px;
  background: var(--primary-50);
  color: var(--primary-600);
  font-size: 11px;
  white-space: nowrap;
}

.chat-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 26px 64px;
  display: flex;
  flex-direction: column;
}

.chat-list > * {
  flex-shrink: 0;
}

.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: auto;
  text-align: center;
}

.chat-empty-hero {
  position: relative;
  width: 76px;
  height: 76px;
  margin: 4px auto 16px;
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
  width: 62px;
  height: 62px;
  display: grid;
  place-items: center;
  border-radius: 20px;
  color: #fff;
  font-size: 29px;
  background: linear-gradient(140deg, #60a5fa 0%, #3b82f6 45%, #2563eb 100%);
  box-shadow: 0 16px 32px rgba(37, 99, 235, 0.34), inset 0 1px 0 rgba(255, 255, 255, 0.5);
  animation: chat-icon-float 3.4s ease-in-out infinite;
}

@keyframes chat-icon-float {
  0%, 100% { transform: translateY(0) rotate(-2deg); }
  50% { transform: translateY(-6px) rotate(2deg); }
}

.empty-text {
  color: var(--gray-700);
  font-size: 15px;
  font-weight: 650;
}

.empty-tip {
  margin-top: 6px;
  color: var(--gray-400);
  font-size: 12.5px;
}

.empty-suggestions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 16px;
  max-width: 520px;
}

.suggestion-chip {
  padding: 8px 14px;
  border: 1px solid rgba(96, 165, 250, 0.35);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  color: var(--primary-600);
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.suggestion-chip:hover {
  border-color: var(--primary-500);
  background: var(--primary-50);
  transform: translateY(-1px);
}

.qa-item {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 28px;
}

.message {
  display: flex;
}

.message.question {
  justify-content: flex-end;
}

.message-content {
  display: flex;
  flex-direction: column;
}

.message.question .message-content {
  max-width: 72%;
  align-items: flex-end;
}

.message.answer .message-content {
  max-width: 82%;
}

.question-bubble {
  padding: 10px 16px;
  border-radius: 18px;
  border-bottom-right-radius: 6px;
  background: #f1f3f5;
  color: var(--gray-800);
  line-height: 1.7;
  font-size: 14px;
  white-space: pre-wrap;
}

.question-bubble.bare {
  padding: 0;
  background: transparent;
}

.answer-plain {
  color: var(--gray-800);
  line-height: 1.85;
  font-size: 14.5px;
}

.answer-md :deep(p) { margin: 0 0 8px; }
.answer-md :deep(p:last-child) { margin-bottom: 0; }
.answer-md :deep(ul), .answer-md :deep(ol) { margin: 0 0 8px; padding-left: 20px; }
.answer-md :deep(h1), .answer-md :deep(h2), .answer-md :deep(h3) {
  margin: 10px 0 6px;
  font-size: 15px;
  color: var(--gray-900);
}
.answer-md :deep(code) {
  padding: 1px 5px;
  border-radius: 5px;
  background: var(--gray-100);
  font-size: 12.5px;
}

.answer-thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--gray-400);
  font-size: 13px;
}

.qa-note {
  margin-top: 8px;
  color: var(--gray-400);
  font-size: 12px;
  line-height: 1.5;
}

.qa-actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}

.answer-md :deep(.cite-sup) {
  color: var(--primary-600);
  font-weight: 600;
  cursor: pointer;
  padding: 0 1px;
}

.answer-md :deep(.cite-sup):hover {
  text-decoration: underline;
}

.input-dock {
  margin: 12px 64px 22px;
  padding: 12px 14px 10px;
  border: 1px solid #dbe5f2;
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 10px 26px rgba(37, 99, 235, 0.08);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.input-dock:focus-within {
  border-color: var(--primary-500);
  box-shadow: 0 10px 26px rgba(37, 99, 235, 0.1), 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.dock-textarea :deep(.el-textarea__inner) {
  padding: 2px 4px;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  font-size: 14px;
  line-height: 1.7;
}

.dock-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 8px;
}

.dock-chips {
  display: flex;
  flex: 1;
  gap: 8px;
  overflow-x: auto;
  scrollbar-width: none;
}

.dock-chips::-webkit-scrollbar {
  display: none;
}

.dock-chip {
  flex-shrink: 0;
  padding: 6px 13px;
  border: 1px solid rgba(96, 165, 250, 0.35);
  border-radius: 999px;
  background: rgba(248, 251, 255, 0.9);
  color: var(--primary-600);
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.dock-chip:hover {
  border-color: var(--primary-500);
  background: var(--primary-50);
}

.tool-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.dock-image-preview {
  position: relative;
  width: 64px;
  margin-bottom: 8px;
}

.dock-image-preview img {
  width: 64px;
  height: 64px;
  border: 1px solid var(--gray-200);
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
  background: var(--gray-600);
  color: #fff;
  cursor: pointer;
}

.preview-remove:hover {
  background: var(--danger);
}

.q-image {
  display: block;
  max-width: 240px;
  max-height: 160px;
  margin-bottom: 6px;
  border-radius: 10px;
}

.dock-send {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  font-size: 16px;
  box-shadow: 0 8px 16px rgba(37, 99, 235, 0.25);
}

@media (max-width: 768px) {
  .chat-list {
    padding: 18px 16px;
  }

  .input-dock {
    margin: 10px 12px 14px;
  }

  .message.question .message-content {
    max-width: 88%;
  }
}
</style>
