<template>
  <view class="page">
    <!-- 筛选行 -->
    <view class="filters">
      <picker :range="courses" range-key="name" @change="onPickCourse">
        <view class="picker-inner">
          <text class="picker-value">{{ currentCourse?.name || '选择课程' }}</text>
          <text class="picker-arrow">▾</text>
        </view>
      </picker>
      <picker :range="qtypeOptions" range-key="label" @change="onPickQtype">
        <view class="picker-inner">
          <text class="picker-value">{{ currentQtype.label }}</text>
          <text class="picker-arrow">▾</text>
        </view>
      </picker>
    </view>

    <button class="primary-btn add" @click="showCreate = !showCreate">{{ showCreate ? '收起录题' : '+ 录题' }}</button>

    <!-- 录题表单 -->
    <view v-if="showCreate" class="card form">
      <picker :range="createQtypes" range-key="label" @change="onPickCreateQtype">
        <view class="input picker">{{ createForm.qtypeLabel }}</view>
      </picker>
      <textarea v-model="createForm.stem" class="textarea" placeholder="题干（必填）" placeholder-class="ph" />

      <!-- 选项编辑（单选/多选） -->
      <template v-if="['single', 'multi'].includes(createForm.qtype)">
        <view v-for="(opt, i) in createForm.options" :key="opt.key" class="opt-edit">
          <text class="opt-key">{{ opt.key }}</text>
          <input v-model="opt.text" class="input opt-input" placeholder="选项内容" placeholder-class="ph" />
          <text v-if="createForm.options.length > 2" class="opt-del" @click="createForm.options.splice(i, 1)">✕</text>
        </view>
        <button class="ghost-btn" @click="addOption">+ 添加选项</button>
        <view class="answer-pick">
          <text class="label">正确答案：</text>
          <text
            v-for="opt in createForm.options"
            :key="opt.key"
            class="chip pick"
            :class="{ on: isPicked(opt.key) }"
            @click="pickAnswer(opt.key)"
          >{{ opt.key }}</text>
        </view>
      </template>

      <!-- 判断 -->
      <view v-if="createForm.qtype === 'judge'" class="answer-pick">
        <text class="label">正确答案：</text>
        <text class="chip pick" :class="{ on: createForm.answerKey === 'A' }" @click="createForm.answerKey = 'A'">正确</text>
        <text class="chip pick" :class="{ on: createForm.answerKey === 'B' }" @click="createForm.answerKey = 'B'">错误</text>
      </view>

      <!-- 填空 -->
      <template v-if="createForm.qtype === 'blank'">
        <view v-for="(_, i) in createForm.blanks" :key="i" class="opt-edit">
          <text class="opt-key">空{{ i + 1 }}</text>
          <input v-model="createForm.blanks[i]" class="input opt-input" placeholder="该空答案" placeholder-class="ph" />
          <text v-if="createForm.blanks.length > 1" class="opt-del" @click="createForm.blanks.splice(i, 1)">✕</text>
        </view>
        <button class="ghost-btn" @click="createForm.blanks.push('')">+ 添加空</button>
      </template>

      <!-- 简答 -->
      <textarea v-if="createForm.qtype === 'short'" v-model="createForm.answerText" class="textarea" placeholder="参考答案" placeholder-class="ph" />

      <textarea v-model="createForm.analysis" class="textarea" placeholder="解析（可空）" placeholder-class="ph" />
      <view class="row-inputs">
        <picker :range="difficulties" range-key="label" @change="createForm.difficulty = difficulties[Number($event.detail.value)].value">
          <view class="input picker">{{ difficultyLabel }}</view>
        </picker>
        <input v-model="createForm.score" class="input score" type="digit" placeholder="分值" placeholder-class="ph" />
      </view>
      <picker :range="catalogOptions" range-key="title" @change="createForm.catalog = catalogOptions[Number($event.detail.value)].id">
        <view class="input picker">{{ catalogLabel }}</view>
      </picker>
      <view class="ops">
        <button class="op-btn" :disabled="saving" @click="save('draft')">存为草稿</button>
        <button class="op-btn primary" :disabled="saving" :loading="saving" @click="save('published')">直接发布</button>
      </view>
    </view>

    <!-- 题目列表 -->
    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">暂无题目</view>
      <view v-for="q in rows" :key="q.id" class="card">
        <view class="q-tags">
          <text class="chip">{{ q.qtype_display || q.qtype }}</text>
          <text class="chip">{{ q.difficulty_display || q.difficulty }}</text>
          <text class="chip" :class="q.status === 'published' ? 'success' : 'warn'">
            {{ q.status === 'published' ? '已发布' : '草稿' }}
          </text>
          <text class="chip">{{ q.score }} 分</text>
        </view>
        <view class="q-stem">{{ q.stem }}</view>
        <view v-if="q.options?.length" class="q-opts">
          <view v-for="opt in q.options" :key="opt.key" class="q-opt">{{ opt.key }}. {{ opt.text }}</view>
        </view>
        <view class="q-answer">答案：{{ fmtAns(q.answer) }}</view>
        <view v-if="q.analysis" class="q-analysis">解析：{{ q.analysis }}</view>
        <view class="node-ops">
          <text class="op" @click="toggleStatus(q)">{{ q.status === 'published' ? '转草稿' : '发布' }}</text>
          <text class="op danger" @click="removeQuestion(q)">删除</text>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listCourses, listCatalogs } from '@/api/course.js'
