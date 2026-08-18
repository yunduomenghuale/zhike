<template>
  <view class="page">
    <view class="toolbar">
      <view class="page-title">考试管理</view>
      <button class="primary-btn small" @click="showCreate = !showCreate">{{ showCreate ? '收起' : '+ 新建考试' }}</button>
    </view>

    <!-- 新建考试 -->
    <view v-if="showCreate" class="card form">
      <picker :range="classes" range-key="name" @change="onPickClass">
        <view class="input picker">{{ createForm.classroom?.name || '选择班级（必选）' }}</view>
      </picker>
      <picker v-if="createForm.classroom" :range="classCourses" range-key="name" @change="createForm.course = classCourses[Number($event.detail.value)]">
        <view class="input picker">{{ createForm.course?.name || '选择课程（必选）' }}</view>
      </picker>
      <input v-model="createForm.name" class="input" placeholder="考试名称（必填）" placeholder-class="ph" />
      <view class="dt-row">
        <picker mode="date" @change="createForm.sd = $event.detail.value"><view class="input picker">{{ createForm.sd || '开始日期' }}</view></picker>
        <picker mode="time" @change="createForm.st = $event.detail.value"><view class="input picker">{{ createForm.st || '时间' }}</view></picker>
      </view>
      <view class="dt-row">
        <picker mode="date" @change="createForm.ed = $event.detail.value"><view class="input picker">{{ createForm.ed || '结束日期' }}</view></picker>
        <picker mode="time" @change="createForm.et = $event.detail.value"><view class="input picker">{{ createForm.et || '时间' }}</view></picker>
      </view>
      <input v-model="createForm.duration" class="input" type="number" placeholder="考试时长（分钟，默认 60）" placeholder-class="ph" />
      <button class="primary-btn" :disabled="creating" :loading="creating" @click="doCreate">创建（草稿）</button>
    </view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">还没有创建过考试</view>
      <view v-for="e in rows" :key="e.id" class="card">
        <view class="e-head">
          <view class="e-name">{{ e.name }}</view>
          <text class="chip" :class="tone(e.status)">{{ e.status_display || e.status }}</text>
        </view>
        <view class="e-chips">
          <text class="chip">{{ e.class_name }}</text>
          <text class="chip">{{ e.duration }} 分钟</text>
          <text class="chip">{{ e.total_score }} 分</text>
        </view>
        <view class="e-time">{{ fmtTime(e.start_at) }} ~ {{ fmtTime(e.end_at) }}</view>

        <!-- 组卷面板 -->
        <view v-if="composeId === e.id" class="compose">
          <view v-for="(r, i) in rules" :key="i" class="rule-row">
            <picker :range="qtypes" range-key="label" @change="r.qtype = qtypes[Number($event.detail.value)].value">
              <view class="input picker rule-qtype">{{ qtypeLabel(r.qtype) }}</view>
            </picker>
            <input v-model="r.count" class="input rule-num" type="number" placeholder="题数" placeholder-class="ph" />
            <input v-model="r.score" class="input rule-num" type="digit" placeholder="分值" placeholder-class="ph" />
            <text class="rule-del" @click="rules.splice(i, 1)">✕</text>
          </view>
          <button class="ghost-btn" @click="rules.push({ qtype: 'single', count: '', score: '' })">+ 添加规则</button>
          <button class="primary-btn compose-btn" :disabled="composing" :loading="composing" @click="doCompose(e)">
            开始随机组卷
          </button>
        </view>

        <view class="ops">
          <template v-if="e.status === 'draft'">
            <button class="op-btn" @click="toggleCompose(e)">{{ composeId === e.id ? '收起组卷' : '组卷' }}</button>
            <button class="op-btn primary" @click="publish(e)">发布考试</button>
          </template>
          <button v-else class="op-btn primary" @click="openMonitor(e)">监控 / 批改</button>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listExams, createExam, composePaper } from '@/api/exam.js'
import { listClasses } from '@/api/classroom.js'
import { patch } from '@/utils/request.js'

const qtypes = [
  { label: '单选', value: 'single' },
  { label: '多选', value: 'multi' },
  { label: '判断', value: 'judge' },
  { label: '填空', value: 'blank' },
  { label: '简答', value: 'short' },
]

const rows = ref([])
const classes = ref([])
const classCourses = ref([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ classroom: null, course: null, name: '', sd: '', st: '', ed: '', et: '', duration: '' })
const composeId = ref(null)
const rules = ref([{ qtype: 'single', count: '', score: '' }])
const composing = ref(false)

onShow(load)

async function load() {
  loading.value = true
  try {
    const [ex, cls] = await Promise.all([listExams(), listClasses()])
    rows.value = ex.results ?? ex
    classes.value = cls.results ?? cls
  } finally {
    loading.value = false
  }
}

function onPickClass(e) {
  const c = classes.value[Number(e.detail.value)]
  createForm.value.classroom = c
  createForm.value.course = null
  const ids = c.courses?.length ? c.courses : [c.course]
  classCourses.value = ids.filter(Boolean).map((id, i) => ({
    id,
    name: c.course_names?.[i] || c.course_name || `课程 ${id}`,
  }))
}

