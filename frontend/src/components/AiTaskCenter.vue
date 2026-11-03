<template>
  <!-- AI 任务面板：嵌入通知铃铛的「任务」页签（MainLayout）。队列化后服务端是唯一真相。 -->
  <div class="task-center-body">
    <div v-if="isAdmin" class="task-board-entry">
      <AdminQueueBoard />
    </div>
    <el-empty v-if="!sorted.length" description="暂无任务" :image-size="70" />
    <div v-for="item in sorted" :key="item.taskId" class="task-item">
      <div class="task-item-head">
        <span class="task-item-type">{{ typeLabel(item.taskType) }}</span>
        <span class="task-item-title">{{ item.catalogTitle || `章节 #${item.catalogId}` }}</span>
        <el-tag size="small" :type="statusType(item.status)" effect="light">
          {{ statusLabel(item) }}
        </el-tag>
      </div>
      <div class="task-item-progress">
        <el-progress
          :percentage="progressPercent(item)"
          :status="item.status === 'failed' || item.status === 'cancelled' ? 'exception' : item.status === 'success' ? 'success' : undefined"
          :stroke-width="8"
        />
      </div>
      <div v-if="item.status === 'pending' && item.queuePosition" class="task-item-queue">
        排队第 {{ item.queuePosition }} 位
      </div>
      <div v-if="item.error && (item.status === 'failed' || item.status === 'cancelled')" class="task-item-error" :title="item.error">{{ item.error }}</div>
      <div class="task-item-actions">
        <el-button
          v-if="item.status === 'pending' || item.status === 'running'"
          size="small"
          text
          type="danger"
          @click="genStore.cancelTask(item.taskId)"
        >取消</el-button>
        <el-button
          v-if="item.status === 'failed' || item.status === 'cancelled'"
          size="small"
          text
          type="primary"
          @click="genStore.retryTask(item.taskId)"
        >重试</el-button>
        <el-button
          v-if="item.status === 'success' || item.status === 'failed' || item.status === 'cancelled'"
          size="small"
          text
          @click="genStore.dismissTask(item.taskId)"
        >清除</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useGenerationStore } from '@/store/generation'
import { useUserStore } from '@/store/user'
import AdminQueueBoard from '@/components/AdminQueueBoard.vue'

const genStore = useGenerationStore()
const { profile } = storeToRefs(useUserStore())
const isAdmin = computed(() => profile.value?.role === 'admin')

onMounted(() => genStore.refreshActive())

const sorted = computed(() =>
  Object.values(genStore.tracked).sort((a, b) => b.taskId - a.taskId).slice(0, 20),
)

const TYPE_LABEL = {
  script_gen: '讲稿',
  audio_gen: '配音',
  question_gen: 'AI 生题',
  chapter_summary: '章节总结',
  class_analytics: '学情分析',
  course_reuse: '课程复用',
  ppt_parse: '课件解析',
  embed_ingest: '向量入库',
}
function typeLabel(t) {
  return TYPE_LABEL[t] || t
}
const QUEUE_LABEL = {
  script_gen: '讲稿',
  audio_gen: '配音',
  question_gen: '生题',
  chapter_summary: '总结',
  class_analytics: '学情',
  course_reuse: '复用',
  ppt_parse: '解析',
  embed_ingest: '入库',
}
function statusLabel(item) {
  // 排队位是分型队列内的名次（各类型槽位独立、互不等位）——标注类型避免误读为全局名次
  if (item.status === 'pending') {
    return item.queuePosition ? `${QUEUE_LABEL[item.taskType] || ''}队列第 ${item.queuePosition} 位` : '排队中'
  }
  if (item.status === 'running') return '进行中'
  if (item.status === 'success') return '已完成'
  if (item.status === 'cancelled') return '已取消'
  return '失败'
}
function statusType(status) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'info'
  if (status === 'running') return 'primary'
  return 'warning'
}
function progressPercent(item) {
  // 已完成恒 100：兜底后端「progress 写满」与「状态翻转」非原子时的定格竞态
  if (item.status === 'success') return 100
  if (!item.total) return 0
  return Math.min(100, Math.round((item.done / item.total) * 100))
}
</script>

<style scoped>
.task-center-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 420px;
  overflow-y: auto;
}
.task-board-entry {
  display: flex;
  justify-content: flex-end;
}
.task-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px 12px;
}
.task-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.task-item-type {
  font-weight: 600;
  font-size: 13px;
}
.task-item-title {
  flex: 1;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-item-queue {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-color-warning);
}
.task-item-error {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-color-danger);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-item-actions {
  margin-top: 4px;
  display: flex;
  gap: 4px;
}
</style>
