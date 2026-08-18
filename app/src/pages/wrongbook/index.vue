<template>
  <view class="page">
    <view v-if="!isStudent" class="tip">错题本仅学生账号可用</view>
    <template v-else>
    <!-- 工具行：课程筛选 + 手动添加 -->
    <view class="toolbar">
      <picker class="course-picker" :range="courseOptions" range-key="name" @change="onPickCourse">
        <view class="picker-inner">
          <text class="picker-value">{{ filterCourse?.name || '全部课程' }}</text>
          <text class="picker-arrow">▾</text>
        </view>
      </picker>
      <button class="add-btn" @click="showAdd = !showAdd">{{ showAdd ? '收起' : '+ 记错题' }}</button>
    </view>

    <!-- 手动添加错题 -->
    <view v-if="showAdd" class="add-form">
      <picker :range="courses" range-key="name" @change="addCourse = courses[Number($event.detail.value)]">
        <view class="picker-inner form-picker">
          <text class="picker-value">{{ addCourse?.name || '选择课程（必选）' }}</text>
          <text class="picker-arrow">▾</text>
        </view>
      </picker>
      <textarea v-model="addForm.stem" class="textarea" placeholder="题干（必填）" placeholder-class="ph" />
      <input v-model="addForm.my_answer" class="input" placeholder="我的答案" placeholder-class="ph" />
      <input v-model="addForm.correct_answer" class="input" placeholder="正确答案" placeholder-class="ph" />
      <textarea v-model="addForm.analysis" class="textarea small" placeholder="解析 / 笔记" placeholder-class="ph" />
      <button class="save-btn" :disabled="adding" :loading="adding" @click="saveNote">保存错题</button>
    </view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!mergedRows.length" class="tip">错题本是空的，继续保持 🎉</view>
      <view v-for="q in mergedRows" :key="q.key" class="q-card">
        <view class="q-head" @click="toggle(q.key)">
          <view class="q-tags">
            <text class="chip">{{ q.typeLabel }}</text>
            <text class="chip">{{ q.sceneLabel }}</text>
            <text v-if="masteredSet.has(q.key)" class="chip mastered">已巩固</text>
          </view>
          <view class="q-stem">{{ q.stem }}</view>
          <view class="q-time">{{ fmtTime(q.time) }}</view>
        </view>

        <view v-if="expandedKeys.has(q.key)" class="q-detail">
          <view v-if="q.options?.length" class="opts">
            <view
              v-for="opt in q.options"
              :key="opt.key"
              class="opt"
              :class="optClass(q, opt.key)"
            >
              <text class="opt-key">{{ opt.key }}.</text> {{ opt.text }}
            </view>
          </view>
          <view class="ans-row wrong">我的答案：{{ fmt(q.my_answer) }}</view>
          <view class="ans-row right">正确答案：{{ fmt(q.correct_answer) }}</view>
          <view v-if="q.analysis" class="ans-row">解析：{{ q.analysis }}</view>

          <view class="actions">
            <button class="act-btn primary" @click="toggleMastery(q)">
              {{ masteredSet.has(q.key) ? '取消巩固' : '标记巩固' }}
            </button>
            <button class="act-btn" @click="toggleRemove(q)">移出错题本</button>
            <button v-if="q.source === 'manual'" class="act-btn danger" @click="removeNote(q)">删除</button>
          </view>
        </view>
      </view>
    </template>
    </template>
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listClasses } from '@/api/classroom.js'
import { getMyWrongQuestions } from '@/api/analytics.js'
import {
  createWrongNote,
  deleteWrongNote,
  listWrongMastery,
  listWrongNotes,
  toggleWrongMastery,
} from '@/api/question.js'

const courses = ref([])
const filterCourse = ref(null)
const rows = ref([])
const notes = ref([])
const masteredSet = ref(new Set())
const removedSet = ref(new Set())
const expandedKeys = ref(new Set())
const loading = ref(false)

// 错题本接口仅学生可用（IsStudent），其他角色不发起请求
const isStudent = uni.getStorageSync('user')?.role === 'student'

const showAdd = ref(false)
const adding = ref(false)
const addCourse = ref(null)
const addForm = ref({ stem: '', my_answer: '', correct_answer: '', analysis: '' })

const courseOptions = computed(() => [{ id: 0, name: '全部课程' }, ...courses.value])

onShow(async () => {
  if (!isStudent) return
  await loadCourses()
  await load()
})

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
  } catch {
    // 忽略
  }
}

