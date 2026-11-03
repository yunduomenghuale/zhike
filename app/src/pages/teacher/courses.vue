<template>
  <view class="page">
    <view class="toolbar">
      <view class="page-title">课程管理</view>
      <button class="primary-btn small" @click="showCreate = !showCreate">{{ showCreate ? '收起' : '+ 新建课程' }}</button>
    </view>

    <view v-if="showCreate" class="card form">
      <input v-model="form.name" class="input" placeholder="课程名称（必填）" placeholder-class="ph" />
      <textarea v-model="form.description" class="textarea" placeholder="课程简介（可空）" placeholder-class="ph" />
      <button class="primary-btn" :disabled="creating" :loading="creating" @click="doCreate">创建课程</button>
    </view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">还没有课程，先创建一门吧</view>
      <view v-for="c in rows" :key="c.id" class="card">
        <view class="c-name">{{ c.name }}</view>
        <view v-if="c.description" class="c-desc">{{ c.description }}</view>
        <view class="ops">
          <button class="op-btn primary" @click="openCatalogs(c)">章节管理</button>
          <button class="op-btn danger" @click="removeCourse(c)">删除</button>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { listCourses, createCourse, deleteCourse } from '@/api/course.js'

const rows = ref([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const form = ref({ name: '', description: '' })

onShow(load)

async function load() {
  loading.value = true
  try {
    const data = await listCourses()
    rows.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

async function doCreate() {
  if (!form.value.name.trim()) return uni.showToast({ title: '请输入课程名称', icon: 'none' })
  creating.value = true
  try {
    await createCourse({ name: form.value.name.trim(), description: form.value.description.trim() })
    uni.showToast({ title: '创建成功', icon: 'success' })
    form.value = { name: '', description: '' }
    showCreate.value = false
    load()
  } finally {
    creating.value = false
  }
}

function openCatalogs(c) {
  uni.navigateTo({ url: `/pages/teacher/catalogs?course=${c.id}&name=${encodeURIComponent(c.name)}` })
}

function removeCourse(c) {
  uni.showModal({
    title: '删除课程',
    content: `确定删除「${c.name}」吗？课程下的章节、题目将一并删除。`,
    confirmColor: '#ef4444',
    success: async (res) => {
      if (!res.confirm) return
      await deleteCourse(c.id)
      uni.showToast({ title: '已删除', icon: 'none' })
      load()
    },
  })
}
</script>

<style scoped>
.page { padding: 28rpx; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; }
.page-title { font-size: 32rpx; font-weight: 800; color: #0f172a; }
.tip { padding: 80rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.card { margin-bottom: 20rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.form .input, .form .textarea { margin-bottom: 16rpx; }
.input { height: 80rpx; padding: 0 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.textarea { width: 100%; min-height: 140rpx; padding: 18rpx 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.ph { color: #94a3b8; }
.primary-btn { height: 80rpx; line-height: 80rpx; border-radius: 20rpx; background: #2563eb; color: #fff; font-size: 28rpx; font-weight: 600; }
.primary-btn::after { border: none; }
.primary-btn.small { width: auto; height: 64rpx; line-height: 64rpx; padding: 0 28rpx; font-size: 24rpx; }
.c-name { font-size: 30rpx; font-weight: 700; color: #0f172a; }
.c-desc { margin-top: 10rpx; font-size: 25rpx; line-height: 1.7; color: #64748b; }
.ops { display: flex; gap: 14rpx; margin-top: 18rpx; }
.op-btn { flex: 1; height: 64rpx; line-height: 64rpx; border-radius: 16rpx; font-size: 24rpx; }
.op-btn::after { border: none; }
.op-btn.primary { background: #eff6ff; color: #2563eb; }
.op-btn.danger { background: #fef2f2; color: #ef4444; }
</style>