import { listQuestions, createQuestion, updateQuestion, deleteQuestion } from '@/api/question.js'

const qtypeOptions = [
  { label: '全部题型', value: '' },
  { label: '单选', value: 'single' },
  { label: '多选', value: 'multi' },
  { label: '判断', value: 'judge' },
  { label: '填空', value: 'blank' },
  { label: '简答', value: 'short' },
]
const createQtypes = qtypeOptions.slice(1)
const difficulties = [
  { label: '简单', value: 'easy' },
  { label: '中等', value: 'medium' },
  { label: '困难', value: 'hard' },
]

const courses = ref([])
const currentCourse = ref(null)
const currentQtype = ref(qtypeOptions[0])
const rows = ref([])
const loading = ref(false)
const showCreate = ref(false)
const saving = ref(false)
const catalogOptions = ref([])

const emptyForm = () => ({
  qtype: 'single',
  qtypeLabel: '单选题',
  stem: '',
  options: [
    { key: 'A', text: '' },
    { key: 'B', text: '' },
    { key: 'C', text: '' },
    { key: 'D', text: '' },
  ],
  answerKey: '',
  answerKeys: [],
  blanks: [''],
  answerText: '',
  analysis: '',
  difficulty: 'medium',
  score: '',
  catalog: null,
})
const createForm = ref(emptyForm())

const difficultyLabel = computed(() =>
  difficulties.find((d) => d.value === createForm.value.difficulty)?.label || '难度',
)
const catalogLabel = computed(() => {
  const c = catalogOptions.value.find((x) => x.id === createForm.value.catalog)
  return c ? c.title : '所属章节（可空）'
})

onShow(async () => {
  try {
    const data = await listCourses()
    courses.value = (data.results ?? data).map((c) => ({ id: c.id, name: c.name }))
    if (courses.value.length) {
      currentCourse.value = courses.value[0]
      loadCatalogs()
      load()
    }
  } catch {
    // 忽略
  }
})

function onPickCourse(e) {
  currentCourse.value = courses.value[Number(e.detail.value)] || null
  loadCatalogs()
  load()
}

function onPickQtype(e) {
  currentQtype.value = qtypeOptions[Number(e.detail.value)]
  load()
}

async function loadCatalogs() {
  catalogOptions.value = []
  if (!currentCourse.value) return
  try {
    const data = await listCatalogs({ course: currentCourse.value.id, tree: 1 })
    const flat = []
    for (const n of data.results ?? data) {
      flat.push({ id: n.id, title: n.title })
      for (const c of n.children || []) flat.push({ id: c.id, title: `${n.title} / ${c.title}` })
    }
    catalogOptions.value = flat
  } catch {
    // 忽略
  }
}