async function load() {
  loading.value = true
  try {
    const params = filterCourse.value?.id ? { course: filterCourse.value.id } : {}
    const [wrong, manual, mastery] = await Promise.all([
      getMyWrongQuestions(params),
      listWrongNotes(params),
      listWrongMastery(params),
    ])
    rows.value = wrong.results ?? []
    notes.value = manual.results ?? manual ?? []
    const mastered = new Set()
    ;(mastery?.questions || []).forEach((id) => mastered.add(`auto-${id}`))
    ;(mastery?.notes || []).forEach((id) => mastered.add(`manual-${id}`))
    masteredSet.value = mastered
    const removed = new Set()
    ;(mastery?.removed_questions || []).forEach((id) => removed.add(`auto-${id}`))
    ;(mastery?.removed_notes || []).forEach((id) => removed.add(`manual-${id}`))
    removedSet.value = removed
  } finally {
    loading.value = false
  }
}

// 自动收录 + 手动添加，统一成同一种展示结构（与 web 端一致）
const mergedRows = computed(() => {
  const auto = rows.value.map((q) => ({
    key: `auto-${q.question_id}`,
    source: 'auto',
    stem: q.stem,
    typeLabel: q.qtype_display,
    sceneLabel: q.scene,
    time: q.submitted_at,
    options: q.options,
    my_answer: q.my_answer,
    correct_answer: q.correct_answer,
    analysis: q.analysis,
  }))
  const manual = notes.value.map((n) => ({
    key: `manual-${n.id}`,
    source: 'manual',
    noteId: n.id,
    stem: n.stem,
    typeLabel: '手动添加',
    sceneLabel: n.course_name || '错题本',
    time: n.created_at,
    options: null,
    my_answer: n.my_answer,
    correct_answer: n.correct_answer,
    analysis: n.analysis,
  }))
  return [...manual, ...auto].filter((q) => !removedSet.value.has(q.key))
})

function onPickCourse(e) {
  const picked = courseOptions.value[Number(e.detail.value)]
  filterCourse.value = picked?.id ? picked : null
  load()
}

function toggle(key) {
  const next = new Set(expandedKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedKeys.value = next
}

function fmt(a) {
  if (!a) return '（未作答）'
  if (typeof a === 'string') return a || '（未作答）'
  if (a.key) return a.key
  if (a.keys) return a.keys.join(', ')
  if (a.blanks) return a.blanks.join(' / ')
  if (a.text) return a.text
  return '—'
}

function fmtTime(t) {
  if (!t) return ''
  const d = new Date(t)
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}

function isCorrectOption(q, key) {
  if (!q.correct_answer || typeof q.correct_answer === 'string') return false
  return q.correct_answer?.key === key || (q.correct_answer?.keys || []).includes(key)
}

function isMyOption(q, key) {
  if (!q.my_answer || typeof q.my_answer === 'string') return false
  return q.my_answer?.key === key || (q.my_answer?.keys || []).includes(key)
}

function optClass(q, key) {
  if (isCorrectOption(q, key)) return 'opt-right'
  if (isMyOption(q, key)) return 'opt-wrong'
  return ''
}

async function toggleMastery(q) {
  const payload = q.source === 'auto'
    ? { question: Number(q.key.replace('auto-', '')) }
    : { note: q.noteId }
  const res = await toggleWrongMastery(payload)
  const next = new Set(masteredSet.value)
  if (res?.mastered) next.add(q.key)
  else next.delete(q.key)
  masteredSet.value = next
}

async function toggleRemove(q) {
  uni.showModal({
    title: '移出错题本',
    content: '确定把这道题移出错题本吗？',
    success: async (res) => {
      if (!res.confirm) return
      const payload = q.source === 'auto'
        ? { question: Number(q.key.replace('auto-', '')), action: 'remove' }
        : { note: q.noteId, action: 'remove' }
      await toggleWrongMastery(payload)
      removedSet.value = new Set([...removedSet.value, q.key])
      uni.showToast({ title: '已移除', icon: 'none' })
    },
  })
}

async function removeNote(q) {
  uni.showModal({
    title: '删除错题',
    content: '删除后不可恢复，确定删除这条手动错题吗？',
    confirmColor: '#ef4444',
    success: async (res) => {
      if (!res.confirm) return
      await deleteWrongNote(q.noteId)
      notes.value = notes.value.filter((n) => n.id !== q.noteId)
      uni.showToast({ title: '已删除', icon: 'none' })
    },
  })
}

async function saveNote() {
  if (!addCourse.value?.id) {
    uni.showToast({ title: '请选择课程', icon: 'none' })
    return
  }
  if (!addForm.value.stem.trim()) {
    uni.showToast({ title: '请填写题干', icon: 'none' })
    return
  }
  adding.value = true
  try {
    await createWrongNote({
      course: addCourse.value.id,
      stem: addForm.value.stem.trim(),
      my_answer: addForm.value.my_answer.trim(),
      correct_answer: addForm.value.correct_answer.trim(),
      analysis: addForm.value.analysis.trim(),
    })
    uni.showToast({ title: '已加入错题本', icon: 'success' })
    addForm.value = { stem: '', my_answer: '', correct_answer: '', analysis: '' }
    showAdd.value = false
    await load()
  } finally {
    adding.value = false
  }
}
</script>

<style scoped>
.page {
  padding: 28rpx;
}

.toolbar {
  display: flex;
  gap: 16rpx;
  margin-bottom: 20rpx;
}

.course-picker {
  flex: 1;
}

.picker-inner {
  display: flex;
  align-items: center;
  gap: 12rpx;
  height: 72rpx;
  padding: 0 24rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.04);
  box-sizing: border-box;
}

