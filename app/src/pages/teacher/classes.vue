<template>
  <view class="page">
    <view class="toolbar">
      <view class="page-title">班级管理</view>
      <button class="primary-btn small" @click="showCreate = !showCreate">{{ showCreate ? '收起' : '+ 新建班级' }}</button>
    </view>

    <!-- 新建班级 -->
    <view v-if="showCreate" class="card form">
      <input v-model="createForm.name" class="input" placeholder="班级名称（必填）" placeholder-class="ph" />
      <picker :range="courses" range-key="name" @change="createForm.course = courses[Number($event.detail.value)]">
        <view class="input picker">
          {{ createForm.course?.name || '选择关联课程（必选）' }}
        </view>
      </picker>
      <button class="primary-btn" :disabled="creating" :loading="creating" @click="doCreate">创建班级</button>
    </view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">还没有班级，先创建一个吧</view>
      <view v-for="c in rows" :key="c.id" class="card">
        <view class="c-head">
          <view class="c-name">{{ c.name }}</view>
          <text class="chip" :class="{ success: c.status === 'open' }">
            {{ c.status === 'open' ? '开课中' : '已结课' }}
          </text>
        </view>
        <view class="c-courses">
          <text v-for="(n, i) in c.course_names || []" :key="i" class="chip">{{ n }}</text>
          <text class="chip">学生 {{ c.student_count ?? 0 }} 人</text>
        </view>

        <!-- 邀请码 -->
        <view class="invite" :class="{ off: !c.invite_enabled }">
          <text class="invite-code">{{ c.invite_code }}</text>
          <text class="invite-act" @click="copyCode(c)">复制</text>
          <text class="invite-act" @click="regen(c)">换码</text>
          <text class="invite-act" @click="toggleInvite(c)">{{ c.invite_enabled ? '关闭' : '开启' }}</text>
        </view>

        <!-- 操作 -->
        <view class="ops">
          <button class="op-btn" @click="toggleStudents(c)">{{ expandedId === c.id ? '收起学生' : `学生管理` }}</button>
          <button class="op-btn danger" @click="removeClass(c)">删除班级</button>
        </view>

        <!-- 学生管理 -->
        <view v-if="expandedId === c.id" class="students">
          <view class="add-row">
            <input v-model="addUsername" class="input" placeholder="输入学生用户名添加" placeholder-class="ph" />
            <button class="primary-btn small" :disabled="adding" @click="doAddStudent(c)">添加</button>
          </view>
          <view v-if="!students.length" class="tip small-tip">暂无学生</view>
          <view v-for="s in students" :key="s.id" class="stu-row">
            <view class="stu-info">
              <text class="stu-name">{{ s.student_name || s.username }}</text>
              <text class="stu-sub">@{{ s.username }} · {{ fmtDate(s.joined_at) }} 加入</text>
            </view>
            <text class="stu-del" @click="removeStudent(s)">移除</text>
          </view>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import {
  listClasses, createClass, deleteClass, patchClass, regenerateCode,
  listClassStudents, addStudent, removeClassStudent,
} from '@/api/classroom.js'
import { listCourses } from '@/api/course.js'

const rows = ref([])
const courses = ref([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ name: '', course: null })
const expandedId = ref(null)
const students = ref([])
const addUsername = ref('')
const adding = ref(false)

onShow(load)

async function load() {
  loading.value = true
  try {
    const [cls, cs] = await Promise.all([listClasses(), listCourses()])
    rows.value = cls.results ?? cls
    courses.value = (cs.results ?? cs).map((c) => ({ id: c.id, name: c.name }))
  } finally {
    loading.value = false
  }
}

async function doCreate() {
  if (!createForm.value.name.trim()) return uni.showToast({ title: '请输入班级名称', icon: 'none' })
  if (!createForm.value.course?.id) return uni.showToast({ title: '请选择关联课程', icon: 'none' })
  creating.value = true
  try {
    await createClass({ name: createForm.value.name.trim(), courses: [createForm.value.course.id] })
    uni.showToast({ title: '创建成功', icon: 'success' })
    createForm.value = { name: '', course: null }
    showCreate.value = false
    load()
  } finally {
    creating.value = false
  }
}

function copyCode(c) {
  uni.setClipboardData({ data: c.invite_code, success: () => uni.showToast({ title: '邀请码已复制', icon: 'none' }) })
}

async function regen(c) {
  const res = await regenerateCode(c.id)
  c.invite_code = res.invite_code
  uni.showToast({ title: '已生成新邀请码', icon: 'none' })
}

