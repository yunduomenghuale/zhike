<template>
  <!-- 管理端全局队列看板：嵌入通知铃铛「任务」页签顶部（仅平台管理员可见）。
       数据来自 /api/ai-tasks/queue/ 与 /api/ai-tasks/worker-health/，手动刷新+打开即拉。 -->
  <div class="queue-board-entry">
    <el-button size="small" text type="primary" @click="open">全局队列看板</el-button>

    <el-drawer v-model="visible" title="AI 队列看板（全局）" size="620px" @open="refresh">
      <div v-loading="loading" class="queue-board">
        <div class="board-actions">
          <el-button size="small" :loading="loading" @click="refresh">刷新</el-button>
          <span v-if="health" class="board-hint">
            worker 心跳 {{ heartbeatAgo }}
            <template v-if="health.render_slot_mode"> · 渲染 {{ health.render_slot_mode }} 并发 {{ health.ai_render_concurrency }}</template>
          </span>
        </div>

        <div class="board-cards">
          <div class="board-card">
            <div class="board-num">{{ board?.by_status?.pending ?? '—' }}</div>
            <div class="board-label">排队中</div>
          </div>
          <div class="board-card">
            <div class="board-num">{{ board?.by_status?.running ?? '—' }}</div>
            <div class="board-label">执行中</div>
          </div>
          <div class="board-card">
            <div class="board-num warn">{{ board?.by_status?.failed ?? '—' }}</div>
            <div class="board-label">失败待处理</div>
          </div>
          <div class="board-card">
            <div class="board-num">{{ fmtWait(board?.avg_wait_seconds_24h) }}</div>
            <div class="board-label">近 24h 平均排队</div>
          </div>
        </div>

        <template v-if="health">
          <div v-if="health.render_slots_occupied?.length" class="board-slots">
            <div class="board-slot">
              <span class="slot-name">渲染占用槽</span>
              <span class="slot-val">{{ health.render_slots_occupied.join(', ') }}</span>
            </div>
          </div>
        </template>

        <div class="board-section">活跃任务（排队+执行，按类型）</div>
        <div v-if="!typeEntries.length" class="board-empty">当前无活跃任务</div>
        <div v-for="[type, n] in typeEntries" :key="type" class="board-row">
          <span>{{ TYPE_LABEL[type] || type }}</span>
          <el-tag size="small" effect="plain">{{ n }}</el-tag>
        </div>

        <template v-if="board?.top_errors?.length">
          <div class="board-section">失败原因 Top {{ board.top_errors.length }}</div>
          <div v-for="(e, i) in board.top_errors" :key="i" class="board-row">
            <span class="board-error" :title="e.error">{{ e.error }}</span>
            <el-tag size="small" type="danger" effect="plain">×{{ e.count }}</el-tag>
          </div>
        </template>

        <template v-if="board?.recent_failed?.length">
          <div class="board-section">近期失败任务</div>
          <div v-for="t in board.recent_failed" :key="t.id" class="board-row">
            <span class="board-fail-id">#{{ t.id }} {{ TYPE_LABEL[t.task_type] || t.task_type }}</span>
            <span class="board-error" :title="t.error">{{ t.error }}</span>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { getQueueBoard, getWorkerHealth } from '@/api/ai-task'

const visible = ref(false)
const loading = ref(false)
const board = ref(null)
const health = ref(null)

const TYPE_LABEL = {
  script_gen: '讲稿', audio_gen: '配音', question_gen: 'AI 生题', chapter_summary: '章节总结',
  class_analytics: '学情分析', course_reuse: '课程复用', ppt_parse: '课件解析', embed_ingest: '向量入库',
}

const typeEntries = computed(() => Object.entries(board.value?.active_by_type || {}))
const heartbeatAgo = computed(() => {
  const s = health.value?.worker_heartbeat_seconds_ago
  if (s == null) return '空闲（无执行中任务）'
  if (s < 60) return `${Math.round(s)} 秒前`
  return `${Math.round(s / 60)} 分钟前`
})
function fmtWait(sec) {
  if (sec == null) return '—'
  return sec < 60 ? `${Math.round(sec)}s` : `${(sec / 60).toFixed(1)}min`
}

async function refresh() {
  loading.value = true
  try {
    const [b, h] = await Promise.allSettled([getQueueBoard(), getWorkerHealth()])
    if (b.status === 'fulfilled') board.value = b.value?.data ?? b.value
    if (h.status === 'fulfilled') health.value = h.value?.data ?? h.value
  } finally {
    loading.value = false
  }
}
function open() {
  visible.value = true
}
</script>

<style scoped>
.queue-board-entry {
  display: inline-flex;
}
.board-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.board-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.board-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}
.board-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px 8px;
  text-align: center;
}
.board-num {
  font-size: 22px;
  font-weight: 700;
  color: var(--el-color-primary);
}
.board-num.warn {
  color: var(--el-color-danger);
}
.board-label {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.board-section {
  margin: 14px 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.board-slots {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.board-slot {
  display: inline-flex;
  gap: 6px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
}
.slot-name {
  color: var(--el-text-color-secondary);
}
.slot-val {
  font-weight: 600;
}
.board-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
  font-size: 13px;
}
.board-error {
  flex: 1;
  color: var(--el-color-danger);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.board-fail-id {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.board-empty {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  padding: 6px 0;
}
</style>
