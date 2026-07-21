<template>
  <div class="page-container">
    <div v-loading="loading">
      <el-row :gutter="16" class="class-grid animate-list">
        <el-col :xs="24" :sm="12" :lg="8">
          <button type="button" class="join-add-card" @click="joinVisible = true">
            <span class="add-icon">
              <el-icon><Plus /></el-icon>
            </span>
            <span class="add-main">加入课程</span>
            <span class="add-sub">输入邀请码，加入课程开始学习</span>
          </button>
        </el-col>
        <el-col :xs="24" :sm="12" :lg="8" v-for="c in filteredClasses" :key="`${c.classId}-${c.id}`">
          <article class="class-card" @click="openCourse(c, 'student-course-learning')">
            <span class="class-icon">
              <el-icon :size="26"><Reading /></el-icon>
            </span>
            <div class="class-main">
              <div class="class-name">{{ c.courseName }}</div>
              <div class="class-meta">
                <span class="class-chip">{{ c.className }}</span>
              </div>
            </div>
            <el-tag :type="c.status === 'open' ? 'success' : 'info'" effect="light" round class="class-status">
              {{ c.status === 'open' ? '开课中' : '已结课' }}
            </el-tag>
            <el-icon class="class-arrow"><ArrowRight /></el-icon>
          </article>
        </el-col>
      </el-row>
      <el-empty v-if="!loading && !filteredClasses.length" :description="courseCards.length ? '没有匹配的课程' : '还没有加入任何班级，点击上方卡片用邀请码加入吧'" />
    </div>

    <!-- 加入课程 -->
    <el-dialog v-model="joinVisible" width="480px" align-center :show-close="false" class="join-dialog">
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon join-dialog-icon">
            <el-icon><Key /></el-icon>
          </span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">加入课程</div>
            <div class="creation-dialog-subtitle">输入教师分享的课程邀请码</div>
          </div>
          <el-button text circle class="creation-dialog-close" :icon="Close" @click="joinVisible = false" />
        </div>
      </template>

      <div class="join-form">
        <el-input
          v-model="code"
          placeholder="如 AKO4YCQ6"
          :prefix-icon="Key"
          @keyup.enter="join"
        />
      </div>
      <template #footer>
        <div class="creation-dialog-footer">
          <el-button @click="joinVisible = false">取消</el-button>
          <el-button type="primary" :loading="joining" @click="join">加入课程</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Key, Plus, Reading, Close, ArrowRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { listClasses, joinClass } from '@/api/classroom'

const route = useRoute()
const router = useRouter()
const code = ref('')
const joining = ref(false)
const joinVisible = ref(false)
const classes = ref([])
const loading = ref(false)
const keyword = computed(() => String(route.query.search || '').trim().toLowerCase())
const courseCards = computed(() => {
  const cards = []
  classes.value.forEach((item) => {
    const ids = item.courses?.length ? item.courses : [item.course]
    ids.filter(Boolean).forEach((id, index) => {
      cards.push({
        id: Number(id),
        classId: item.id,
        className: item.name,
        courseName: item.course_names?.[index] || item.course_name || `课程 ${id}`,
        status: item.status,
      })
    })
  })
  return cards
})
const filteredClasses = computed(() => {
  if (!keyword.value) return courseCards.value
  return courseCards.value.filter((c) => [
    c.className,
    c.courseName,
  ].some((text) => String(text || '').toLowerCase().includes(keyword.value)))
})

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
    joinVisible.value = false
    load()
  } finally {
    joining.value = false
  }
}

function openCourse(course, name) {
  router.push({ name, params: { id: course.id } })
}

onMounted(load)
</script>

<style scoped>
/* 加入班级虚线卡（与课程卡同高的紧凑版） */
.join-add-card {
  min-height: 108px;
  width: 100%;
  height: 100%;
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  justify-items: start;
  gap: 4px 14px;
  padding: 18px 20px;
  border: 1px dashed var(--el-color-primary-light-5);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
  color: var(--el-color-primary);
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease, background-color 0.2s ease;
}
.join-add-card:hover {
  transform: translateY(-2px);
  border-color: var(--el-color-primary);
  background: #fff;
  box-shadow: var(--shadow-md);
}
.add-icon {
  width: 46px;
  height: 46px;
  display: grid;
  grid-row: 1 / 3;
  place-items: center;
  border-radius: 13px;
  background: var(--el-color-primary-light-9);
  font-size: 22px;
  transition: transform 0.25s ease, background-color 0.2s ease;
}
.join-add-card:hover .add-icon {
  transform: scale(1.08) rotate(3deg);
  background: var(--primary-50);
}
.add-main {
  align-self: end;
  font-size: 16px;
  font-weight: 750;
  line-height: 1.25;
}
.add-sub {
  align-self: start;
  max-width: 260px;
  color: var(--el-text-color-secondary);
  font-size: 12.5px;
  line-height: 1.5;
}