async function toggleInvite(c) {
  await patchClass(c.id, { invite_enabled: !c.invite_enabled })
  c.invite_enabled = !c.invite_enabled
  uni.showToast({ title: c.invite_enabled ? '邀请码已开启' : '邀请码已关闭', icon: 'none' })
}

function removeClass(c) {
  uni.showModal({
    title: '删除班级',
    content: `确定删除「${c.name}」吗？班级学生关系将一并删除。`,
    confirmColor: '#ef4444',
    success: async (res) => {
      if (!res.confirm) return
      await deleteClass(c.id)
      uni.showToast({ title: '已删除', icon: 'none' })
      load()
    },
  })
}

async function toggleStudents(c) {
  if (expandedId.value === c.id) {
    expandedId.value = null
    return
  }
  expandedId.value = c.id
  addUsername.value = ''
  const data = await listClassStudents({ classroom: c.id })
  students.value = data.results ?? data
}

async function doAddStudent(c) {
  const username = addUsername.value.trim()
  if (!username) return uni.showToast({ title: '请输入用户名', icon: 'none' })
  adding.value = true
  try {
    await addStudent(c.id, username)
    uni.showToast({ title: '添加成功', icon: 'success' })
    addUsername.value = ''
    const data = await listClassStudents({ classroom: c.id })
    students.value = data.results ?? data
    load()
  } finally {
    adding.value = false
  }
}

function removeStudent(s) {
  uni.showModal({
    title: '移除学生',
    content: `确定把 ${s.student_name || s.username} 移出班级吗？`,
    confirmColor: '#ef4444',
    success: async (res) => {
      if (!res.confirm) return
      await removeClassStudent(s.id)
      students.value = students.value.filter((x) => x.id !== s.id)
      load()
    },
  })
}

function fmtDate(t) {
  if (!t) return '-'
  const d = new Date(t)
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}
</script>

<style scoped>
.page { padding: 28rpx; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20rpx; }
.page-title { font-size: 32rpx; font-weight: 800; color: #0f172a; }
.tip { padding: 80rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.small-tip { padding: 30rpx 0; }
.card { margin-bottom: 20rpx; padding: 26rpx 28rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.form .input { margin-bottom: 16rpx; }
.input { height: 80rpx; padding: 0 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.picker { display: flex; align-items: center; color: #334155; }
.ph { color: #94a3b8; }
.primary-btn { height: 80rpx; line-height: 80rpx; border-radius: 20rpx; background: #2563eb; color: #fff; font-size: 28rpx; font-weight: 600; }
.primary-btn::after { border: none; }
.primary-btn.small { width: auto; height: 64rpx; line-height: 64rpx; padding: 0 28rpx; font-size: 24rpx; }
.c-head { display: flex; align-items: center; justify-content: space-between; }
.c-name { font-size: 30rpx; font-weight: 700; color: #0f172a; }
.c-courses { display: flex; flex-wrap: wrap; gap: 10rpx; margin-top: 14rpx; }
.chip { padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; font-size: 22rpx; }
.chip.success { background: #ecfdf5; color: #10b981; }
.invite { display: flex; align-items: center; gap: 20rpx; margin-top: 18rpx; padding: 16rpx 20rpx; border-radius: 14rpx; background: #eff6ff; }
.invite.off { background: #f1f5f9; }
.invite.off .invite-code { color: #94a3b8; text-decoration: line-through; }
.invite-code { flex: 1; font-size: 30rpx; font-weight: 800; letter-spacing: 4rpx; color: #2563eb; }
.invite-act { font-size: 24rpx; color: #2563eb; }
.ops { display: flex; gap: 14rpx; margin-top: 18rpx; }
.op-btn { flex: 1; height: 64rpx; line-height: 64rpx; border-radius: 16rpx; background: #f1f5f9; color: #475569; font-size: 24rpx; }
.op-btn::after { border: none; }
.op-btn.danger { background: #fef2f2; color: #ef4444; }
.students { margin-top: 18rpx; padding-top: 18rpx; border-top: 1rpx solid #f1f5f9; }
.add-row { display: flex; gap: 14rpx; margin-bottom: 10rpx; }
.add-row .input { flex: 1; }
.stu-row { display: flex; align-items: center; padding: 16rpx 0; border-bottom: 1rpx solid #f8fafc; }
.stu-row:last-child { border-bottom: none; }
.stu-info { flex: 1; }
.stu-name { font-size: 27rpx; font-weight: 600; color: #0f172a; }
.stu-sub { display: block; margin-top: 4rpx; font-size: 22rpx; color: #94a3b8; }
.stu-del { font-size: 24rpx; color: #ef4444; }
</style>
