<template>
  <view class="page">
    <!-- 课程选择 -->
    <picker class="course-picker" :range="courses" range-key="name" @change="onPickCourse">
      <view class="picker-inner">
        <text class="picker-label">课程</text>
        <text class="picker-value">{{ currentCourse?.name || '请选择课程' }}</text>
        <text class="picker-arrow">▾</text>
      </view>
    </picker>

    <!-- 聊天记录 -->
    <scroll-view class="chat" scroll-y :scroll-into-view="scrollAnchor" scroll-with-animation>
      <view v-if="!messages.length" class="empty">
        <view class="empty-icon">💬</view>
        <view class="empty-title">向 AI 助教提问</view>
        <view class="empty-sub">基于教师上传的课程资料回答，资料不足会如实告知</view>
        <view
          v-for="s in suggests"
          :key="s"
          class="suggest"
          @click="ask(s)"
        >{{ s }}</view>
      </view>

      <template v-else>
        <view
          v-for="(m, i) in messages"
          :key="i"
          :id="`msg-${i}`"
          class="msg"
          :class="m.role"
        >
          <view class="bubble">
            <view class="msg-text">{{ m.content }}</view>
            <view v-if="m.cited?.length" class="sources">
              <view class="sources-label">参考来源</view>
              <view v-for="(c, ci) in m.cited" :key="ci" class="source-item">
                📄 {{ c.material_name || '课程资料' }}{{ c.page ? ` P${c.page}` : '' }}
              </view>
            </view>
          </view>
        </view>
        <view v-if="asking" id="msg-pending" class="msg assistant">
          <view class="bubble"><view class="msg-text pending">正在思考…</view></view>
        </view>
        <view id="msg-bottom" class="anchor"></view>
      </template>
    </scroll-view>

    <!-- 输入栏 -->
    <view class="input-bar">
      <input
        v-model="input"
        class="input"
        placeholder="输入你的问题…"
        placeholder-class="ph"
        confirm-type="send"
        :disabled="!currentCourse"
        @confirm="ask()"
      />
      <button class="send-btn" :disabled="asking || !currentCourse" :loading="asking" @click="ask()">
        发送
      </button>
    </view>
  </view>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { listClasses } from '@/api/classroom.js'
import { askQuestion, listQaRecords } from '@/api/knowledge.js'

