<template>
  <div class="page-container qa-page">
    <div class="page-header">
      <div>
        <div class="page-title">知识库提问</div>
        <div class="page-subtitle">基于教师上传的课程资料进行 AI 问答，资料不足时会如实告知</div>
      </div>
    </div>

    <el-card shadow="never" class="qa-card">
      <div class="qa-header">
        <el-select v-model="courseId" placeholder="选择课程" style="width: 260px" @change="loadHistory">
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-text type="info" size="small">
          <el-icon style="vertical-align: middle; margin-right: 4px"><InfoFilled /></el-icon>
          选择课程后，可向该课程知识库提问
        </el-text>
      </div>

      <el-empty v-if="!courseId" description="请先选择一门课程">
        <template #description>
          <div class="empty-text">请先选择一门课程</div>
          <div class="empty-tip">选择左侧课程后即可基于知识库提问</div>
        </template>
      </el-empty>

      <template v-else>
        <div ref="listRef" class="chat-list">
          <el-empty v-if="!messages.length" description="还没有提问">
            <template #description>
              <div class="empty-text">还没有提问</div>
              <div class="empty-tip">试试在下方输入问题，Enter 发送，Shift+Enter 换行</div>
            </template>
          </el-empty>

          <div v-for="(m, i) in messages" :key="i" class="qa-item">
            <div class="message question">
              <el-avatar :size="36" :icon="UserFilled" class="msg-avatar user-avatar" />
              <div class="message-content">
                <div class="msg-meta">
                  <span class="msg-name">我</span>
                  <span class="msg-time">{{ formatTime(m.created_at) }}</span>
                </div>
                <div class="bubble question-bubble">{{ m.question }}</div>
              </div>
            </div>

            <div class="message answer">
              <el-avatar :size="36" :icon="ChatDotRound" class="msg-avatar ai-avatar" />
              <div class="message-content">
                <div class="msg-meta">
                  <span class="msg-name">AI 助教</span>
                  <span class="msg-time">{{ formatTime(m.created_at) }}</span>
                </div>
                <div class="bubble answer-bubble">
                  <div class="answer-text">{{ m.answer }}</div>
                  <div v-if="m.cited_chunks?.length" class="sources">
                    <div class="sources-title">
                      <el-icon><Collection /></el-icon> 参考来源
                    </div>
                    <div class="source-tags">
                      <el-tag
                        v-for="(c, ci) in m.cited_chunks"
                        :key="ci"
                        size="small"
                        effect="plain"
                        type="info"
                        round
                      >
                        {{ c.material_name }}{{ c.page ? ` P${c.page}` : '' }}
                      </el-tag>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="input-bar">
          <el-input
            v-model="question"
            type="textarea"
            :rows="3"
            resize="none"
            placeholder="输入你的问题，Enter 发送，Shift+Enter 换行"
            @keydown.enter.exact.prevent="ask"
          />
          <el-button type="primary" :loading="asking" :icon="Promotion" class="send-btn" @click="ask">发送</el-button>
        </div>
      </template>
    </el-card>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { UserFilled, ChatDotRound, InfoFilled, Collection, Promotion } from '@element-plus/icons-vue'
import { listClasses } from '@/api/classroom'
import { askQuestion, listQaRecords } from '@/api/knowledge'

const courses = ref([])
const courseId = ref(null)
const messages = ref([])
const question = ref('')
const asking = ref(false)
const listRef = ref(null)

function formatTime(t) {
  return t ? new Date(t).toLocaleString() : new Date().toLocaleString()
}

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
  if (courses.value.length) {
    courseId.value = courses.value[0].id
    loadHistory()
  }
}

async function loadHistory() {
  if (!courseId.value) return
  const data = await listQaRecords({ course: courseId.value })
  const rows = (data.results ?? data).slice().reverse()
  messages.value = rows.map((r) => ({
    question: r.question,
    answer: r.answer,
    cited_chunks: r.cited_chunks,
    created_at: r.created_at,
  }))
  scrollToBottom()
}

// #7 打字机逐字显示回答
let typeTimer = null
function typewrite(msg, text) {
  if (typeTimer) clearTimeout(typeTimer)
  msg.answer = ''
  const chunk = Math.max(1, Math.round(text.length / 80))
  let i = 0
  const step = () => {
    i = Math.min(i + chunk, text.length)
    msg.answer = text.slice(0, i)
    scrollToBottom()
    if (i < text.length) typeTimer = setTimeout(step, 20)
  }
  step()
}

async function ask() {
  const q = question.value.trim()
  if (!q) return
  if (!courseId.value) return ElMessage.warning('请先选择课程')
  asking.value = true
  const now = new Date().toISOString()
  const pending = { question: q, answer: '思考中…', cited_chunks: [], created_at: now }
  messages.value.push(pending)
  question.value = ''
  scrollToBottom()
  try {
    const data = await askQuestion({ course: courseId.value, question: q })
    pending.cited_chunks = data.cited_chunks
    typewrite(pending, data.answer)
  } catch {
    pending.answer = '回答失败，请稍后重试。'
  } finally {
    asking.value = false
    scrollToBottom()
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
  })
}

onMounted(loadCourses)
</script>

<style scoped>
.qa-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 72px);
  padding-bottom: 24px;
}

.qa-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}

.qa-card :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 20px;
}

.qa-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #f8fafc;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}

.qa-item {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-bottom: 24px;
}

.message {
  display: flex;
  gap: 12px;
}

.message.question {
  flex-direction: row-reverse;
}

.message-content {
  max-width: 70%;
  display: flex;
  flex-direction: column;
}

.message.question .message-content {
  align-items: flex-end;
}

.msg-avatar {
  flex-shrink: 0;
}

.user-avatar {
  background: linear-gradient(135deg, #2563eb, #4f46e5);
  color: #fff;
}

.ai-avatar {
  background: #10b981;
  color: #fff;
}

.msg-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12px;
}

.msg-name {
  font-weight: 600;
  color: #1e293b;
}

.msg-time {
  color: #94a3b8;
}

.bubble {
  padding: 14px 18px;
  border-radius: 16px;
  line-height: 1.7;
  font-size: 14px;
}

.question-bubble {
  background: #2563eb;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.answer-bubble {
  background: #fff;
  color: #1e293b;
  border: 1px solid #e2e8f0;
  border-bottom-left-radius: 4px;
}

.answer-text {
  white-space: pre-wrap;
}

.sources {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #e2e8f0;
}

.sources-title {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.source-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.input-bar {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  margin-top: 16px;
}

.input-bar :deep(.el-textarea__inner) {
  border-radius: 12px;
  resize: none;
}

.send-btn {
  height: 54px;
  padding: 0 24px;
  border-radius: 12px;
  font-size: 15px;
}

.empty-text {
  font-size: 14px;
  color: #64748b;
  margin-bottom: 4px;
}

.empty-tip {
  font-size: 12px;
  color: #94a3b8;
}

@media (max-width: 768px) {
  .message-content {
    max-width: 85%;
  }
}
</style>
