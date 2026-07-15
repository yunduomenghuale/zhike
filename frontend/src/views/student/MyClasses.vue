<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">我的班级</div>
        <div class="page-subtitle">输入教师提供的邀请码加入班级，即可开始学习</div>
      </div>
    </div>

    <el-card shadow="never" class="data-card join-card">
      <div class="join-bar">
        <el-input
          v-model="code"
          placeholder="输入班级邀请码（如 AKO4YCQ6）"
          :prefix-icon="Key"
          style="max-width: 320px"
          @keyup.enter="join"
        />
        <el-button type="primary" :icon="Plus" :loading="joining" @click="join">加入班级</el-button>
      </div>
    </el-card>

    <div v-loading="loading">
      <el-row :gutter="20">
        <el-col :xs="24" :sm="12" :lg="8" v-for="c in classes" :key="c.id">
          <el-card shadow="never" class="class-card">
            <div class="class-top">
              <div class="class-icon"><el-icon :size="24"><School /></el-icon></div>
              <el-tag :type="c.status === 'open' ? 'success' : 'info'" effect="light" round>
                {{ c.status === 'open' ? '开课中' : '已结课' }}
              </el-tag>
            </div>
            <div class="class-name">{{ c.name }}</div>
            <div class="class-course">{{ c.course_names?.join('、') || c.course_name || '未关联课程' }}</div>
            <div class="class-actions">
              <el-button size="small" :icon="VideoPlay" @click="$router.push('/student/learning')">去学习</el-button>
              <el-button size="small" :icon="ChatDotRound" @click="$router.push('/student/qa')">提问</el-button>
              <el-button size="small" :icon="Document" @click="$router.push('/student/exams')">考试</el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>
      <el-empty v-if="!loading && !classes.length" description="还没有加入任何班级，用上方邀请码加入吧" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { Key, Plus, School, VideoPlay, ChatDotRound, Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { listClasses, joinClass } from '@/api/classroom'

const code = ref('')
const joining = ref(false)
const classes = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await listClasses()
    classes.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

async function join() {
  const c = code.value.trim()
  if (!c) return ElMessage.warning('请输入邀请码')
  joining.value = true
  try {
    await joinClass(c)
    ElMessage.success('加入成功')
    code.value = ''
    load()
  } finally {
    joining.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.join-card {
  margin-bottom: 20px;
}
.join-bar {
  display: flex;
  gap: 12px;
  align-items: center;
}
.class-card {
  margin-bottom: 20px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.class-card:hover {
  transform: translateY(-3px);
}
.class-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.class-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #2563eb, #4f46e5);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.class-name {
  font-size: 17px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  margin-bottom: 4px;
}
.class-course {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 16px;
}
.class-actions {
  display: flex;
  gap: 8px;
}
</style>