async function load() {
  if (!currentCourse.value) return
  loading.value = true
  try {
    const params = { course: currentCourse.value.id }
    if (currentQtype.value.value) params.qtype = currentQtype.value.value
    const data = await listQuestions(params)
    rows.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

function onPickCreateQtype(e) {
  const picked = createQtypes[Number(e.detail.value)]
  createForm.value.qtype = picked.value
  createForm.value.qtypeLabel = `${picked.label}题`
}

function addOption() {
  const next = String.fromCharCode(65 + createForm.value.options.length)
  createForm.value.options.push({ key: next, text: '' })
}

function isPicked(key) {
  const f = createForm.value
  return f.qtype === 'multi' ? f.answerKeys.includes(key) : f.answerKey === key
}

function pickAnswer(key) {
  const f = createForm.value
  if (f.qtype === 'multi') {
    f.answerKeys = f.answerKeys.includes(key)
      ? f.answerKeys.filter((k) => k !== key)
      : [...f.answerKeys, key]
  } else {
    f.answerKey = key
  }
}

function fmtAns(a) {
  if (!a) return '-'
  if (a.key) return a.key
  if (a.keys) return a.keys.join('、')
  if (a.blanks) return a.blanks.join(' / ')
  if (a.text) return a.text
  return '-'
}

async function save(status) {
  const f = createForm.value
  if (!f.stem.trim()) return uni.showToast({ title: '请输入题干', icon: 'none' })
  let options = []
  let answer = {}
  if (['single', 'multi'].includes(f.qtype)) {
    options = f.options.filter((o) => o.text.trim())
    if (options.length < 2) return uni.showToast({ title: '至少两个有效选项', icon: 'none' })
    if (f.qtype === 'single' && !f.answerKey) return uni.showToast({ title: '请选择正确答案', icon: 'none' })
    if (f.qtype === 'multi' && !f.answerKeys.length) return uni.showToast({ title: '请选择正确答案', icon: 'none' })
    answer = f.qtype === 'single' ? { key: f.answerKey } : { keys: f.answerKeys }
  } else if (f.qtype === 'judge') {
    options = [{ key: 'A', text: '正确' }, { key: 'B', text: '错误' }]
    if (!f.answerKey) return uni.showToast({ title: '请选择正确答案', icon: 'none' })
    answer = { key: f.answerKey }
  } else if (f.qtype === 'blank') {
    const blanks = f.blanks.map((b) => b.trim()).filter(Boolean)
    if (!blanks.length) return uni.showToast({ title: '请填写填空答案', icon: 'none' })
    answer = { blanks }
  } else {
    answer = { text: f.answerText.trim() }
  }
  saving.value = true
  try {
    await createQuestion({
      course: currentCourse.value.id,
      catalog: f.catalog || undefined,
      qtype: f.qtype,
      stem: f.stem.trim(),
      options,
      answer,
      analysis: f.analysis.trim(),
      difficulty: f.difficulty,
      score: Number(f.score) || 5,
      status,
    })
    uni.showToast({ title: status === 'published' ? '已发布' : '已存草稿', icon: 'success' })
    createForm.value = emptyForm()
    showCreate.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function toggleStatus(q) {
  await updateQuestion(q.id, { status: q.status === 'published' ? 'draft' : 'published' })
  uni.showToast({ title: '已更新', icon: 'none' })
  load()
}

function removeQuestion(q) {
  uni.showModal({
    title: '删除题目',
    content: '确定删除这道题吗？',
    confirmColor: '#ef4444',
    success: async (res) => {
      if (!res.confirm) return
      await deleteQuestion(q.id)
      uni.showToast({ title: '已删除', icon: 'none' })
      load()
    },
  })
}
</script>

<style scoped>
.page { padding: 28rpx; }
.filters { display: flex; gap: 14rpx; margin-bottom: 16rpx; }
.filters picker { flex: 1; }
.picker-inner { display: flex; align-items: center; gap: 12rpx; height: 76rpx; padding: 0 24rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-sizing: border-box; }
.picker-value { flex: 1; overflow: hidden; font-size: 26rpx; color: #334155; text-overflow: ellipsis; white-space: nowrap; }
.picker-arrow { color: #cbd5e1; }
.tip { padding: 60rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.card { margin-bottom: 18rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.primary-btn { height: 80rpx; line-height: 80rpx; border-radius: 20rpx; background: #2563eb; color: #fff; font-size: 28rpx; font-weight: 600; }
.primary-btn::after { border: none; }
.primary-btn.add { margin-bottom: 16rpx; }
.ghost-btn { height: 60rpx; line-height: 60rpx; margin-top: 8rpx; border-radius: 16rpx; background: #f1f5f9; color: #64748b; font-size: 24rpx; }
.ghost-btn::after { border: none; }
.form .input, .form .textarea, .form .row-inputs, .form .answer-pick, .form picker { margin-bottom: 14rpx; display: block; }
.input { height: 76rpx; padding: 0 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.picker { display: flex !important; align-items: center; color: #334155; }
.textarea { width: 100%; min-height: 130rpx; padding: 18rpx 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.ph { color: #94a3b8; }
.opt-edit { display: flex; align-items: center; gap: 14rpx; margin-bottom: 12rpx; }
.opt-key { width: 64rpx; flex-shrink: 0; font-size: 26rpx; font-weight: 700; color: #64748b; }
.opt-input { flex: 1; }
.opt-del { color: #ef4444; font-size: 26rpx; }
.answer-pick { display: flex; align-items: center; flex-wrap: wrap; gap: 12rpx; }
.label { font-size: 24rpx; color: #64748b; }
.chip { padding: 6rpx 20rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 24rpx; }
.chip.pick.on { background: #2563eb; color: #fff; }
.row-inputs { display: flex; gap: 14rpx; }
.row-inputs picker { flex: 1; }
.input.score { width: 160rpx; flex-shrink: 0; }
.ops { display: flex; gap: 14rpx; margin-top: 8rpx; }
.op-btn { flex: 1; height: 76rpx; line-height: 76rpx; border-radius: 20rpx; background: #f1f5f9; color: #475569; font-size: 26rpx; font-weight: 600; }
.op-btn::after { border: none; }
.op-btn.primary { background: #2563eb; color: #fff; }
.q-tags { display: flex; flex-wrap: wrap; gap: 10rpx; margin-bottom: 12rpx; }
.chip.success { background: #ecfdf5; color: #10b981; }
.chip.warn { background: #fff7ed; color: #f59e0b; }
.q-stem { font-size: 27rpx; line-height: 1.7; color: #0f172a; }
.q-opts { margin-top: 12rpx; }
.q-opt { margin-top: 6rpx; font-size: 25rpx; color: #475569; }
.q-answer { margin-top: 12rpx; font-size: 25rpx; color: #10b981; }
.q-analysis { margin-top: 8rpx; font-size: 24rpx; color: #64748b; }
.node-ops { display: flex; gap: 24rpx; margin-top: 14rpx; }
.op { font-size: 24rpx; color: #2563eb; }
.op.danger { color: #ef4444; }
</style>