async function doCreate() {
  const f = createForm.value
  if (!f.classroom?.id) return uni.showToast({ title: '请选择班级', icon: 'none' })
  if (!f.course?.id) return uni.showToast({ title: '请选择课程', icon: 'none' })
  if (!f.name.trim()) return uni.showToast({ title: '请输入考试名称', icon: 'none' })
  creating.value = true
  try {
    await createExam({
      course: f.course.id,
      classroom: f.classroom.id,
      name: f.name.trim(),
      start_at: f.sd ? `${f.sd}T${f.st || '00:00'}:00` : null,
      end_at: f.ed ? `${f.ed}T${f.et || '23:59'}:00` : null,
      duration: Number(f.duration) || 60,
    })
    uni.showToast({ title: '创建成功（草稿）', icon: 'success' })
    createForm.value = { classroom: null, course: null, name: '', sd: '', st: '', ed: '', et: '', duration: '' }
    showCreate.value = false
    load()
  } finally {
    creating.value = false
  }
}

function tone(s) {
  return { draft: '', published: 'success', finished: 'muted' }[s] || ''
}

function fmtTime(t) {
  if (!t) return '不限'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function toggleCompose(e) {
  composeId.value = composeId.value === e.id ? null : e.id
  rules.value = [{ qtype: 'single', count: '', score: '' }]
}

function qtypeLabel(v) {
  return qtypes.find((q) => q.value === v)?.label || '题型'
}

async function doCompose(e) {
  const valid = rules.value.filter((r) => Number(r.count) > 0)
  if (!valid.length) return uni.showToast({ title: '请至少填一条有效规则', icon: 'none' })
  composing.value = true
  try {
    await composePaper(e.id, {
      mode: 'random',
      rules: valid.map((r) => ({ qtype: r.qtype, count: Number(r.count), score: Number(r.score) || 5 })),
    })
    uni.showToast({ title: '组卷完成', icon: 'success' })
    composeId.value = null
    load()
  } finally {
    composing.value = false
  }
}

function publish(e) {
  uni.showModal({
    title: '发布考试',
    content: '发布后将通知班级学生，且不能再组卷。确定发布吗？',
    success: async (res) => {
      if (!res.confirm) return
      await patch(`/exams/${e.id}/`, { status: 'published' })
      uni.showToast({ title: '已发布', icon: 'success' })
      load()
    },
  })
}

function openMonitor(e) {
  uni.navigateTo({ url: `/pages/teacher/exam-monitor?id=${e.id}&name=${encodeURIComponent(e.name)}` })
}
</script>

<style scoped>
.page { padding: 28rpx; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; }
.page-title { font-size: 32rpx; font-weight: 800; color: #0f172a; }
.tip { padding: 80rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.card { margin-bottom: 20rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.form .input, .form .dt-row, .form picker { margin-bottom: 14rpx; display: block; }
.input { height: 76rpx; padding: 0 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.picker { display: flex !important; align-items: center; color: #334155; }
.dt-row { display: flex; gap: 14rpx; }
.dt-row .input, .dt-row picker { flex: 1; }
.ph { color: #94a3b8; }
.primary-btn { height: 80rpx; line-height: 80rpx; border-radius: 20rpx; background: #2563eb; color: #fff; font-size: 28rpx; font-weight: 600; }
.primary-btn::after { border: none; }
.primary-btn.small { width: auto; height: 64rpx; line-height: 64rpx; padding: 0 28rpx; font-size: 24rpx; }
.primary-btn.compose-btn { margin-top: 14rpx; }
.ghost-btn { height: 60rpx; line-height: 60rpx; border-radius: 16rpx; background: #f1f5f9; color: #64748b; font-size: 24rpx; }
.ghost-btn::after { border: none; }
.e-head { display: flex; align-items: center; justify-content: space-between; gap: 14rpx; }
.e-name { flex: 1; overflow: hidden; font-size: 30rpx; font-weight: 700; color: #0f172a; text-overflow: ellipsis; white-space: nowrap; }
.e-chips { display: flex; flex-wrap: wrap; gap: 10rpx; margin-top: 14rpx; }
.chip { padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 22rpx; }
.chip.success { background: #ecfdf5; color: #10b981; }
.chip.muted { background: #f1f5f9; color: #94a3b8; }
.e-time { margin-top: 12rpx; font-size: 23rpx; color: #94a3b8; }
.compose { margin-top: 16rpx; padding-top: 16rpx; border-top: 1rpx solid #f1f5f9; }
.rule-row { display: flex; align-items: center; gap: 12rpx; margin-bottom: 12rpx; }
.rule-qtype { width: 150rpx; flex-shrink: 0; }
.rule-num { flex: 1; }
.rule-del { color: #ef4444; font-size: 26rpx; }
.ops { display: flex; gap: 14rpx; margin-top: 16rpx; }
.op-btn { flex: 1; height: 68rpx; line-height: 68rpx; border-radius: 16rpx; background: #f1f5f9; color: #475569; font-size: 26rpx; font-weight: 600; }
.op-btn::after { border: none; }
.op-btn.primary { background: #2563eb; color: #fff; }
</style>