const courses = ref([])
const currentCourse = ref(null)
const messages = ref([])
const input = ref('')
const asking = ref(false)
const scrollAnchor = ref('')
const session = `app-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

// 问答历史仅学生加载；教师视角的 qa-records 是全班学生记录，不能当成"我的对话"展示
const isStudent = uni.getStorageSync('user')?.role === 'student'

const suggests = ['这门课的重点是什么？', '帮我总结第一章的内容', '这门课的考核方式是什么？']

onLoad(loadCourses)

async function loadCourses() {
  try {
    const data = await listClasses()
    const map = new Map()
    ;(data.results ?? data).forEach((row) => {
      const ids = row.courses?.length ? row.courses : [row.course]
      ids.filter(Boolean).forEach((id, index) => {
        map.set(id, { id, name: row.course_names?.[index] || row.course_name || `课程 ${id}` })
      })
    })
    courses.value = [...map.values()]
    if (courses.value.length) {
      currentCourse.value = courses.value[0]
      loadHistory()
    }
  } catch {
    // 班级加载失败时保持空态
  }
}

function onPickCourse(e) {
  currentCourse.value = courses.value[Number(e.detail.value)] || null
  messages.value = []
  loadHistory()
}

/** 载入该课程的历史问答 */
async function loadHistory() {
  if (!currentCourse.value || !isStudent) return
  try {
    const data = await listQaRecords({ course: currentCourse.value.id, page_size: 50 })
    const rows = [...(data.results ?? data)].sort((a, b) => a.id - b.id)
    const list = []
    rows.forEach((r) => {
      list.push({ role: 'user', content: r.question })
      list.push({ role: 'assistant', content: r.answer, cited: r.cited_chunks || [] })
    })
    messages.value = list
    scrollToBottom()
  } catch {
    // 历史加载失败不阻塞提问
  }
}

async function ask(preset) {
  const q = (preset ?? input.value).trim()
  if (!q || asking.value) return
  if (!currentCourse.value) {
    uni.showToast({ title: '请先选择课程', icon: 'none' })
    return
  }
  input.value = ''
  messages.value.push({ role: 'user', content: q })
  asking.value = true
  scrollToBottom('msg-pending')
  try {
    const record = await askQuestion({
      course: currentCourse.value.id,
      question: q,
      session,
    })
    messages.value.push({
      role: 'assistant',
      content: record.answer || '（无回答）',
      cited: record.cited_chunks || [],
    })
  } catch {
    messages.value.push({
      role: 'assistant',
      content: '抱歉，AI 助教暂时没有响应，请稍后再试。',
    })
  } finally {
    asking.value = false
    scrollToBottom()
  }
}

function scrollToBottom(anchor) {
  nextTick(() => {
    scrollAnchor.value = ''
    nextTick(() => {
      scrollAnchor.value = anchor || (messages.value.length ? 'msg-bottom' : '')
    })
  })
}
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  box-sizing: border-box;
  padding: 20rpx 28rpx 0;
}

.course-picker {
  flex-shrink: 0;
  margin-bottom: 20rpx;
}

.picker-inner {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 22rpx 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.04);
}

.picker-label {
  font-size: 24rpx;
  color: #94a3b8;
}

.picker-value {
  flex: 1;
  overflow: hidden;
  font-size: 28rpx;
  font-weight: 600;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picker-arrow {
  color: #cbd5e1;
}

.chat {
  flex: 1;
  min-height: 0;
}

.empty {
  padding: 80rpx 40rpx;
  text-align: center;
}

.empty-icon {
  font-size: 72rpx;
}

.empty-title {
  margin-top: 20rpx;
  font-size: 32rpx;
  font-weight: 700;
  color: #0f172a;
}

.empty-sub {
  margin: 12rpx 0 36rpx;
  font-size: 24rpx;
  color: #94a3b8;
}

.suggest {
  display: inline-block;
  margin: 0 10rpx 16rpx;
  padding: 12rpx 26rpx;
  border-radius: 999rpx;
  background: #eff6ff;
  color: #2563eb;
  font-size: 24rpx;
}

.msg {
  display: flex;
  margin-bottom: 22rpx;
}

.msg.user {
  justify-content: flex-end;
}

.bubble {
  max-width: 78%;
  padding: 20rpx 26rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
}

.msg.user .bubble {
  background: #2563eb;
  border: none;
}

.msg.user .msg-text {
  color: #ffffff;
}

.msg-text {
  font-size: 27rpx;
  line-height: 1.8;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-text.pending {
  color: #94a3b8;
}

.sources {
  margin-top: 16rpx;
  padding-top: 14rpx;
  border-top: 1rpx solid #f1f5f9;
}

.sources-label {
  margin-bottom: 8rpx;
  font-size: 22rpx;
  font-weight: 700;
  color: #2563eb;
}

.source-item {
  margin-top: 6rpx;
  font-size: 22rpx;
  color: #64748b;
}

.anchor {
  height: 10rpx;
}

.input-bar {
  display: flex;
  flex-shrink: 0;
  gap: 16rpx;
  padding: 16rpx 0 calc(16rpx + env(safe-area-inset-bottom));
}

.input {
  flex: 1;
  height: 80rpx;
  padding: 0 28rpx;
  border-radius: 20rpx;
  background: #f1f5f9;
  border: 1rpx solid transparent;
  font-size: 27rpx;
  box-sizing: border-box;
}

.ph {
  color: #94a3b8;
}

.send-btn {
  width: 140rpx;
  height: 80rpx;
  line-height: 80rpx;
  border-radius: 20rpx;
  background: #2563eb;
  color: #ffffff;
  font-size: 26rpx;
  font-weight: 600;
}

.send-btn::after {
  border: none;
}
</style>