.form-picker {
  margin-bottom: 14rpx;
}

.picker-value {
  flex: 1;
  overflow: hidden;
  font-size: 26rpx;
  color: #334155;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picker-arrow {
  color: #cbd5e1;
}

.add-btn {
  width: 170rpx;
  height: 72rpx;
  line-height: 72rpx;
  border-radius: 20rpx;
  background: #2563eb;
  color: #ffffff;
  font-size: 24rpx;
  font-weight: 600;
}

.add-btn::after {
  border: none;
}

.add-form {
  margin-bottom: 20rpx;
  padding: 24rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.04);
}

.input {
  height: 76rpx;
  margin-bottom: 14rpx;
  padding: 0 24rpx;
  border-radius: 20rpx;
  background: #f1f5f9;
  border: 1rpx solid transparent;
  font-size: 26rpx;
  box-sizing: border-box;
}

.textarea {
  width: 100%;
  min-height: 140rpx;
  margin-bottom: 14rpx;
  padding: 18rpx 24rpx;
  border-radius: 20rpx;
  background: #f1f5f9;
  border: 1rpx solid transparent;
  font-size: 26rpx;
  box-sizing: border-box;
}

.textarea.small {
  min-height: 100rpx;
}

.ph {
  color: #94a3b8;
}

.save-btn {
  height: 80rpx;
  line-height: 80rpx;
  border-radius: 20rpx;
  background: #2563eb;
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 600;
}

.save-btn::after {
  border: none;
}

.tip {
  padding: 100rpx 0;
  text-align: center;
  font-size: 26rpx;
  color: #94a3b8;
}

.q-card {
  margin-bottom: 18rpx;
  padding: 26rpx 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.04);
}

.q-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-bottom: 12rpx;
}

.chip {
  padding: 4rpx 16rpx;
  border-radius: 999rpx;
  background: #f1f5f9;
  color: #64748b;
  font-size: 20rpx;
}

.chip.mastered {
  background: #ecfdf5;
  color: #10b981;
}

.q-stem {
  font-size: 27rpx;
  line-height: 1.7;
  color: #0f172a;
}

.q-time {
  margin-top: 10rpx;
  font-size: 22rpx;
  color: #94a3b8;
}

.q-detail {
  margin-top: 18rpx;
  padding-top: 18rpx;
  border-top: 1rpx solid #f1f5f9;
}

.opts {
  margin-bottom: 14rpx;
}

.opt {
  margin-bottom: 10rpx;
  padding: 14rpx 20rpx;
  border-radius: 14rpx;
  background: #f8fafc;
  font-size: 25rpx;
  color: #334155;
}

.opt.opt-right {
  background: #ecfdf5;
  color: #10b981;
}

.opt.opt-wrong {
  background: #fef2f2;
  color: #ef4444;
}

.opt-key {
  font-weight: 700;
}

.ans-row {
  margin-top: 10rpx;
  font-size: 25rpx;
  line-height: 1.7;
  color: #475569;
}

.ans-row.wrong {
  color: #ef4444;
}

.ans-row.right {
  color: #10b981;
}

.actions {
  display: flex;
  gap: 14rpx;
  margin-top: 20rpx;
}

.act-btn {
  flex: 1;
  height: 64rpx;
  line-height: 64rpx;
  border-radius: 999rpx;
  background: #f1f5f9;
  color: #475569;
  font-size: 24rpx;
}

.act-btn.primary {
  background: #eff6ff;
  color: #2563eb;
}

.act-btn.danger {
  background: #fef2f2;
  color: #ef4444;
}

.act-btn::after {
  border: none;
}
</style>
