<template>
  <view class="page">
    <picker class="course-picker" :range="courses" range-key="name" @change="onPickCourse">
      <view class="picker-inner">
        <text class="picker-label">课程</text>
        <text class="picker-value">{{ currentCourse?.name || '请选择课程' }}</text>
        <text class="picker-arrow">▾</text>
      </view>
    </picker>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">{{ currentCourse ? '该课程暂无学生提问' : '请选择课程查看问答记录' }}</view>
      <view v-for="r in rows" :key="r.id" class="card">
        <view class="r-head">
          <text class="r-student">{{ r.student_name || '学生' }}</text>
          <text v-if="r.created_at" class="r-time">{{ fmtTime(r.created_at) }}</text>
        </view>
        <view class="r-q">Q：{{ r.question }}</view>
        <view class="r-a">{{ r.answer }}</view>
        <view v-if="r.cited_chunks?.length" class="sources">
          <text v-for="(c, i) in r.cited_chunks" :key="i" class="chip">
            📄 {{ c.material_name || '课程资料' }}{{ c.page ? ` P${c.page}` : '' }}
          </text>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listClasses } from '@/api/classroom.js'
import { listQaRecords } from '@/api/knowledge.js'

const courses = ref([])
const currentCourse = ref(null)
const rows = ref([])
const loading = ref(false)

onShow(async () => {
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
      load()
    }
  } catch {
    // 忽略
  }
})

function onPickCourse(e) {
  currentCourse.value = courses.value[Number(e.detail.value)] || null
  load()
}

async function load() {
  if (!currentCourse.value) return
  loading.value = true
  try {
    const data = await listQaRecords({ course: currentCourse.value.id, page_size: 100 })
    rows.value = [...(data.results ?? data)].sort((a, b) => b.id - a.id)
  } finally {
    loading.value = false
  }
}

function fmtTime(t) {
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style scoped>
.page { padding: 28rpx; }
.course-picker { margin-bottom: 20rpx; }
.picker-inner { display: flex; align-items: center; gap: 16rpx; padding: 22rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.picker-label { font-size: 24rpx; color: #94a3b8; }
.picker-value { flex: 1; overflow: hidden; font-size: 28rpx; font-weight: 600; color: #0f172a; text-overflow: ellipsis; white-space: nowrap; }
.picker-arrow { color: #cbd5e1; }
.tip { padding: 80rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.card { margin-bottom: 18rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.r-head { display: flex; align-items: center; justify-content: space-between; }
.r-student { font-size: 26rpx; font-weight: 700; color: #2563eb; }
.r-time { font-size: 22rpx; color: #94a3b8; }
.r-q { margin-top: 12rpx; font-size: 27rpx; font-weight: 600; line-height: 1.7; color: #0f172a; }
.r-a { margin-top: 10rpx; font-size: 26rpx; line-height: 1.8; color: #475569; white-space: pre-wrap; }
.sources { display: flex; flex-wrap: wrap; gap: 10rpx; margin-top: 14rpx; }
.chip { padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 22rpx; }
</style>
