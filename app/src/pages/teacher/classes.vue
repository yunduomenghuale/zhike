<template>
  <view class="page">
    <view class="toolbar">
      <view class="page-title">班级管理</view>
    </view>
    <view class="hint">班级由学校统一分配，如需调整请联系管理员</view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">暂无可管理的班级</view>
      <view v-for="c in rows" :key="c.id" class="card">
        <view class="c-head">
          <view class="c-name">{{ c.name }}</view>
          <text class="chip" :class="{ success: c.status === 'active' }">
            {{ classStatusLabel(c.status) }}
          </text>
        </view>
        <view class="c-courses">
          <text v-for="(n, i) in c.course_names || []" :key="i" class="chip">{{ n }}</text>
          <text class="chip">学生 {{ c.student_count ?? 0 }} 人</text>
        </view>

        <!-- 只读名单：加人 / 移人由管理员在管理端操作 -->
        <view class="ops">
          <button class="op-btn" @click="toggleStudents(c)">{{ expandedId === c.id ? '收起名单' : '查看名单' }}</button>
        </view>

        <view v-if="expandedId === c.id" class="students">
          <view v-if="!students.length" class="tip small-tip">暂无学生</view>
          <view v-for="s in students" :key="s.id" class="stu-row">
            <view class="stu-info">
              <text class="stu-name">{{ s.student_name || s.username }}</text>
              <text class="stu-sub">@{{ s.username }} · {{ fmtDate(s.joined_at) }} 加入</text>
            </view>
          </view>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listClasses, listClassStudents } from '@/api/classroom.js'
import { classStatusLabel } from '@/utils/classStatus.js'

const rows = ref([])
const loading = ref(false)
const expandedId = ref(null)
const students = ref([])

onShow(load)

async function load() {
  loading.value = true
  try {
    const cls = await listClasses()
    rows.value = cls.results ?? cls
  } finally {
    loading.value = false
  }
}

async function toggleStudents(c) {
  if (expandedId.value === c.id) {
    expandedId.value = null
    return
  }
  expandedId.value = c.id
  const data = await listClassStudents({ classroom: c.id })
  students.value = data.results ?? data
}

function fmtDate(t) {
  if (!t) return '-'
  const d = new Date(t)
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}
</script>

<style scoped>
.page { padding: 28rpx; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12rpx; }
.page-title { font-size: 32rpx; font-weight: 800; color: #0f172a; }
.hint { margin-bottom: 20rpx; padding: 16rpx 20rpx; border-radius: 14rpx; background: #f8fafc; color: #94a3b8; font-size: 24rpx; }
.tip { padding: 80rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.small-tip { padding: 30rpx 0; }
.card { margin-bottom: 20rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.c-head { display: flex; align-items: center; justify-content: space-between; }
.c-name { font-size: 30rpx; font-weight: 700; color: #0f172a; }
.c-courses { display: flex; flex-wrap: wrap; gap: 10rpx; margin-top: 14rpx; }
.chip { padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 22rpx; }
.chip.success { background: #ecfdf5; color: #10b981; }
.ops { display: flex; gap: 14rpx; margin-top: 18rpx; }
.op-btn { flex: 1; height: 64rpx; line-height: 64rpx; border-radius: 16rpx; background: #f1f5f9; color: #475569; font-size: 24rpx; }
.op-btn::after { border: none; }
.students { margin-top: 18rpx; padding-top: 18rpx; border-top: 1rpx solid #f1f5f9; }
.stu-row { display: flex; align-items: center; padding: 16rpx 0; border-bottom: 1rpx solid #f8fafc; }
.stu-row:last-child { border-bottom: none; }
.stu-info { flex: 1; }
.stu-name { font-size: 27rpx; font-weight: 600; color: #0f172a; }
.stu-sub { display: block; margin-top: 4rpx; font-size: 22rpx; color: #94a3b8; }
</style>
