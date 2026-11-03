<template>
  <view class="page">
    <view class="toolbar">
      <view class="page-title">作业管理</view>
      <button class="primary-btn small" @click="showCreate = !showCreate">{{ showCreate ? '收起' : '+ 布置作业' }}</button>
    </view>

    <!-- 布置作业 -->
    <view v-if="showCreate" class="card form">
      <picker :range="classes" range-key="name" @change="onPickClass">
        <view class="input picker">{{ createForm.classroom?.name || '选择班级（必选）' }}</view>
      </picker>
      <picker v-if="createForm.classroom" :range="classCourses" range-key="name" @change="createForm.course = classCourses[Number($event.detail.value)]">
        <view class="input picker">{{ createForm.course?.name || '选择课程（必选）' }}</view>
      </picker>
      <input v-model="createForm.title" class="input" placeholder="作业标题（必填）" placeholder-class="ph" />
      <textarea v-model="createForm.description" class="textarea" placeholder="作业说明" placeholder-class="ph" />
      <view class="dt-row">
        <picker mode="date" @change="createForm.date = $event.detail.value">
          <view class="input picker">{{ createForm.date || '截止日期' }}</view>
        </picker>
        <picker mode="time" @change="createForm.time = $event.detail.value">
          <view class="input picker">{{ createForm.time || '时间' }}</view>
        </picker>
      </view>
      <input v-model="createForm.total_score" class="input" type="digit" placeholder="总分（默认 100）" placeholder-class="ph" />
      <button class="primary-btn" :disabled="creating" :loading="creating" @click="doCreate">发布作业</button>
    </view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">还没有布置过作业</view>
      <view v-for="h in rows" :key="h.id" class="card" @click="openSubs(h)">
        <view class="h-head">
          <view class="h-title">{{ h.title }}</view>
          <text class="arrow">›</text>
        </view>
        <view class="h-chips">
          <text class="chip">{{ h.mode === 'questions' ? '题库作业' : '附件/文本' }}</text>
          <text class="chip" :class="statusTone(h.status)">{{ statusLabel(h.status) }}</text>
          <text class="chip">提交 {{ h.submission_count ?? 0 }}</text>
          <text class="chip">{{ h.total_score }} 分</text>
        </view>
        <view class="h-time">截止：{{ fmtTime(h.deadline) }}</view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listHomeworks, createHomework } from '@/api/homework.js'
import { listClasses } from '@/api/classroom.js'

const rows = ref([])
const classes = ref([])
const classCourses = ref([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ classroom: null, course: null, title: '', description: '', date: '', time: '', total_score: '' })

onShow(load)

async function load() {
  loading.value = true
  try {
    const [hw, cls] = await Promise.all([listHomeworks(), listClasses()])
    rows.value = hw.results ?? hw
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
  if (!f.title.trim()) return uni.showToast({ title: '请输入作业标题', icon: 'none' })
  creating.value = true
  try {
    await createHomework({
      classroom: f.classroom.id,
      course: f.course.id,
      title: f.title.trim(),
      description: f.description.trim(),
      deadline: f.date ? `${f.date}T${f.time || '23:59'}:00` : null,
      total_score: Number(f.total_score) || 100,
      mode: 'attachment',
      status: 'published',
    })
    uni.showToast({ title: '发布成功', icon: 'success' })
    createForm.value = { classroom: null, course: null, title: '', description: '', date: '', time: '', total_score: '' }
    showCreate.value = false
    load()
  } finally {
    creating.value = false
  }
}

function statusLabel(s) {
  return { draft: '草稿', published: '已发布', closed: '已截止' }[s] || s
}

function statusTone(s) {
  return s === 'published' ? 'success' : ''
}

function fmtTime(t) {
  if (!t) return '不限'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function openSubs(h) {
  uni.navigateTo({ url: `/pages/teacher/homework-subs?id=${h.id}&title=${encodeURIComponent(h.title)}` })
}
</script>

<style scoped>
.page { padding: 28rpx; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; }
.page-title { font-size: 32rpx; font-weight: 800; color: #0f172a; }
.tip { padding: 80rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.card { margin-bottom: 20rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.form .input, .form .textarea, .form .dt-row { margin-bottom: 16rpx; }
.input { height: 80rpx; padding: 0 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.picker { display: flex; align-items: center; color: #334155; }
.textarea { width: 100%; min-height: 140rpx; padding: 18rpx 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.dt-row { display: flex; gap: 14rpx; }
.dt-row .input { flex: 1; }
.ph { color: #94a3b8; }
.primary-btn { height: 80rpx; line-height: 80rpx; border-radius: 20rpx; background: #2563eb; color: #fff; font-size: 28rpx; font-weight: 600; }
.primary-btn::after { border: none; }
.primary-btn.small { width: auto; height: 64rpx; line-height: 64rpx; padding: 0 28rpx; font-size: 24rpx; }
.h-head { display: flex; align-items: center; justify-content: space-between; }
.h-title { flex: 1; overflow: hidden; font-size: 30rpx; font-weight: 700; color: #0f172a; text-overflow: ellipsis; white-space: nowrap; }
.arrow { font-size: 36rpx; color: #cbd5e1; }
.h-chips { display: flex; flex-wrap: wrap; gap: 10rpx; margin-top: 14rpx; }
.chip { padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 22rpx; }
.chip.success { background: #ecfdf5; color: #10b981; }
.h-time { margin-top: 12rpx; font-size: 23rpx; color: #94a3b8; }
</style>