/* 加入班级弹窗（与教师端新建弹窗一致） */
.join-dialog :deep(.el-dialog),
:global(.join-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}
.join-dialog :deep(.el-dialog__header),
:global(.join-dialog.el-dialog .el-dialog__header) {
  margin: 0;
  padding: 0;
}
.join-dialog :deep(.el-dialog__body),
:global(.join-dialog.el-dialog .el-dialog__body) {
  padding: 0;
}
.join-dialog :deep(.el-dialog__footer),
:global(.join-dialog.el-dialog .el-dialog__footer) {
  padding: 0;
}
.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 86px;
  padding: 22px 24px 18px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.88);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98) 58%);
}
.creation-dialog-icon {
  width: 44px;
  height: 44px;
  display: grid;
  flex: 0 0 44px;
  place-items: center;
  border-radius: 14px;
  color: var(--primary-600);
  font-size: 21px;
}
.join-dialog-icon {
  background: #e8f4ff;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.11);
}
.creation-dialog-heading {
  min-width: 0;
  flex: 1;
}
.creation-dialog-title {
  color: #0f172a;
  font-size: 20px;
  font-weight: 760;
  line-height: 1.25;
}
.creation-dialog-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.3;
}
.creation-dialog-close {
  width: 32px;
  height: 32px;
  color: #94a3b8;
  transition: background-color 0.2s ease, color 0.2s ease;
}
.creation-dialog-close:hover {
  color: #475569;
  background: rgba(226, 232, 240, 0.7);
}
.join-form {
  padding: 22px 24px 26px;
}
.join-form :deep(.el-input__wrapper) {
  min-height: 46px;
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbe5f2;
  transition: box-shadow 0.2s ease, background-color 0.2s ease;
}
.join-form :deep(.el-input__wrapper:hover) {
  background: #fff;
  box-shadow: inset 0 0 0 1px #bfdbfe;
}
.join-form :deep(.el-input__wrapper.is-focus) {
  background: #fff;
  box-shadow: inset 0 0 0 1px var(--primary-500), 0 0 0 3px rgba(59, 130, 246, 0.12);
}
.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px 20px;
  border-top: 1px solid rgba(226, 232, 240, 0.88);
  background: rgba(248, 250, 252, 0.8);
}
.creation-dialog-footer :deep(.el-button) {
  height: 40px;
  padding: 0 17px;
  border-radius: 10px;
}
.creation-dialog-footer :deep(.el-button--primary) {
  box-shadow: 0 9px 18px rgba(37, 99, 235, 0.22);
}

/* 课程卡片（横向紧凑布局，对齐教师端课程卡） */
.class-grid {
  row-gap: 16px;
}
.class-card {
  display: flex;
  align-items: center;
  gap: 15px;
  min-height: 108px;
  padding: 18px 20px;
  border: 1px solid rgba(37, 99, 235, 0.09);
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(248, 251, 255, 0.9));
  box-shadow: 0 8px 22px rgba(37, 99, 235, 0.06);
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.class-card:hover {
  transform: translateY(-2px);
  border-color: rgba(96, 165, 250, 0.45);
  box-shadow: 0 14px 32px rgba(37, 99, 235, 0.12);
}
.class-icon {
  width: 52px;
  height: 52px;
  display: grid;
  flex: 0 0 52px;
  place-items: center;
  border-radius: 14px;
  color: var(--primary-600);
  background: linear-gradient(145deg, #eff6ff, #ffffff);
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.16);
  transition: transform 0.25s ease;
}
.class-card:hover .class-icon {
  transform: scale(1.08) rotate(-3deg);
}
.class-main {
  min-width: 0;
  flex: 1;
}
.class-name {
  overflow: hidden;
  color: var(--gray-900);
  font-size: 17px;
  font-weight: 750;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.class-meta {
  margin: 7px 0 0;
}
.class-chip {
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--gray-100);
  color: var(--gray-500);
  font-size: 12px;
}
.class-status {
  flex-shrink: 0;
}
.class-arrow {
  flex-shrink: 0;
  color: var(--gray-300);
  font-size: 16px;
  transition: color 0.18s ease, transform 0.18s ease;
}
.class-card:hover .class-arrow {
  color: var(--primary-600);
  transform: translateX(3px);
}

@media (max-width: 640px) {
  .join-bar {
    align-items: stretch;
  }
  .join-bar :deep(.el-input),
  .join-bar :deep(.el-button) {
    width: 100%;
    max-width: none !important;
  }
}
</style>
