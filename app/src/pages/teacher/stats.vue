<template>
  <view class="page">
    <view class="pickers">
      <picker :range="classes" range-key="name" @change="onPickClass">
        <view class="picker-inner">
          <text class="picker-label">班级</text>
          <text class="picker-value">{{ currentClass?.name || '请选择' }}</text>
          <text class="picker-arrow">▾</text>
        </view>
      </picker>
      <picker v-if="classCourses.length > 1" :range="classCourses" range-key="name" @change="onPickCourse">
        <view class="picker-inner">
          <text class="picker-label">课程</text>
          <text class="picker-value">{{ currentCourse?.name || '请选择' }}</text>
          <text class="picker-arrow">▾</text>
        </view>
      </picker>
    </view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else-if="stats">
      <!-- 概览 -->
      <view class="summary">
        <view class="sum-item">
          <view class="sum-num">{{ stats.summary?.student_count ?? '-' }}</view>
          <view class="sum-label">学生数</view>
        </view>
        <view class="sum-item">
          <view class="sum-num">{{ pct(stats.summary?.avg_accuracy) }}</view>
          <view class="sum-label">平均正确率</view>
        </view>
        <view class="sum-item">
          <view class="sum-num">{{ pct(stats.summary?.homework_rate) }}</view>
          <view class="sum-label">作业提交率</view>
        </view>
        <view class="sum-item">
          <view class="sum-num" :class="{ danger: stats.summary?.warning_count }">{{ stats.summary?.warning_count ?? 0 }}</view>
          <view class="sum-label">预警人数</view>
        </view>
      </view>

      <!-- AI 报告 -->
      <view class="card">
        <view class="card-head">
          <text class="card-title">AI 班级报告</text>
          <button class="text-btn" :disabled="aiLoading" @click="genReport">{{ aiLoading ? '生成中…' : '生成报告' }}</button>
        </view>
        <view v-if="aiReport" class="ai-report">{{ aiReport }}</view>
        <view v-else class="ai-empty">点击生成基于班级学习数据的 AI 分析报告</view>
      </view>

      <!-- 学生列表 -->
      <view class="section-title">学生明细（{{ stats.students?.length || 0 }}）</view>
      <view v-if="!stats.students?.length" class="tip">班级暂无学生</view>
      <view v-for="s in stats.students" :key="s.student_id" class="card stu" @click="openStudent(s)">
        <view class="stu-head">
          <view>
            <text class="stu-name">{{ s.name }}</text>
            <text class="stu-username">@{{ s.username }}</text>
          </view>
          <text class="arrow">›</text>
        </view>
        <view class="stu-metrics">
          <text class="metric">正确率 {{ pct(s.accuracy) }}</text>
          <text class="metric">作业 {{ s.homework_submitted }}/{{ s.homework_total }}</text>
          <text class="metric">考试 {{ s.exam_taken }}/{{ s.exam_total }}</text>
          <text v-if="s.avg_exam_score != null" class="metric">均分 {{ s.avg_exam_score }}</text>
        </view>
        <view v-if="s.warnings?.length" class="warn-row">
          <text class="chip danger">⚠ {{ s.warnings.join('、') }}</text>
        </view>
      </view>
    </template>
    <view v-else class="tip">请选择班级查看统计</view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listClasses } from '@/api/classroom.js'
import { getClassStats, generateClassAiReport } from '@/api/analytics.js'

const classes = ref([])
const currentClass = ref(null)
const classCourses = ref([])
const currentCourse = ref(null)
const stats = ref(null)
const loading = ref(false)
const aiReport = ref('')
const aiLoading = ref(false)

onShow(async () => {
  try {
    const data = await listClasses()
    classes.value = data.results ?? data
    if (classes.value.length) onPickClass({ detail: { value: 0 } })
  } catch {
    // 忽略
  }
})

function onPickClass(e) {
  const c = classes.value[Number(e.detail.value)]
  currentClass.value = c
  const ids = c?.courses?.length ? c.courses : [c?.course]
  classCourses.value = (ids || []).filter(Boolean).map((id, i) => ({
    id,
    name: c.course_names?.[i] || c.course_name || `课程 ${id}`,
  }))
  currentCourse.value = classCourses.value[0] || null
  load()
}

function onPickCourse(e) {
  currentCourse.value = classCourses.value[Number(e.detail.value)] || null
  load()
}

async function load() {
  if (!currentClass.value || !currentCourse.value) return
  loading.value = true
  aiReport.value = ''
  try {
    stats.value = await getClassStats(currentClass.value.id, { course: currentCourse.value.id })
  } finally {
    loading.value = false
  }
}

async function genReport() {
  aiLoading.value = true
  try {
    const res = await generateClassAiReport(currentClass.value.id, currentCourse.value.id)
    aiReport.value = res?.report || '（未生成内容）'
  } finally {
    aiLoading.value = false
  }
}

function pct(v) {
  return v == null ? '-' : `${v}%`
}

function openStudent(s) {
  uni.navigateTo({
    url: `/pages/teacher/stats-student?class=${currentClass.value.id}&student=${s.student_id}&course=${currentCourse.value.id}&name=${encodeURIComponent(s.name)}`,
  })
}
</script>

<style scoped>
.page { padding: 28rpx; }
.pickers { display: flex; flex-direction: column; gap: 14rpx; margin-bottom: 20rpx; }
.picker-inner { display: flex; align-items: center; gap: 16rpx; padding: 22rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.picker-label { font-size: 24rpx; color: #94a3b8; }
.picker-value { flex: 1; overflow: hidden; font-size: 28rpx; font-weight: 600; color: #0f172a; text-overflow: ellipsis; white-space: nowrap; }
.picker-arrow { color: #cbd5e1; }
.tip { padding: 60rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.summary { display: flex; gap: 14rpx; margin-bottom: 20rpx; }
.sum-item { flex: 1; padding: 24rpx 10rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; text-align: center; }
.sum-num { font-size: 36rpx; font-weight: 800; color: #2563eb; }
.sum-num.danger { color: #ef4444; }
.sum-label { margin-top: 6rpx; font-size: 21rpx; color: #94a3b8; }
.card { margin-bottom: 20rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.card-head { display: flex; align-items: center; justify-content: space-between; }
.card-title { font-size: 28rpx; font-weight: 700; color: #0f172a; }
.text-btn { height: 56rpx; line-height: 56rpx; padding: 0 24rpx; border-radius: 999rpx; background: #eff6ff; color: #2563eb; font-size: 24rpx; }
.text-btn::after { border: none; }
.ai-report { margin-top: 16rpx; font-size: 26rpx; line-height: 1.8; color: #334155; white-space: pre-wrap; }
.ai-empty { margin-top: 16rpx; font-size: 24rpx; color: #94a3b8; }
.section-title { margin: 8rpx 0 16rpx; font-size: 28rpx; font-weight: 700; color: #0f172a; }
.stu-head { display: flex; align-items: center; justify-content: space-between; }
.stu-name { font-size: 29rpx; font-weight: 700; color: #0f172a; }
.stu-username { margin-left: 12rpx; font-size: 23rpx; color: #94a3b8; }
.arrow { font-size: 36rpx; color: #cbd5e1; }
.stu-metrics { display: flex; flex-wrap: wrap; gap: 16rpx; margin-top: 12rpx; }
.metric { font-size: 23rpx; color: #64748b; }
.warn-row { margin-top: 12rpx; }
.chip { padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 22rpx; }
.chip.danger { background: #fef2f2; color: #ef4444; }
</style>
